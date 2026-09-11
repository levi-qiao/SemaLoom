import { useEffect, useMemo, useState } from "react";

type Counts = { objects: number; links: number; mappings: number; sources: number; rules: number };
type GraphMeta = {
  releaseDigest: string;
  onlineValidation: string;
  packs: { id: string; label: string; version: string }[];
  counts: Counts;
};
type Node = {
  id: string;
  label: string;
  namespace: string;
  properties: string[];
  metricCount: number;
  ruleCount: number;
  mappingCount: number;
  sourceCount: number;
};
type Edge = {
  id: string;
  label: string;
  source: string;
  target: string;
  cardinality: string;
  sourceKey: string;
  targetKey: string;
};
type Mapping = {
  id: string;
  label: string;
  target: string;
  objectType: string;
  sourceId: string;
  provider: string;
  resource: string;
  fieldCount: number;
  completeness: string;
  expectedCardinality: string;
  perspective: string | null;
};
type Source = {
  id: string;
  label: string;
  sourceId: string;
  provider: string;
  mappingCount: number;
  actionCount: number;
  targets: string[];
  namespaces: string[];
  status: string;
};
type Inspector = {
  id: string;
  label: string;
  version: string;
  namespace: string;
  identityKeys: string[];
  properties: { id: string; label?: string; valueType: string; required: boolean }[];
  metrics: { id: string; label: string; valueType: string; unit: string; perspective: string | null }[];
  mappings: Mapping[];
  rules: { id: string; label: string; claim: string | null }[];
  relations: {
    id: string;
    label: string;
    direction: string;
    target: string;
    targetLabel: string;
    cardinality: string;
  }[];
};
type View = "graph" | "list" | "mappings" | "sources";
type Position = { x: number; y: number };

const TOKEN = "tenant-a-modeler";
const headers = { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" };
const viewNames: Record<View, { title: string; description: string }> = {
  graph: { title: "实体关系", description: "从业务实体出发，检查关系、规则与来源覆盖。" },
  list: { title: "实体目录", description: "按稳定语义标识浏览当前发布中的全部实体。" },
  mappings: { title: "来源映射", description: "追踪业务定义与数据库表、API 操作之间的绑定。" },
  sources: { title: "数据源", description: "查看独立接入层中的来源、协议和影响范围。" },
};

function viewFromUrl(): View | null {
  const value = new URLSearchParams(window.location.search).get("view");
  return value && value in viewNames ? (value as View) : null;
}

export default function App() {
  const [hasExplicitView] = useState(() => viewFromUrl() !== null);
  const [initialEntity] = useState(() => new URLSearchParams(window.location.search).get("entity"));
  const [view, setView] = useState<View>(() => viewFromUrl() ?? "graph");
  const [meta, setMeta] = useState<GraphMeta | null>(null);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selected, setSelected] = useState<string | null>(
    () => initialEntity,
  );
  const [inspector, setInspector] = useState<Inspector | null>(null);
  const [mappings, setMappings] = useState<Mapping[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [search, setSearch] = useState("");
  const [revision, setRevision] = useState(0);
  const [status, setStatus] = useState("正在同步工作区");
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadInitialState();
  }, []);

  useEffect(() => {
    if (!selected) return;
    fetch(`/v0.1/studio/inspector?objectId=${encodeURIComponent(selected)}`, { headers })
      .then(checkedJson)
      .then(setInspector)
      .catch((cause: Error) => setError(cause.message));
  }, [selected]);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("view", view);
    if (selected) url.searchParams.set("entity", selected);
    else url.searchParams.delete("entity");
    window.history.replaceState(null, "", url);
  }, [view, selected]);

  async function loadInitialState(preferSaved = false) {
    try {
      setError(null);
      const [graphPayload, mappingPayload, sourcePayload, draftPayload] = await Promise.all([
        fetch("/v0.1/studio/graph", { headers }).then(checkedJson),
        fetch("/v0.1/studio/mappings", { headers }).then(checkedJson),
        fetch("/v0.1/studio/sources", { headers }).then(checkedJson),
        fetch("/v0.1/studio/drafts/default", { headers }).then(checkedJson),
      ]);
      setMeta(graphPayload.meta);
      setNodes(graphPayload.nodes);
      setEdges(graphPayload.edges);
      setMappings(mappingPayload.mappings ?? []);
      setSources(sourcePayload.sources ?? []);
      setRevision(draftPayload.revision);
      setConflict(false);
      const saved = draftPayload.payload ?? {};
      const candidate = !preferSaved && initialEntity ? initialEntity : saved.selected;
      const selectedId = graphPayload.nodes.some((node: Node) => node.id === candidate)
        ? candidate
        : graphPayload.nodes[0]?.id;
      setSelected(selectedId ?? null);
      if ((preferSaved || !hasExplicitView) && saved.view in viewNames) setView(saved.view);
      if ((preferSaved || !hasExplicitView) && typeof saved.search === "string") setSearch(saved.search);
      else setSearch("");
      setStatus(draftPayload.exists ? `工作区已同步 · r${draftPayload.revision}` : "新工作区");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
      setStatus("同步失败");
    }
  }

  async function saveWorkspace() {
    setSaving(true);
    setStatus("正在保存");
    setError(null);
    try {
      const response = await fetch("/v0.1/studio/drafts/default", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          expectedRevision: revision,
          payload: { selected, view, search },
        }),
      });
      if (response.status === 409) {
        setConflict(true);
        setStatus("工作区有新版本");
        return;
      }
      const payload = await checkedJson(response);
      setRevision(payload.revision);
      setConflict(false);
      setStatus(`已保存 · r${payload.revision}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
      setStatus("保存失败");
    } finally {
      setSaving(false);
    }
  }

  function showMappings(filter: string) {
    setSearch(filter);
    setView("mappings");
  }

  function navigate(nextView: View) {
    setSearch("");
    setView(nextView);
  }

  const activeTitle = viewNames[view];
  const normalizedSearch = search.trim().toLowerCase();
  const filteredNodes = nodes.filter((node) =>
    `${node.label} ${node.id} ${node.namespace}`.toLowerCase().includes(normalizedSearch),
  );
  const filteredMappings = mappings.filter((item) =>
    `${item.id} ${item.target} ${item.sourceId} ${item.resource} ${item.provider}`
      .toLowerCase()
      .includes(normalizedSearch),
  );
  const filteredSources = sources.filter((item) =>
    `${item.id} ${item.label} ${item.sourceId} ${item.provider} ${item.targets.join(" ")}`
      .toLowerCase()
      .includes(normalizedSearch),
  );

  return (
    <div className="shell">
      <nav aria-label="工作台导航">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">SL</span>
          <div><strong>SemaLoom</strong><small>Semantic Studio</small></div>
        </div>
        <NavGroup label="语义模型">
          <NavButton label="实体关系" active={view === "graph"} onClick={() => navigate("graph")} />
          <NavButton label="实体目录" active={view === "list"} onClick={() => navigate("list")} />
        </NavGroup>
        <NavGroup label="独立接入层">
          <NavButton label="来源映射" active={view === "mappings"} onClick={() => navigate("mappings")} />
          <NavButton label="数据源" active={view === "sources"} onClick={() => navigate("sources")} />
        </NavGroup>
        <div className="nav-spacer" />
        <div className="environment">
          <span className="status-dot" aria-hidden="true" />
          <span><strong>本地合成环境</strong><small>未连接真实业务数据</small></span>
        </div>
      </nav>
      <main>
        <header>
          <div className="context-title">
            <small>模型工作区 / 合成发布</small>
            <strong>企业语义模型</strong>
          </div>
          <div className="header-actions">
            {meta ? <span className="release-ref" title={meta.releaseDigest}>v0.1 · {meta.releaseDigest.slice(0, 7)}</span> : null}
            <span className={conflict ? "save-status conflict" : "save-status"}>{status}</span>
            {conflict ? <button className="secondary" onClick={() => void loadInitialState(true)}>重新载入</button> : null}
            <button className="primary" disabled={saving} onClick={() => void saveWorkspace()}>
              保存工作区
            </button>
          </div>
        </header>
        {error ? <div className="error" role="alert"><span>加载失败：{error}</span><button onClick={() => void loadInitialState()}>重试</button></div> : null}
        <div className="view-heading">
          <div><p className="eyebrow">{view === "graph" || view === "list" ? "ONTOLOGY" : "INTEGRATION"}</p><h1>{activeTitle.title}</h1><p>{activeTitle.description}</p></div>
          <label className="search-field">
            <span className="sr-only">搜索当前视图</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称、ID 或来源" />
            {search ? <button aria-label="清除搜索" onClick={() => setSearch("")}>清除</button> : null}
          </label>
        </div>
        <section className="workspace">
          <div className="content-pane">
            {view === "graph" ? <EntityGraph nodes={filteredNodes} allNodes={nodes} edges={edges} selected={selected} onSelect={setSelected} /> : null}
            {view === "list" ? <EntityTable nodes={filteredNodes} selected={selected} onSelect={setSelected} /> : null}
            {view === "mappings" ? <MappingTable items={filteredMappings} selected={selected} onSelect={setSelected} /> : null}
            {view === "sources" ? <SourceCatalog items={filteredSources} onShowMappings={showMappings} /> : null}
            {normalizedSearch && ((view === "graph" || view === "list") ? filteredNodes.length === 0 : view === "mappings" ? filteredMappings.length === 0 : filteredSources.length === 0) ? <EmptySearch onClear={() => setSearch("")} /> : null}
          </div>
          <EntityInspector inspector={inspector} onSelect={setSelected} onShowMappings={showMappings} />
        </section>
      </main>
    </div>
  );
}

function NavGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="nav-group"><p className="nav-label">{label}</p>{children}</div>;
}

function NavButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return <button aria-pressed={active} className={active ? "active" : ""} onClick={onClick}>{label}</button>;
}

function EntityGraph({ nodes, allNodes, edges, selected, onSelect }: { nodes: Node[]; allNodes: Node[]; edges: Edge[]; selected: string | null; onSelect: (id: string) => void }) {
  const visible = new Set(nodes.map((node) => node.id));
  const layout = useMemo(() => buildLayout(allNodes), [allNodes]);
  const groups = useMemo(() => [...new Set(allNodes.map((node) => node.namespace))], [allNodes]);
  const height = Math.max(620, groups.length * 280 + 28);
  return (
    <div className="graph-panel">
      <div className="graph-legend"><span><i className="legend-node" />实体定义</span><span><i className="legend-edge" />业务关系</span><span>{nodes.length} 个实体 · {edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)).length} 条关系</span></div>
      <svg viewBox={`0 0 980 ${height}`} role="img" aria-label="实体关系图">
        <defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
        {groups.map((group, index) => <g key={group}><rect className="domain-area" x="24" y={index * 280 + 28} width="932" height="244" rx="8" /><text className="domain-label" x="48" y={index * 280 + 61}>{group.toUpperCase()}</text></g>)}
        {edges.map((edge) => {
          if (!visible.has(edge.source) || !visible.has(edge.target)) return null;
          const from = layout[edge.source]; const to = layout[edge.target];
          if (!from || !to) return null;
          const forward = to.x >= from.x;
          const x1 = forward ? from.x + 240 : from.x; const x2 = forward ? to.x : to.x + 240;
          const mid = (x1 + x2) / 2;
          return <g key={edge.id}><line x1={x1} y1={from.y + 54} x2={x2} y2={to.y + 54} /><rect className="edge-label-bg" x={mid - 25} y={from.y + 35} width="50" height="28" rx="4" /><text className="edge-label" x={mid} y={from.y + 49}>{edge.label}</text><text className="edge-cardinality" x={mid} y={from.y + 60}>{edge.cardinality}</text></g>;
        })}
        {nodes.map((node) => {
          const pos = layout[node.id];
          return <g key={node.id} role="button" tabIndex={0} aria-pressed={selected === node.id} aria-label={`选择实体 ${node.label}`} onClick={() => onSelect(node.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(node.id); } }}>
            <rect x={pos.x} y={pos.y} width="240" height="108" rx="6" className={selected === node.id ? "node selected" : "node"} />
            <text x={pos.x + 16} y={pos.y + 29} className="node-title">{node.label}</text>
            <text x={pos.x + 16} y={pos.y + 51} className="node-id">{node.id}</text>
            <line className="node-divider" x1={pos.x + 16} y1={pos.y + 67} x2={pos.x + 224} y2={pos.y + 67} />
            <text x={pos.x + 16} y={pos.y + 91} className="node-count">{node.properties.length} 属性</text>
            <text x={pos.x + 92} y={pos.y + 91} className="node-count">{node.metricCount} 指标</text>
            <text x={pos.x + 164} y={pos.y + 91} className="node-count">{node.sourceCount} 来源</text>
          </g>;
        })}
      </svg>
    </div>
  );
}

function buildLayout(nodes: Node[]): Record<string, Position> {
  const groups = [...new Set(nodes.map((node) => node.namespace))];
  const positions: Record<string, Position> = {};
  groups.forEach((group, groupIndex) => {
    nodes.filter((node) => node.namespace === group).forEach((node, index) => {
      positions[node.id] = { x: 56 + index * 292, y: groupIndex * 280 + 102 };
    });
  });
  return positions;
}

function EntityTable({ nodes, selected, onSelect }: { nodes: Node[]; selected: string | null; onSelect: (id: string) => void }) {
  return <TableFrame count={nodes.length} label="实体"><table><thead><tr><th>实体</th><th>Semantic ID</th><th>定义</th><th>接入覆盖</th></tr></thead><tbody>{nodes.map((node) => <tr key={node.id} data-selected={selected === node.id}><td><button className="text-button" onClick={() => onSelect(node.id)}>{node.label}</button></td><td><code>{node.id}</code></td><td>{node.properties.length} 属性 · {node.metricCount} 指标 · {node.ruleCount} 规则</td><td>{node.mappingCount} Mapping · {node.sourceCount} 来源</td></tr>)}</tbody></table></TableFrame>;
}

function MappingTable({ items, selected, onSelect }: { items: Mapping[]; selected: string | null; onSelect: (id: string) => void }) {
  return <TableFrame count={items.length} label="Mapping"><table><thead><tr><th>业务目标</th><th>Mapping</th><th>数据源 / 资源</th><th>契约</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} data-selected={selected === item.objectType}><td><button className="text-button" onClick={() => onSelect(item.objectType)}>{item.target}</button><small className="cell-note">归属 {item.objectType}</small></td><td><code>{item.id}</code></td><td><strong>{item.sourceId}</strong><small className="cell-note"><ProviderMark provider={item.provider} /> {item.resource}</small></td><td><span className="contract">{item.completeness === "AUTHORITATIVE" ? "权威" : "部分"}</span><small className="cell-note">{item.fieldCount} 字段 · {item.expectedCardinality}</small></td></tr>)}</tbody></table></TableFrame>;
}

function SourceCatalog({ items, onShowMappings }: { items: Source[]; onShowMappings: (source: string) => void }) {
  return <div className="source-grid">{items.map((item) => <article className="source-card" key={item.id}><div className="source-card-head"><ProviderMark provider={item.provider} large /><span className={item.status === "PASSED" ? "source-state verified" : "source-state"}>{item.status === "PASSED" ? "已验证" : "未在线验证"}</span></div><h2>{item.label}</h2><code>{item.id}</code><dl><div><dt>Mapping</dt><dd>{item.mappingCount}</dd></div><div><dt>Action</dt><dd>{item.actionCount}</dd></div><div><dt>影响目标</dt><dd>{item.targets.length}</dd></div></dl><div className="source-targets">{item.namespaces.map((namespace) => <span key={namespace}>{namespace}</span>)}</div>{item.mappingCount ? <button className="secondary full" onClick={() => onShowMappings(item.sourceId)}>查看 Mapping</button> : <p className="source-note">仅用于受控 Action，没有读取 Mapping。</p>}</article>)}</div>;
}

function EntityInspector({ inspector, onSelect, onShowMappings }: { inspector: Inspector | null; onSelect: (id: string) => void; onShowMappings: (filter: string) => void }) {
  return <aside className="inspector" aria-label="实体检查器">{inspector ? <><div className="inspector-kicker"><span>{inspector.namespace}</span><span>v{inspector.version}</span></div><h2>{inspector.label}</h2><code className="semantic-id">{inspector.id}</code><div className="meta-row"><span>业务键</span><strong>{inspector.identityKeys.join(", ")}</strong></div><DefinitionList title="属性" items={inspector.properties.map((item) => ({ label: item.label ?? item.id, id: item.id, meta: `${item.valueType}${item.required ? " · 必需" : ""}` }))} /><DefinitionList title="指标" items={inspector.metrics.map((item) => ({ label: item.label, id: item.id, meta: `${item.valueType} · ${item.unit}` }))} /><DefinitionList title="规则" items={inspector.rules.map((item) => ({ label: item.label, id: item.id }))} /><section className="definition-section"><div className="section-heading"><h3>关系</h3><span>{inspector.relations.length}</span></div>{inspector.relations.length ? <ul className="definition-list">{inspector.relations.map((item) => <li key={item.id}><button className="definition-link" onClick={() => onSelect(item.target)}><span>{item.label}</span><small>{item.direction === "OUTGOING" ? "→" : "←"} {item.targetLabel}</small></button></li>)}</ul> : <p className="empty">尚无业务关系</p>}</section><section className="definition-section"><div className="section-heading"><h3>来源追踪</h3><span>{inspector.mappings.length}</span></div>{inspector.mappings.length ? <ol className="trace-list">{inspector.mappings.map((item) => <li key={item.id}><button onClick={() => onShowMappings(item.id)}><span className="trace-target">{item.target}</span><span className="trace-line" aria-hidden="true" /><span className="trace-source"><ProviderMark provider={item.provider} /> {item.sourceId} / {item.resource}</span></button></li>)}</ol> : <p className="empty">此实体尚未配置来源</p>}</section></> : <div className="inspector-empty"><p className="eyebrow">ENTITY INSPECTOR</p><h2>选择一个实体</h2><p>查看它的属性、指标、规则、关系和物理来源。</p></div>}</aside>;
}

function DefinitionList({ title, items }: { title: string; items: { label: string; id: string; meta?: string }[] }) {
  return <section className="definition-section"><div className="section-heading"><h3>{title}</h3><span>{items.length}</span></div>{items.length ? <ul className="definition-list">{items.map((item) => <li key={item.id}><span><strong>{item.label}</strong><code>{item.id}</code></span>{item.meta ? <small>{item.meta}</small> : null}</li>)}</ul> : <p className="empty">暂无定义</p>}</section>;
}

function TableFrame({ count, label, children }: { count: number; label: string; children: React.ReactNode }) {
  return <div className="table-frame"><div className="table-meta"><span>{count} 个{label}</span><span>当前发布 · 只读视图</span></div><div className="table-scroll">{children}</div></div>;
}

function ProviderMark({ provider, large = false }: { provider: string; large?: boolean }) {
  return <span className={large ? "provider-mark large" : "provider-mark"}>{provider === "postgres" ? "PG" : "API"}</span>;
}

function EmptySearch({ onClear }: { onClear: () => void }) {
  return <div className="empty-search"><h2>没有匹配项</h2><p>尝试名称、Semantic ID、来源 ID 或物理资源。</p><button className="secondary" onClick={onClear}>清除搜索</button></div>;
}

async function checkedJson(response: Response) {
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

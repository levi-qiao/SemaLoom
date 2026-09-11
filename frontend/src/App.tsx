import { useEffect, useMemo, useState } from "react";

type Node = { id: string; label: string; properties: string[] };
type Edge = { id: string; source: string; target: string; cardinality: string };
type Inspector = {
  id: string;
  label: string;
  identityKeys: string[];
  properties: { id: string; valueType: string; required: boolean }[];
  metrics: string[];
  mappings: string[];
  rules: string[];
};
type Mapping = { id: string; target: string; sourceId: string; provider: string };
type View = "graph" | "list" | "mappings";

const TOKEN = "tenant-a-modeler";
const headers = { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" };

export default function App() {
  const [view, setView] = useState<View>("graph");
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [inspector, setInspector] = useState<Inspector | null>(null);
  const [mappings, setMappings] = useState<Mapping[]>([]);
  const [revision, setRevision] = useState(0);
  const [status, setStatus] = useState("未保存");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/v0.1/studio/graph", { headers })
      .then(checkedJson)
      .then((payload) => {
        setNodes(payload.nodes);
        setEdges(payload.edges);
        if (payload.nodes[0]) setSelected(payload.nodes[0].id);
      })
      .catch((cause: Error) => setError(cause.message));
    fetch("/v0.1/studio/mappings", { headers })
      .then(checkedJson)
      .then((payload) => setMappings(payload.mappings ?? []))
      .catch((cause: Error) => setError(cause.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    fetch(`/v0.1/studio/inspector?objectId=${encodeURIComponent(selected)}`, { headers })
      .then(checkedJson)
      .then(setInspector)
      .catch((cause: Error) => setError(cause.message));
  }, [selected]);

  const positions = useMemo(
    () =>
      Object.fromEntries(
        nodes.map((node, index) => [
          node.id,
          { x: 48 + (index % 3) * 274, y: 48 + Math.floor(index / 3) * 148 },
        ]),
      ),
    [nodes],
  );

  async function saveDraft() {
    setStatus("保存中");
    const response = await fetch("/v0.1/studio/drafts/default", {
      method: "PUT",
      headers,
      body: JSON.stringify({ expectedRevision: revision, payload: { selected, view } }),
    });
    if (response.status === 409) {
      setStatus("修订冲突");
      return;
    }
    const payload = await checkedJson(response);
    setRevision(payload.revision);
    setStatus(`已保存 · r${payload.revision}`);
  }

  return (
    <div className="shell">
      <nav aria-label="工作台导航">
        <div className="brand">
          <span className="brand-mark">SL</span>
          <div>
            <strong>SemaLoom</strong>
            <small>Semantic Studio</small>
          </div>
        </div>
        <p className="nav-label">模型空间</p>
        <NavButton label="实体模型" active={view === "graph"} onClick={() => setView("graph")} />
        <NavButton label="实体列表" active={view === "list"} onClick={() => setView("list")} />
        <NavButton
          label="来源映射"
          active={view === "mappings"}
          onClick={() => setView("mappings")}
        />
        <div className="nav-spacer" />
        <div className="environment">
          <span className="status-dot" />
          <span>本地合成环境</span>
        </div>
      </nav>
      <main>
        <header>
          <div>
            <small>采购与税务示例</small>
            <strong>企业语义模型</strong>
          </div>
          <div className="header-actions">
            <span className="save-status">{status}</span>
            <button className="primary" onClick={() => void saveDraft()}>
              保存草稿
            </button>
          </div>
        </header>
        {error ? <p className="error">加载失败：{error}</p> : null}
        <section className="workspace">
          <div className="canvas">
            {view === "graph" ? (
              <svg width="100%" height="100%" role="img" aria-label="实体关系图">
                <defs>
                  <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" />
                  </marker>
                </defs>
                {edges.map((edge) => {
                  const from = positions[edge.source];
                  const to = positions[edge.target];
                  if (!from || !to) return null;
                  return (
                    <g key={edge.id}>
                      <line x1={from.x + 220} y1={from.y + 44} x2={to.x} y2={to.y + 44} />
                      <text x={(from.x + to.x) / 2 + 110} y={(from.y + to.y) / 2 + 34} className="edge-label">
                        {edge.cardinality}
                      </text>
                    </g>
                  );
                })}
                {nodes.map((node) => {
                  const pos = positions[node.id];
                  return (
                    <g
                      key={node.id}
                      role="button"
                      tabIndex={0}
                      aria-label={`选择实体 ${node.label}`}
                      onClick={() => setSelected(node.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") setSelected(node.id);
                      }}
                    >
                      <rect x={pos.x} y={pos.y} width="220" height="88" rx="6" className={selected === node.id ? "node selected" : "node"} />
                      <text x={pos.x + 14} y={pos.y + 28} className="node-title">{node.label}</text>
                      <text x={pos.x + 14} y={pos.y + 50} className="muted">{node.id}</text>
                      <text x={pos.x + 14} y={pos.y + 72} className="count">{node.properties.length} 个属性</text>
                    </g>
                  );
                })}
              </svg>
            ) : null}
            {view === "list" ? (
              <div className="table-view">
                <table>
                  <thead><tr><th>实体</th><th>Semantic ID</th><th>属性</th></tr></thead>
                  <tbody>
                    {nodes.map((node) => (
                      <tr key={node.id} onClick={() => setSelected(node.id)}>
                        <td><button className="text-button">{node.label}</button></td>
                        <td><code>{node.id}</code></td>
                        <td>{node.properties.length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {view === "mappings" ? (
              <div className="table-view">
                <table>
                  <thead><tr><th>Mapping</th><th>业务目标</th><th>来源</th><th>协议</th></tr></thead>
                  <tbody>
                    {mappings.map((item) => (
                      <tr key={item.id}>
                        <td><code>{item.id}</code></td><td>{item.target}</td><td>{item.sourceId}</td>
                        <td><span className="tag">{item.provider}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
          <aside>
            <p className="aside-label">实体检查器</p>
            {inspector ? (
              <>
                <h2>{inspector.label}</h2>
                <code className="semantic-id">{inspector.id}</code>
                <div className="meta-row"><span>业务键</span><strong>{inspector.identityKeys.join(", ")}</strong></div>
                <DefinitionList title="属性" items={inspector.properties.map((item) => ({ label: item.id, meta: item.valueType }))} />
                <DefinitionList title="指标" items={inspector.metrics.map((label) => ({ label }))} />
                <DefinitionList title="规则" items={inspector.rules.map((label) => ({ label }))} />
                <DefinitionList title="来源映射" items={inspector.mappings.map((label) => ({ label }))} />
              </>
            ) : <p className="empty">选择一个实体查看定义和来源。</p>}
          </aside>
        </section>
      </main>
    </div>
  );
}

function NavButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return <button aria-pressed={active} className={active ? "active" : ""} onClick={onClick}>{label}</button>;
}

function DefinitionList({ title, items }: { title: string; items: { label: string; meta?: string }[] }) {
  return (
    <section className="definition-section">
      <div className="section-heading"><h3>{title}</h3><span>{items.length}</span></div>
      {items.length ? <ul className="definition-list">{items.map((item) => <li key={item.label}><span>{item.label}</span>{item.meta ? <small>{item.meta}</small> : null}</li>)}</ul> : <p className="empty">暂无定义</p>}
    </section>
  );
}

async function checkedJson(response: Response) {
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

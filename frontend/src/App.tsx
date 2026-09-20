import { useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  apiHeaders,
  checkedJson,
  ensureSession,
  errorDetail,
  hasRole,
  type StudioSession,
} from "./api";
import { ChatPage } from "./ChatPage";
import { defaultLinkIdentity, linkIdentitySummary } from "./doc";
import { EntityPage } from "./EntityPage";
import { ApiPage } from "./ApiPage";
import { GraphCanvas } from "./GraphCanvas";
import { draftSaveLabel, gateErrorMessage } from "./labels";
import { SourcePage } from "./SourcePage";
import { StudioDialog } from "./StudioDialog";
import { IconApi, IconChat, IconEntity, IconGraph, IconSource } from "./icons";
import type { DraftDocument, Edge, GraphMeta, Mapping, Node, Source, View } from "./types";

type DialogState =
  | { mode: "entity"; id: string }
  | { mode: "link"; id: string }
  | { mode: "create" }
  | null;

const viewNames: Record<View, { title: string; description: string }> = {
  chat: { title: "业务问答", description: "用业务语言提问，查看规则结果与来源依据。" },
  graph: { title: "图谱", description: "看关系和试读映射。点实体做主要维护，细节到「实体」菜单。" },
  objects: { title: "实体", description: "维护业务对象、属性和来源字段对应。金额是带单位的属性；问答里再选合计或平均。" },
  sources: { title: "数据源", description: "配置物理数据库连接，表结构自动读取。" },
  apis: { title: "API 接口", description: "维护微服务与外部 API 契约，支持线上导入 OpenAPI / Swagger 与鉴权配置。" },
};

function readLocation(): { view: View; entity: string | null } {
  const params = new URLSearchParams(window.location.search);
  const value = params.get("view");
  const view: View =
    value === "chat" || value === "sources" || value === "objects" || value === "apis" ? value : "graph";
  return { view, entity: params.get("entity") };
}

function writeLocation(view: View, entity: string | null, history: "push" | "replace") {
  const params = new URLSearchParams();
  params.set("view", view);
  if (entity) params.set("entity", entity);
  const url = `${window.location.pathname}?${params.toString()}`;
  if (`${window.location.pathname}${window.location.search}` === url) return;
  if (history === "push") window.history.pushState({ view, entity }, "", url);
  else window.history.replaceState({ view, entity }, "", url);
}

export default function App() {
  const initial = useMemo(() => readLocation(), []);
  const [view, setView] = useState<View>(initial.view);
  const [meta, setMeta] = useState<GraphMeta | null>(null);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selected, setSelected] = useState<string | null>(initial.entity);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogState>(
    initial.entity ? { mode: "entity", id: initial.entity } : null,
  );
  const [mappings, setMappings] = useState<Mapping[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [documents, setDocuments] = useState<DraftDocument[]>([]);
  const [savedDocuments, setSavedDocuments] = useState<DraftDocument[]>([]);
  const [revision, setRevision] = useState(0);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [sourceDirty, setSourceDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [namespaceFilter, setNamespaceFilter] = useState("");
  const [relationFilter, setRelationFilter] = useState("");
  const [session, setSession] = useState<StudioSession | null>(null);
  const editGen = useRef(0);
  const viewRef = useRef(view);
  const canModel = hasRole(session, "modeler");

  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  function selectEntity(id: string, history: "push" | "replace" = "push") {
    setSelected(id);
    setSelectedEdge(null);
    setDialog({ mode: "entity", id });
    writeLocation(viewRef.current, id, history);
  }

  function selectView(next: View) {
    setSearch("");
    setView(next);
    if (next === "graph" && selected) setDialog({ mode: "entity", id: selected });
    writeLocation(next, selected, "push");
  }

  async function loadInitialState(force = false) {
    if ((dirty || sourceDirty) && !force) {
      setError("有未保存修改，重新载入会丢弃它们。请先保存，或选择放弃本地修改并载入。");
      return;
    }
    try {
      const nextSession = await ensureSession();
      setSession(nextSession);
      const modeler = hasRole(nextSession, "modeler");
      const modelQuery = modeler ? "?draftId=default" : "";
      const [graph, mappingPayload, sourcePayload, model] = await Promise.all([
        fetch(`/v0.1/studio/graph${modelQuery}`).then(checkedJson),
        fetch(`/v0.1/studio/mappings${modelQuery}`).then(checkedJson),
        fetch(`/v0.1/studio/sources${modelQuery}`).then(checkedJson),
        modeler ? fetch("/v0.1/studio/drafts/default").then(checkedJson) : Promise.resolve(null),
      ]);
      const nextDocuments = (model?.documents ?? []) as DraftDocument[];
      const urlEntity = readLocation().entity;
      const nextSelected =
        selected &&
        (graph.nodes.some((item: Node) => item.id === selected) ||
          nextDocuments.some((item) => item.id === selected))
          ? selected
          : urlEntity &&
              (graph.nodes.some((item: Node) => item.id === urlEntity) ||
                nextDocuments.some((item) => item.id === urlEntity))
            ? urlEntity
            : (graph.nodes[0]?.id ?? null);
      setMeta(graph.meta);
      setNodes(graph.nodes);
      setEdges(graph.edges);
      setMappings(mappingPayload.mappings ?? []);
      setSources(sourcePayload.sources ?? []);
      setDocuments(nextDocuments);
      setSavedDocuments(nextDocuments);
      setRevision(model?.revision ?? 0);
      setSelected(nextSelected);
      setDialog((current) => {
        if (current?.mode === "link") return current;
        if (current?.mode === "entity" && current.id === nextSelected) return current;
        return nextSelected ? { mode: "entity", id: nextSelected } : current;
      });
      setSourceId((current) => current ?? sourcePayload.sources?.[0]?.sourceId ?? null);
      setDirty(false);
      setSourceDirty(false);
      setConflict(false);
      setStatus("");
      setError(null);
      writeLocation(viewRef.current, nextSelected, "replace");
    } catch (cause) {
      setError(gateErrorMessage(errorDetail(cause), cause instanceof ApiError ? cause.status : undefined));
      setStatus("");
    }
  }

  useEffect(() => {
    void loadInitialState();
  }, []);

  useEffect(() => {
    function onPop() {
      const next = readLocation();
      setView(next.view);
      setSelected(next.entity);
      setDialog(next.entity ? { mode: "entity", id: next.entity } : null);
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent) {
      if (!dirty && !sourceDirty) return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty, sourceDirty]);

  async function save(expectedRevision = revision) {
    const gen = editGen.current;
    const toSave = documents;
    setSaving(true);
    setError(null);
    try {
      const payload = await fetch("/v0.1/studio/drafts/default", {
        method: "PUT",
        headers: apiHeaders(),
        body: JSON.stringify({ expectedRevision, documents: toSave }),
      }).then(checkedJson);
      setRevision(payload.revision);
      setSavedDocuments(payload.documents ?? toSave);
      if (editGen.current !== gen) {
        setConflict(false);
        setStatus("较早版本已保存，当前修改仍未保存");
      } else {
        setDocuments(payload.documents ?? toSave);
        setDirty(false);
        setConflict(false);
        setStatus("已保存");
      }
      const graph = await fetch("/v0.1/studio/graph?draftId=default").then(checkedJson);
      setMeta(graph.meta);
      setNodes(graph.nodes);
      setEdges(graph.edges);
      const mappingPayload = await fetch("/v0.1/studio/mappings?draftId=default").then(checkedJson);
      setMappings(mappingPayload.mappings ?? []);
    } catch (cause) {
      const message = errorDetail(cause);
      const statusCode = cause instanceof ApiError ? cause.status : undefined;
      if (message.includes("409") || message.includes("REVISION_CONFLICT") || statusCode === 409) {
        setConflict(true);
        setStatus("保存冲突");
        setError(gateErrorMessage("REVISION_CONFLICT", 409));
      } else {
        setError(gateErrorMessage(message, statusCode));
      }
    } finally {
      setSaving(false);
    }
  }

  async function retrySave() {
    try {
      const model = await fetch("/v0.1/studio/drafts/default").then(checkedJson);
      await save(model.revision ?? revision);
    } catch (cause) {
      setError(gateErrorMessage(errorDetail(cause), cause instanceof ApiError ? cause.status : undefined));
    }
  }

  function changeDocuments(next: DraftDocument[]) {
    if (!canModel) return;
    editGen.current += 1;
    setDocuments(next);
    setDirty(true);
    setStatus("有未保存修改");
  }

  const query = search.trim().toLowerCase();
  const liveNodes = useMemo(() => {
    const mapped = nodes.map((node) => {
      const doc = documents.find((item) => item.id === node.id && item.kind === "ObjectType");
      return doc?.label ? { ...node, label: String(doc.label) } : node;
    });
    const extras = documents
      .filter((item) => item.kind === "ObjectType" && !nodes.some((node) => node.id === item.id))
      .map((item) => ({
        id: item.id,
        label: String(item.label || item.id),
        namespace: item.id.split(".")[0] ?? "",
        properties: [] as string[],
        metricCount: 0,
        ruleCount: 0,
        actionCount: 0,
        mappingCount: 0,
        sourceCount: 0,
      }));
    return [...mapped, ...extras];
  }, [nodes, documents]);
  const liveEdges = useMemo(
    () =>
      documents
        .filter((item) => item.kind === "Link")
        .map((item) => {
          const summary = linkIdentitySummary(item.identity);
          return {
            id: item.id,
            label: String(item.label || "关联"),
            source: String(item.source ?? ""),
            target: String(item.target ?? ""),
            cardinality: String(item.cardinality || "ONE"),
            sourceKey: summary.sourceKey,
            targetKey: summary.targetKey,
          };
        }),
    [documents],
  );
  const namespaces = [...new Set(liveNodes.map((node) => node.namespace))].sort();
  const relationOptions = liveEdges.map((edge) => ({ id: edge.id, label: edge.label }));
  const scopedNodes = liveNodes.filter((node) => {
    if (namespaceFilter && node.namespace !== namespaceFilter) return false;
    return `${node.label} ${node.id} ${node.namespace}`.toLowerCase().includes(query);
  });
  const scopedIds = new Set(scopedNodes.map((node) => node.id));
  const scopedEdges = liveEdges.filter((edge) => {
    if (!scopedIds.has(edge.source) || !scopedIds.has(edge.target)) return false;
    return !relationFilter || edge.id === relationFilter;
  });
  const unsaved = dirty || sourceDirty;

  return (
    <div className="shell">
      <nav aria-label="工作台导航">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">SL</span>
          <div><strong>SemaLoom</strong><small>Semantic Studio</small></div>
        </div>
        <div className="nav-group">
          <NavButton icon={<IconGraph size={18} />} label="图谱" active={view === "graph"} onClick={() => selectView("graph")} />
          <NavButton icon={<IconEntity size={18} />} label="实体" active={view === "objects"} onClick={() => selectView("objects")} />
          <NavButton icon={<IconSource size={18} />} label="数据源" active={view === "sources"} onClick={() => selectView("sources")} />
          <NavButton icon={<IconApi size={18} />} label="API 接口" active={view === "apis"} onClick={() => selectView("apis")} />
          <NavButton icon={<IconChat size={18} />} label="问答" active={view === "chat"} onClick={() => selectView("chat")} />
        </div>
        <div className="nav-spacer" />
        <div className="environment">
          <span className="status-dot" aria-hidden="true" />
          <span><strong>本地开发环境</strong><small>业务样本请查看数据源</small></span>
        </div>
      </nav>
      <main>
        <header>
          <div className="context-title">
            <h1>{viewNames[view].title}</h1>
            <small>{viewNames[view].description}</small>
          </div>
          <div className="header-actions">
            {view === "chat" ? null : (
              <label className="search-field">
                <span className="sr-only">搜索当前视图</span>
                <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称或 ID" />
              </label>
            )}
            {status || (sourceDirty && view === "sources") ? (
              <span className={conflict ? "save-status conflict" : "save-status"}>
                {status}{sourceDirty && view === "sources" ? (status ? " · 来源未保存" : "来源未保存") : ""}
              </span>
            ) : null}
            {conflict ? (
              <span className="conflict-actions">
                <button className="secondary" onClick={() => void retrySave()}>用当前修改重试保存</button>
                <button className="secondary" onClick={() => void loadInitialState(true)}>放弃本地修改并载入</button>
              </span>
            ) : null}
            {view === "sources" || view === "chat" || view === "apis" || !canModel ? null : (
              <button className="primary" disabled={saving || !dirty} onClick={() => void save()}>{draftSaveLabel()}</button>
            )}
          </div>
        </header>
        {error ? (
          <div className="error" role="alert">
            <span>操作未完成：{error}</span>
            {unsaved ? (
              <button onClick={() => setError(null)}>关闭</button>
            ) : (
              <button onClick={() => void loadInitialState()}>重新载入</button>
            )}
          </div>
        ) : null}
        {view === "chat" && session ? <ChatPage key={`${session.tenant}:${session.subject}`} session={session} /> : null}
        <section className={view === "objects" ? "workspace entity-workspace" : "workspace"} hidden={view === "sources" || view === "chat" || view === "apis"}>
          {view === "graph" ? (
            <div className="content-pane graph-host">
              <GraphCanvas
                nodes={scopedNodes}
                edges={scopedEdges}
                selected={selected}
                selectedEdge={selectedEdge}
                onSelect={(id) => selectEntity(id)}
                onSelectEdge={(id) => {
                  setSelectedEdge(id);
                  setDialog({ mode: "link", id });
                }}
                onCreate={() => setDialog({mode: "create"})}
                canEdit={Boolean(session?.roles.includes("modeler"))}
                onOpenFull={(id) => {
                  selectEntity(id, "replace");
                  selectView("objects");
                }}
                onLink={(source, target) => {
                  const exists = documents.find((item) => item.kind === "Link" && item.source === source && item.target === target);
                  if (exists) {
                    setDialog({ mode: "link", id: exists.id });
                    setSelectedEdge(exists.id);
                    return;
                  }
                  const sourceDoc = documents.find((item) => item.id === source);
                  const targetDoc = documents.find((item) => item.id === target);
                  const ns = source.includes(".") ? source.split(".")[0] : source;
                  const id = `${ns}.${source.split(".").at(-1)}To${target.split(".").at(-1)}`;
                  changeDocuments([
                    ...documents,
                    {
                      apiVersion: "semaloom/v0.1",
                      kind: "Link",
                      id,
                      version: "1.0.0",
                      label: "关联",
                      source,
                      target,
                      cardinality: "ONE",
                      traversal: "FORWARD",
                      identity: defaultLinkIdentity(sourceDoc, targetDoc),
                    },
                  ]);
                  setSelectedEdge(id);
                  setDialog({ mode: "link", id });
                }}
                namespaces={namespaces}
                packs={meta?.packs ?? []}
                relations={relationOptions}
                namespaceFilter={namespaceFilter}
                relationFilter={relationFilter}
                onNamespaceFilter={setNamespaceFilter}
                onRelationFilter={setRelationFilter}
              />
            </div>
          ) : null}
          {view === "objects" ? (
            <EntityPage
              documents={documents}
              savedDocuments={savedDocuments}
              savedRevision={revision}
              search={search}
              selectedId={selected}
              onSelect={(id) => selectEntity(id)}
              onChange={changeDocuments}
              onError={(message) => setError(message ? gateErrorMessage(message) : null)}
              packs={meta?.packs ?? []}
            />
          ) : null}
          {view === "graph" ? (
            <StudioDialog
              mode={dialog?.mode ?? "entity"}
              variant="quick"
              targetId={dialog?.mode === "create" || !dialog ? null : dialog.id}
              documents={documents}
              savedDocuments={savedDocuments}
              savedRevision={revision}
              onChange={changeDocuments}
              onClose={() => setDialog(selected ? { mode: "entity", id: selected } : null)}
              onCreated={(id) => { selectEntity(id); }}
              onOpenEntity={(id) => {
                selectEntity(id, "replace");
                selectView("objects");
              }}
              onError={(message) => setError(message ? gateErrorMessage(message) : null)}
              packs={meta?.packs ?? []}
            />
          ) : null}
        </section>
        <section className="workspace" hidden={view !== "sources"}>
          <SourcePage
            ready={meta !== null}
            catalog={sources}
            mappings={mappings}
            search={search}
            selectedId={sourceId}
            onSelect={setSourceId}
            onError={(message) => setError(message ? gateErrorMessage(message) : null)}
            onDirtyChange={setSourceDirty}
            onSaved={() => undefined}
          />
        </section>
        <section className="workspace full" hidden={view !== "apis"}>
          <ApiPage
            ready={meta !== null}
            documents={documents}
            search={search}
            selectedId={sourceId}
            onSelect={setSourceId}
            onError={(message) => setError(message ? gateErrorMessage(message) : null)}
            onChangeDocuments={changeDocuments}
            onDirtyChange={setSourceDirty}
          />
        </section>
      </main>
    </div>
  );
}

function NavButton({ label, icon, active, onClick }: { label: string; icon?: React.ReactNode; active: boolean; onClick: () => void }) {
  return (
    <button aria-pressed={active} className={active ? "active" : ""} onClick={onClick}>
      <span className="nav-btn-icon" aria-hidden="true">{icon}</span>
      <span className="nav-btn-label">{label}</span>
    </button>
  );
}

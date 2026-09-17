import { useEffect, useState } from "react";

import { apiHeaders, checkedJson } from "./api";
import {
  LOCAL_ID,
  array,
  attachMapping,
  defaultLinkIdentity,
  documentById,
  linkIdentityPairs,
  makeObjectType,
  ownedByEntity,
  referencesEntity,
  replaceDocument,
  text,
} from "./doc";
import { LinkFields } from "./DraftEditor";
import { namespaceLabel, publishedExecutionHint } from "./labels";
import { MappingEditor, makeMappingDocument } from "./MappingEditor";
import { PropertyMappingSheet } from "./PropertyMappingSheet";
import {
  AboutSidePanel,
  ActionsSidePanel,
  RelationsSidePanel,
  RulesSidePanel,
  SheetHelp,
} from "./EntitySidePanels";
import type { DraftDocument, SourceProfileSummary } from "./types";

type Tab = "about" | "properties" | "relations" | "rules" | "actions";

type Props = {
  mode: "entity" | "link" | "create";
  variant?: "quick" | "full";
  targetId: string | null;
  documents: DraftDocument[];
  savedDocuments: DraftDocument[];
  savedRevision: number;
  onChange: (documents: DraftDocument[]) => void;
  onClose: () => void;
  onCreated: (id: string) => void;
  onOpenEntity?: (id: string) => void;
  onSave?: () => void;
  onError: (message: string | null) => void;
};

export function StudioDialog({
  mode,
  variant = "quick",
  targetId,
  documents,
  savedDocuments,
  savedRevision,
  onChange,
  onClose,
  onCreated,
  onOpenEntity,
  onSave,
  onError,
}: Props) {
  if (mode === "create") {
    return <CreateEntityDialog documents={documents} onChange={onChange} onClose={onClose} onCreated={onCreated} onError={onError} />;
  }
  if (mode === "link") {
    const document = documents.find((item) => item.id === targetId && item.kind === "Link");
    if (!document) return null;
    return (
      <Panel title="关系" onSave={onSave}>
        <LinkEditor document={document} documents={documents} onChange={(next) => onChange(replaceDocument(documents, next))} />
      </Panel>
    );
  }
  const document = documents.find((item) => item.id === targetId && item.kind === "ObjectType");
  if (!document) {
    return (
      <Panel title="配置">
        <div className="inspector-empty">
          <h2>从实体开始</h2>
          <p>点实体可改名称、描述并试读映射。完整属性、多表映射、判断和操作请到「实体」菜单。</p>
        </div>
      </Panel>
    );
  }
  return (
    <Panel title={String(document.label || document.id)} onSave={onSave}>
      <EntityEditor
        document={document}
        documents={documents}
        savedDocuments={savedDocuments}
        savedRevision={savedRevision}
        variant={variant}
        onChange={onChange}
        onError={onError}
        onOpenEntity={onOpenEntity}
      />
    </Panel>
  );
}

export function Panel({
  title,
  onClose,
  onSave,
  children,
}: {
  title: string;
  onClose?: () => void;
  onSave?: () => void;
  children: React.ReactNode;
}) {
  return (
    <aside className="inspector studio-panel" aria-label={title}>
      <div className="dialog-head">
        <h2>{title}</h2>
        {onClose ? <button className="text-button" onClick={onClose} aria-label="关闭">关闭</button> : null}
      </div>
      <div className="studio-panel-body">{children}</div>
      {onSave ? <div className="dialog-foot"><button className="primary" onClick={onSave}>保存</button></div> : null}
    </aside>
  );
}

export function Window(props: {
  title: string;
  onClose: () => void;
  onSave?: () => void;
  children: React.ReactNode;
}) {
  return <Panel {...props} />;
}

function CreateEntityDialog({
  documents,
  onChange,
  onClose,
  onCreated,
  onError,
}: {
  documents: DraftDocument[];
  onChange: (documents: DraftDocument[]) => void;
  onClose: () => void;
  onCreated: (id: string) => void;
  onError: (message: string | null) => void;
}) {
  const namespaces = [...new Set(documents.filter((item) => item.kind === "ObjectType").map((item) => item.id.split(".")[0] ?? ""))].filter(Boolean);
  const [namespace, setNamespace] = useState(namespaces[0] ?? "procurement");
  const [localId, setLocalId] = useState("");
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  function create() {
    const local = localId.trim();
    const display = label.trim();
    if (!display) {
      setFormError("请填写显示名称");
      return;
    }
    if (!LOCAL_ID.test(local)) {
      setFormError("请填写英文语义 ID，字母开头，仅含字母数字和下划线");
      return;
    }
    const document = makeObjectType(namespace, local, display);
    if (description.trim()) document.description = description.trim();
    if (documents.some((item) => item.id === document.id)) {
      setFormError("该语义 ID 已存在");
      return;
    }
    onChange([...documents, document]);
    onCreated(document.id);
    onError(null);
    setFormError(null);
  }

  return (
    <Panel title="新建实体" onClose={onClose}>
      <div className="form-grid">
        <label className="form-field"><span>领域</span>
          <select aria-label="领域" value={namespace} onChange={(event) => setNamespace(event.target.value)}>
            {namespaces.map((item) => <option key={item} value={item}>{namespaceLabel(item)}</option>)}
          </select>
        </label>
        <label className="form-field"><span>显示名称</span>
          <input aria-label="显示名称" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="例如 仓库" />
        </label>
      </div>
      <label className="form-field"><span>语义 ID</span>
        <input aria-label="语义 ID" value={localId} onChange={(event) => setLocalId(event.target.value)} placeholder="英文 ID，例如 Warehouse" />
      </label>
      <label className="form-field"><span>描述（给 AI 和同事看）</span>
        <textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="这个实体在业务里代表什么" />
      </label>
      {formError ? <p className="field-error" role="alert">{formError}</p> : null}
      <button className="primary" onClick={create}>创建</button>
    </Panel>
  );
}

export function EntityEditor({
  document,
  documents,
  savedDocuments,
  savedRevision,
  variant = "full",
  onChange,
  onError,
  onOpenEntity,
}: {
  document: DraftDocument;
  documents: DraftDocument[];
  savedDocuments: DraftDocument[];
  savedRevision: number;
  variant?: "quick" | "full";
  onChange: (documents: DraftDocument[]) => void;
  onError: (message: string | null) => void;
  onOpenEntity?: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("about");
  const quick = variant === "quick";
  const properties = array(document.properties) as Record<string, unknown>[];
  const identityKeys = array(document.identityKeys).map(String);
  const mappings = documents.filter((item) => item.kind === "Mapping" && item.target === document.id);
  const metricIds = new Set(
    documents.filter((item) => item.kind === "Metric" && item.objectType === document.id).map((item) => item.id),
  );
  const rules = documents.filter((item) => item.kind === "Rule" && array(item.inputs).some((input) => {
    const row = input as Record<string, unknown>;
    return row.objectType === document.id || (typeof row.metric === "string" && metricIds.has(row.metric));
  }));
  const actions = documents.filter((item) => item.kind === "Action" && item.targetObject === document.id);
  const links = documents.filter((item) => item.kind === "Link" && (item.source === document.id || item.target === document.id));

  function replace(next: DraftDocument) {
    onChange(replaceDocument(documents, next));
  }

  function addLink() {
    const target = documents.find((item) => item.kind === "ObjectType" && item.id !== document.id);
    if (!target) {
      onError("请先创建另一个实体");
      return;
    }
    const ns = document.id.split(".")[0] ?? "procurement";
    const local = `${String(document.id.split(".").at(-1))}To${String(target.id.split(".").at(-1))}`;
    let id = `${ns}.${local}`;
    let n = 2;
    while (documents.some((item) => item.id === id)) {
      id = `${ns}.${local}${n}`;
      n += 1;
    }
    onChange([
      ...documents,
      {
        apiVersion: "semaloom/v0.1",
        kind: "Link",
        id,
        version: "1.0.0",
        label: "关联",
        source: document.id,
        target: target.id,
        cardinality: "ONE",
        traversal: "FORWARD",
        identity: defaultLinkIdentity(document, target),
      },
    ]);
    onError(null);
  }

  return (
    <>
      <div className="chip-row">
        <Chip label="概况" active={tab === "about"} onClick={() => setTab("about")} />
        <Chip label={quick ? `来源 ${mappings.length}` : `属性与来源 ${properties.length}`} active={tab === "properties"} onClick={() => setTab("properties")} />
        {quick ? null : <Chip label={`关系 ${links.length}`} active={tab === "relations"} onClick={() => setTab("relations")} />}
        <Chip label={`判断 ${rules.length}`} active={tab === "rules"} onClick={() => setTab("rules")} />
        {quick ? null : <Chip label={`操作 ${actions.length}`} active={tab === "actions"} onClick={() => setTab("actions")} />}
      </div>
      {quick && onOpenEntity ? (
        <button className="secondary" onClick={() => onOpenEntity(document.id)}>在实体中完整编辑</button>
      ) : null}
      {tab === "about" ? (
        <div className="entity-sheet">
          <div className="entity-sheet-main">
            <div className="form-grid">
              <label className="form-field"><span>显示名称</span>
                <input aria-label="显示名称" value={text(document.label)} onChange={(event) => replace({ ...document, label: event.target.value })} />
              </label>
              <label className="form-field"><span>语义 ID</span>
                <input value={document.id} readOnly disabled className="is-readonly" />
              </label>
            </div>
            <label className="form-field"><span>描述（给 AI 和同事看）</span>
              <textarea rows={4} aria-label="实体描述" value={text(document.description)} onChange={(event) => replace({ ...document, description: event.target.value || undefined })} placeholder="这个实体是什么、何时使用、和哪些系统有关" />
            </label>
            <p className="mapping-hint">语义 ID：{document.id}（稳定英文标识，不能靠改显示名称替换）</p>
          </div>
          {quick ? null : (
            <div className="entity-sheet-side">
              <AboutSidePanel
                document={document}
                documents={documents}
                onOpenEntity={onOpenEntity}
              />
            </div>
          )}
        </div>
      ) : null}
      {tab === "properties" && quick ? (
        <MappingList
          objectType={document}
          mappings={mappings}
          documents={documents}
          savedDocuments={savedDocuments}
          savedRevision={savedRevision}
          compact
          onChange={onChange}
          onError={onError}
        />
      ) : null}
      {tab === "properties" && !quick ? (
        <PropertyMappingSheet
          objectType={document}
          documents={documents}
          savedDocuments={savedDocuments}
          savedRevision={savedRevision}
          onChange={onChange}
          onError={onError}
        />
      ) : null}
      {tab === "relations" && !quick ? (
        <div className="entity-sheet">
          <div className="entity-sheet-main">
            <p className="mapping-hint">ONE 表示源到目标至多一个，例如每个订单对应一个供应商；不能据此标成 1:1。</p>
            <button className="secondary sheet-action" onClick={addLink}>添加关系</button>
            {links.length ? links.map((link) => (
              <article className="bind-card" key={link.id}>
                <LinkEditor document={link} documents={documents} onChange={(next) => onChange(replaceDocument(documents, next))} />
              </article>
            )) : <p className="empty">还没有关系。可用表单添加，不必只靠图谱拖拽。</p>}
          </div>
          <div className="entity-sheet-side">
            <RelationsSidePanel
              document={document}
              documents={documents}
              links={links}
              onOpenEntity={onOpenEntity}
            />
          </div>
        </div>
      ) : null}
      {tab === "rules" ? (
        <div className="entity-sheet">
          <div className="entity-sheet-main">
            <p className="mapping-hint">判断用来根据已有数据得出一件事是否成立。结果只有三种：成立、不成立、数据不够无法判断。{publishedExecutionHint()}</p>
            {rules.length ? rules.map((rule) => (
              <article className="bind-card" key={rule.id}>
                <strong>{text(rule.label) || rule.id}</strong>
                <small>{text(rule.description) || "尚未填写说明"}</small>
                {quick ? null : (
                  <label className="form-field"><span>描述</span>
                    <textarea rows={2} value={text(rule.description)} onChange={(event) => onChange(replaceDocument(documents, { ...rule, description: event.target.value || undefined }))} />
                  </label>
                )}
              </article>
            )) : <p className="empty">这个实体还没有判断。判断不是筛数据的过滤器，而是可重复评估的业务命题。</p>}
          </div>
          {quick ? null : (
            <div className="entity-sheet-side">
              <RulesSidePanel
                document={document}
                documents={documents}
                rules={rules}
              />
            </div>
          )}
        </div>
      ) : null}
      {tab === "actions" && !quick ? (
        <div className="entity-sheet">
          <div className="entity-sheet-main">
            <p className="mapping-hint">受控操作会调用外部系统写接口。所有写操作必须通过前置审批和执行对账。</p>
            {actions.length ? actions.map((action) => (
              <article className="bind-card" key={action.id}>
                <strong>{text(action.label) || action.id}</strong>
                <small>{text(action.effect)}</small>
                <label className="form-field"><span>描述</span>
                  <textarea rows={2} value={text(action.description)} onChange={(event) => onChange(replaceDocument(documents, { ...action, description: event.target.value || undefined }))} />
                </label>
              </article>
            )) : <p className="empty">这个实体还没有会改业务系统的操作。</p>}
          </div>
          <div className="entity-sheet-side">
            <ActionsSidePanel
              document={document}
              documents={documents}
              actions={actions}
              rules={rules}
            />
          </div>
        </div>
      ) : null}
    </>
  );
}

function MappingList({
  objectType,
  mappings,
  documents,
  savedDocuments,
  savedRevision,
  compact = false,
  onChange,
  onError,
}: {
  objectType: DraftDocument;
  mappings: DraftDocument[];
  documents: DraftDocument[];
  savedDocuments: DraftDocument[];
  savedRevision: number;
  compact?: boolean;
  onChange: (documents: DraftDocument[]) => void;
  onError: (message: string | null) => void;
}) {
  const [profiles, setProfiles] = useState<SourceProfileSummary[]>([]);
  useEffect(() => {
    void fetch("/v0.1/studio/source-profiles").then(checkedJson).then((payload) => setProfiles(payload.profiles ?? [])).catch(() => setProfiles([]));
  }, []);

  function addMapping() {
    const source = profiles[0];
    onChange(
      attachMapping(
        documents,
        makeMappingDocument(objectType, source?.sourceId ?? "orders_pg", source?.provider ?? "postgres", documents),
      ),
    );
  }

  return (
    <div>
      <p className="mapping-hint">把表或接口字段对到上面的属性。同一实体可以来自多张表。</p>
      {compact ? null : <button className="secondary" onClick={addMapping}>添加一张表 / 接口</button>}
      {mappings.map((mapping) => {
        const saved = savedDocuments.find((item) => item.id === mapping.id && item.kind === "Mapping");
        return (
          <MappingEditor
            key={mapping.id}
            mapping={mapping}
            objectType={objectType}
            documents={documents}
            profiles={profiles}
            compact={compact}
            saved={Boolean(saved) && JSON.stringify(saved) === JSON.stringify(mapping)}
            savedRevision={savedRevision}
            onChange={onChange}
            onError={onError}
          />
        );
      })}
      {mappings.length === 0 ? <p className="empty">还没有接到任何表或接口。点上面按钮添加。</p> : null}
    </div>
  );
}

export function LinkEditor({ document, documents, onChange }: { document: DraftDocument; documents: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
  const objects = documents.filter((item) => item.kind === "ObjectType");
  const sourceDoc = documentById(objects, text(document.source));
  const targetDoc = documentById(objects, text(document.target));
  const identity = Array.isArray(document.identity)
    ? document.identity
    : linkIdentityPairs(document.identity);
  const working: DraftDocument = {
    ...document,
    identity: identity.length ? identity : defaultLinkIdentity(sourceDoc, targetDoc),
  };
  return (
    <>
      <label className="form-field"><span>显示名称</span>
        <input aria-label="显示名称" value={text(document.label)} onChange={(event) => onChange({ ...working, label: event.target.value })} />
      </label>
      <LinkFields document={working} objects={objects} onChange={onChange} />
      <label className="form-field"><span>描述（给 AI 和同事看）</span>
        <textarea rows={3} aria-label="关系描述" value={text(document.description)} onChange={(event) => onChange({ ...working, description: event.target.value || undefined })} placeholder="这条关系在业务上表示什么" />
      </label>
    </>
  );
}

export async function loadDeleteImpacts(entityId: string, documents: DraftDocument[]) {
  const payload = await fetch(`/v0.1/studio/drafts/default/impacts/${encodeURIComponent(entityId)}`, {
    headers: apiHeaders(),
  }).then(checkedJson);
  const remote = Array.isArray(payload.impacts) ? payload.impacts as { id: string; kind: string }[] : [];
  const local = documents
    .filter((item) => referencesEntity(item, entityId) && !ownedByEntity(item, entityId))
    .map((item) => ({ id: item.id, kind: item.kind }));
  const merged = [...remote, ...local].filter((item, index, list) => list.findIndex((entry) => entry.id === item.id) === index);
  return merged.filter((item) => {
    const doc = documents.find((entry) => entry.id === item.id);
    return !doc || !ownedByEntity(doc, entityId);
  });
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return <button className={active ? "chip active" : "chip"} onClick={onClick} aria-pressed={active}>{label}</button>;
}

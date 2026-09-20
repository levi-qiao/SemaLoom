import { useEffect, useState } from "react";

import { apiHeaders, checkedJson } from "./api";
import {
  LOCAL_ID,
  array,
  attachMapping,
  defaultLinkIdentity,
  documentById,
  linkIdentityPairs,
  makeActionForObject,
  makeObjectType,
  makeRuleForObject,
  ownedByEntity,
  referencesEntity,
  replaceDocument,
  text,
  uniqueDocumentId,
} from "./doc";
import { ActionFields, LinkFields, RuleFields } from "./DefinitionFields";
import { EntityDslEditor } from "./EntityDslEditor";
import { namespaceLabel, publishedExecutionHint, type PackLabel } from "./labels";
import { MappingEditor, makeMappingDocument } from "./MappingEditor";
import { PropertyMappingSheet } from "./PropertyMappingSheet";
import type { DraftDocument, SourceProfileSummary } from "./types";

type Tab = "about" | "properties" | "relations" | "rules" | "actions" | "dsl";

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
  packs?: PackLabel[];
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
  packs = [],
}: Props) {
  if (mode === "create") {
    return <CreateEntityDialog documents={documents} packs={packs} onChange={onChange} onClose={onClose} onCreated={onCreated} onError={onError} />;
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
    <Panel
      title={String(document.label || document.id)}
      subtitle={document.id}
      namespace={document.id.split(".")[0]}
      packs={packs}
      headerAction={
        variant === "quick" && onOpenEntity ? (
          <button className="secondary entity-open-full-btn" onClick={() => onOpenEntity(document.id)}>在实体中完整编辑</button>
        ) : null
      }
      onSave={onSave}
    >
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
  subtitle,
  namespace,
  packs = [],
  headerAction,
  onClose,
  onSave,
  children,
}: {
  title: string;
  subtitle?: string;
  namespace?: string;
  packs?: PackLabel[];
  headerAction?: React.ReactNode;
  onClose?: () => void;
  onSave?: () => void;
  children: React.ReactNode;
}) {
  return (
    <aside className="inspector studio-panel" aria-label={title}>
      <div className="dialog-head">
        <div className="dialog-head-info">
          <div className="dialog-head-title-row">
            <h2>{title}</h2>
            {namespace ? (
              <span className="dialog-head-ns">{namespaceLabel(namespace, packs)}</span>
            ) : null}
          </div>
          {subtitle && subtitle !== title ? (
            <code className="dialog-head-id">{subtitle}</code>
          ) : null}
        </div>
        <div className="dialog-head-actions">
          {headerAction}
          {onClose ? <button className="text-button" onClick={onClose} aria-label="关闭">关闭</button> : null}
        </div>
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
  packs,
  onChange,
  onClose,
  onCreated,
  onError,
}: {
  documents: DraftDocument[];
  packs: PackLabel[];
  onChange: (documents: DraftDocument[]) => void;
  onClose: () => void;
  onCreated: (id: string) => void;
  onError: (message: string | null) => void;
}) {
  const namespaces = [...new Set(documents.filter((item) => item.kind === "ObjectType").map((item) => item.id.split(".")[0] ?? ""))].filter(Boolean);
  const [namespace, setNamespace] = useState(namespaces[0] ?? "");
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
    if (!namespace) {
      setFormError("请先选择领域");
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
            {namespaces.map((item) => <option key={item} value={item}>{namespaceLabel(item, packs)}</option>)}
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
    const ns = document.id.includes(".") ? document.id.split(".")[0] : document.id;
    const local = `${String(document.id.split(".").at(-1))}To${String(target.id.split(".").at(-1))}`;
    const id = uniqueDocumentId(documents, ns, local);
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

  function addRule() {
    onChange([...documents, makeRuleForObject(document, documents)]);
    onError(null);
  }

  function addAction() {
    onChange([...documents, makeActionForObject(document, documents)]);
    onError(null);
  }

  async function removeDocument(id: string) {
    try {
      const impacts = await loadDeleteImpacts(id, documents);
      if (impacts.length) {
        onError(`仍被 ${impacts.slice(0, 3).map((item) => item.id).join("、")} 引用，不能删除`);
        return;
      }
      onChange(documents.filter((item) => item.id !== id));
      onError(null);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    }
  }

  return (
    <>
      <div className="chip-row">
        <Chip label="概况" active={tab === "about"} onClick={() => setTab("about")} />
        <Chip label={quick ? `来源 ${mappings.length}` : `属性与来源 ${properties.length}`} active={tab === "properties"} onClick={() => setTab("properties")} />
        {quick ? null : <Chip label={`关系 ${links.length}`} active={tab === "relations"} onClick={() => setTab("relations")} />}
        <Chip label={`判断 ${rules.length}`} active={tab === "rules"} onClick={() => setTab("rules")} />
        {quick ? null : <Chip label={`操作 ${actions.length}`} active={tab === "actions"} onClick={() => setTab("actions")} />}
        <Chip label="DSL 代码" active={tab === "dsl"} onClick={() => setTab("dsl")} />
      </div>
      {tab === "about" ? (
        <div className="entity-sheet">
          <div className="entity-sheet-main">
            <div className="entity-section-card">
              <div className="form-grid">
                <label className="form-field"><span>显示名称</span>
                  <input aria-label="显示名称" value={text(document.label)} onChange={(event) => replace({ ...document, label: event.target.value })} />
                </label>
                <label className="form-field"><span>语义 ID</span>
                  <input value={document.id} readOnly disabled className="is-readonly" />
                </label>
              </div>
              <label className="form-field"><span>描述</span>
                <textarea rows={3} aria-label="实体描述" value={text(document.description)} onChange={(event) => replace({ ...document, description: event.target.value || undefined })} placeholder="这个实体在业务中代表什么、和哪些系统关联" />
              </label>
              <div className="entity-id-meta">
                <span className="entity-meta-item">
                  <span className="meta-label">主业务键</span>
                  <code>{identityKeys.join(", ") || "无"}</code>
                </span>
                <span className="entity-meta-item">
                  <span className="meta-label">所属领域</span>
                  <code>{document.id.split(".")[0]}</code>
                </span>
              </div>
            </div>

            {quick ? null : (
              <div className="entity-section-card">
                <div className="entity-card-header">
                  <span className="entity-card-title">语义资产概览</span>
                  <span className="entity-card-tip">点击卡片切换视图</span>
                </div>
                <div className="entity-stat-grid">
                  <div role="group" tabIndex={0} className="entity-stat-card" onClick={() => setTab("properties")}>
                    <span className="stat-value">{properties.length}</span>
                    <span className="stat-label">属性与测量槽</span>
                  </div>
                  <div role="group" tabIndex={0} className="entity-stat-card" onClick={() => setTab("relations")}>
                    <span className="stat-value">{links.length}</span>
                    <span className="stat-label">业务关系</span>
                  </div>
                  <div role="group" tabIndex={0} className="entity-stat-card" onClick={() => setTab("rules")}>
                    <span className="stat-value">{rules.length}</span>
                    <span className="stat-label">判断规则</span>
                  </div>
                  <div role="group" tabIndex={0} className="entity-stat-card" onClick={() => setTab("actions")}>
                    <span className="stat-value">{actions.length}</span>
                    <span className="stat-label">业务操作</span>
                  </div>
                </div>
              </div>
            )}
          </div>
          {quick ? null : (
            <div className="entity-sheet-side">
              <EntityDslEditor
                document={document}
                allDocuments={documents}
                onChange={replace}
                onError={onError}
              />
            </div>
          )}
        </div>
      ) : null}
      {tab === "dsl" ? (
        <div className="entity-dsl-full-view">
          <EntityDslEditor
            document={document}
            allDocuments={documents}
            onChange={replace}
            onError={onError}
          />
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
            <div className="relation-toolbar">
              <div className="relation-toolbar-info">
                <span className="relation-count-badge">已配置 {links.length} 条业务关系</span>
                <span className="relation-toolbar-hint">配置实体间的关联基数与主外键映射</span>
              </div>
              <button className="secondary sheet-action" onClick={addLink}>＋ 添加关系</button>
            </div>
            {links.length ? links.map((link) => (
              <article className="bind-card relation-card" key={link.id}>
                <div className="relation-card-header">
                  <div className="relation-card-title">
                    <span className="relation-badge">关系</span>
                    <strong>{text(link.label) || link.id}</strong>
                    <code>{link.id}</code>
                  </div>
                  <button className="text-button danger-text" onClick={() => void removeDocument(link.id)}>删除关系</button>
                </div>
                <LinkEditor document={link} documents={documents} onChange={(next) => onChange(replaceDocument(documents, next))} />
              </article>
            )) : <p className="empty">还没有关系。点击右上角「＋ 添加关系」，不必只靠图谱拖拽。</p>}
          </div>
          <div className="entity-sheet-side">
            <EntityDslEditor
              document={document}
              allDocuments={documents}
              defaultScope="closure"
              onChange={replace}
              onError={onError}
            />
          </div>
        </div>
      ) : null}
      {tab === "rules" ? (
        <div className="entity-sheet">
          <div className="entity-sheet-main">
            <p className="mapping-hint">判断用来根据已有数据得出一件事是否成立。结果只有三种：成立、不成立、数据不够无法判断。{publishedExecutionHint()}</p>
            {quick ? null : <button className="secondary sheet-action" onClick={addRule}>添加判断</button>}
            {rules.length ? rules.map((rule) => (
              <article className="bind-card" key={rule.id}>
                {quick ? (
                  <>
                    <strong>{text(rule.label) || rule.id}</strong>
                    <small>{text(rule.description) || "尚未填写说明"}</small>
                  </>
                ) : (
                  <>
                    <label className="form-field"><span>显示名称</span>
                      <input aria-label="判断名称" value={text(rule.label)} onChange={(event) => onChange(replaceDocument(documents, { ...rule, label: event.target.value }))} />
                    </label>
                    <label className="form-field"><span>描述</span>
                      <textarea rows={2} aria-label="判断描述" value={text(rule.description)} onChange={(event) => onChange(replaceDocument(documents, { ...rule, description: event.target.value || undefined }))} />
                    </label>
                    <RuleFields document={rule} documents={documents} onChange={(next) => onChange(replaceDocument(documents, next))} />
                    <button className="text-button" onClick={() => void removeDocument(rule.id)}>删除判断</button>
                  </>
                )}
              </article>
            )) : <p className="empty">{quick ? "这个实体还没有判断。到「实体」页添加。" : "这个实体还没有判断。点上面按钮添加。"}</p>}
          </div>
          {quick ? null : (
            <div className="entity-sheet-side">
              <EntityDslEditor
                document={document}
                allDocuments={documents}
                defaultScope="closure"
                onChange={replace}
                onError={onError}
              />
            </div>
          )}
        </div>
      ) : null}
      {tab === "actions" && !quick ? (
        <div className="entity-sheet">
          <div className="entity-sheet-main">
            <p className="mapping-hint">受控操作会调用外部系统写接口。所有写操作必须通过前置审批和执行对账。</p>
            <button className="secondary sheet-action" onClick={addAction}>添加操作</button>
            {actions.length ? actions.map((action) => (
              <article className="bind-card" key={action.id}>
                <label className="form-field"><span>显示名称</span>
                  <input aria-label="操作名称" value={text(action.label)} onChange={(event) => onChange(replaceDocument(documents, { ...action, label: event.target.value }))} />
                </label>
                <ActionFields
                  document={action}
                  objects={documents.filter((item) => item.kind === "ObjectType")}
                  allDocuments={documents}
                  onDocumentsChange={onChange}
                  onChange={(next) => onChange(replaceDocument(documents, next))}
                />
                <label className="form-field"><span>描述</span>
                  <textarea rows={2} aria-label="操作描述" value={text(action.description)} onChange={(event) => onChange(replaceDocument(documents, { ...action, description: event.target.value || undefined }))} />
                </label>
                <button className="text-button" onClick={() => void removeDocument(action.id)}>删除操作</button>
              </article>
            )) : <p className="empty">这个实体还没有会改业务系统的操作。点上面按钮添加。</p>}
          </div>
          <div className="entity-sheet-side">
            <EntityDslEditor
              document={document}
              allDocuments={documents}
              defaultScope="closure"
              onChange={replace}
              onError={onError}
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

function LinkEditor({ document, documents, onChange }: { document: DraftDocument; documents: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
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
    <div className="link-editor-form">
      <label className="form-field">
        <span>显示名称</span>
        <input aria-label="显示名称" value={text(document.label)} onChange={(event) => onChange({ ...working, label: event.target.value })} placeholder="例如：所属供应商" />
      </label>
      <LinkFields document={working} objects={objects} onChange={onChange} />
      <label className="form-field">
        <span>描述（给 AI 和同事看）</span>
        <textarea rows={2} aria-label="关系描述" value={text(document.description)} onChange={(event) => onChange({ ...working, description: event.target.value || undefined })} placeholder="例如：采购订单关联的唯一供应商主体，用于点查及跨实体约束" />
      </label>
    </div>
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

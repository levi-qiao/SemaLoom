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
import { useI18n } from "./i18n";
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
  const { t } = useI18n();
  if (mode === "create") {
    return <CreateEntityDialog documents={documents} packs={packs} onChange={onChange} onClose={onClose} onCreated={onCreated} onError={onError} />;
  }
  if (mode === "link") {
    const document = documents.find((item) => item.id === targetId && item.kind === "Link");
    if (!document) return null;
    return (
      <Panel title={t("relation.title")} onSave={onSave}>
        <LinkEditor document={document} documents={documents} onChange={(next) => onChange(replaceDocument(documents, next))} />
      </Panel>
    );
  }
  const document = documents.find((item) => item.id === targetId && item.kind === "ObjectType");
  if (!document) {
    return (
      <Panel title={t("entity.config")}>
        <div className="inspector-empty">
          <h2>{t("entity.startFromEntity")}</h2>
          <p>{t("entity.startFromEntityHint")}</p>
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
          <button className="secondary entity-open-full-btn" onClick={() => onOpenEntity(document.id)}>{t("entity.openFull")}</button>
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
  const { t } = useI18n();
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
          {onClose ? <button className="text-button" onClick={onClose} aria-label={t("common.close")}>{t("common.close")}</button> : null}
        </div>
      </div>
      <div className="studio-panel-body">{children}</div>
      {onSave ? <div className="dialog-foot"><button className="primary" onClick={onSave}>{t("common.save")}</button></div> : null}
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
  const { t } = useI18n();
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
      setFormError(t("entity.labelRequired"));
      return;
    }
    if (!LOCAL_ID.test(local)) {
      setFormError(t("entity.idRequired"));
      return;
    }
    if (!namespace) {
      setFormError(t("entity.selectNamespaceFirst"));
      return;
    }
    const document = makeObjectType(namespace, local, display);
    if (description.trim()) document.description = description.trim();
    if (documents.some((item) => item.id === document.id)) {
      setFormError(t("entity.idExists"));
      return;
    }
    onChange([...documents, document]);
    onCreated(document.id);
    onError(null);
    setFormError(null);
  }

  return (
    <Panel title={t("entity.create")} onClose={onClose}>
      <div className="form-grid">
        <label className="form-field"><span>{t("entity.namespace")}</span>
          <select aria-label={t("entity.namespace")} value={namespace} onChange={(event) => setNamespace(event.target.value)}>
            {namespaces.map((item) => <option key={item} value={item}>{namespaceLabel(item, packs)}</option>)}
          </select>
        </label>
        <label className="form-field"><span>{t("entity.label")}</span>
          <input aria-label={t("entity.label")} value={label} onChange={(event) => setLabel(event.target.value)} placeholder={t("entity.labelPlaceholder")} />
        </label>
      </div>
      <label className="form-field"><span>{t("entity.id")}</span>
        <input aria-label={t("entity.id")} value={localId} onChange={(event) => setLocalId(event.target.value)} placeholder={t("entity.idPlaceholder")} />
      </label>
      <label className="form-field"><span>{t("entity.descriptionColleague")}</span>
        <textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder={t("entity.descriptionPlaceholder")} />
      </label>
      {formError ? <p className="field-error" role="alert">{formError}</p> : null}
      <button className="primary" onClick={create}>{t("common.create")}</button>
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
  const { t, locale } = useI18n();
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
      onError(t("entity.createAnotherFirst"));
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
        label: t("relation.defaultLabel"),
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
        const sep = locale === "en" ? ", " : "、";
        onError(t("entity.referencedCannotDelete", { impacts: impacts.slice(0, 3).map((item) => item.id).join(sep) }));
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
        <Chip label={t("entity.tab.about")} active={tab === "about"} onClick={() => setTab("about")} />
        <Chip label={quick ? t("entity.tab.sourcesCount", { count: mappings.length }) : t("entity.tab.propertiesCount", { count: properties.length })} active={tab === "properties"} onClick={() => setTab("properties")} />
        {quick ? null : <Chip label={t("entity.tab.relations", { count: links.length })} active={tab === "relations"} onClick={() => setTab("relations")} />}
        <Chip label={t("entity.tab.rules", { count: rules.length })} active={tab === "rules"} onClick={() => setTab("rules")} />
        {quick ? null : <Chip label={t("entity.tab.actions", { count: actions.length })} active={tab === "actions"} onClick={() => setTab("actions")} />}
        <Chip label={t("entity.tab.dsl")} active={tab === "dsl"} onClick={() => setTab("dsl")} />
      </div>
      {tab === "about" ? (
        <div className="entity-sheet">
          <div className="entity-sheet-main">
            <div className="entity-section-card">
              <div className="form-grid">
                <label className="form-field"><span>{t("entity.label")}</span>
                  <input aria-label={t("entity.label")} value={text(document.label)} onChange={(event) => replace({ ...document, label: event.target.value })} />
                </label>
                <label className="form-field"><span>{t("entity.id")}</span>
                  <input value={document.id} readOnly disabled className="is-readonly" />
                </label>
              </div>
              <label className="form-field"><span>{t("entity.description")}</span>
                <textarea rows={3} aria-label={t("entity.description")} value={text(document.description)} onChange={(event) => replace({ ...document, description: event.target.value || undefined })} placeholder={t("entity.fullDescriptionPlaceholder")} />
              </label>
              <div className="entity-id-meta">
                <span className="entity-meta-item">
                  <span className="meta-label">{t("entity.primaryKey")}</span>
                  <code>{identityKeys.join(", ") || t("common.none")}</code>
                </span>
                <span className="entity-meta-item">
                  <span className="meta-label">{t("entity.namespace")}</span>
                  <code>{document.id.split(".")[0]}</code>
                </span>
              </div>
            </div>

            {quick ? null : (
              <div className="entity-section-card">
                <div className="entity-card-header">
                  <span className="entity-card-title">{t("entity.overview")}</span>
                  <span className="entity-card-tip">{t("entity.clickToSwitch")}</span>
                </div>
                <div className="entity-stat-grid">
                  <div role="group" tabIndex={0} className="entity-stat-card" onClick={() => setTab("properties")}>
                    <span className="stat-value">{properties.length}</span>
                    <span className="stat-label">{t("entity.stats.properties")}</span>
                  </div>
                  <div role="group" tabIndex={0} className="entity-stat-card" onClick={() => setTab("relations")}>
                    <span className="stat-value">{links.length}</span>
                    <span className="stat-label">{t("entity.stats.relations")}</span>
                  </div>
                  <div role="group" tabIndex={0} className="entity-stat-card" onClick={() => setTab("rules")}>
                    <span className="stat-value">{rules.length}</span>
                    <span className="stat-label">{t("entity.stats.rules")}</span>
                  </div>
                  <div role="group" tabIndex={0} className="entity-stat-card" onClick={() => setTab("actions")}>
                    <span className="stat-value">{actions.length}</span>
                    <span className="stat-label">{t("entity.stats.actions")}</span>
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
                <span className="relation-count-badge">{t("relation.configuredCount", { count: links.length })}</span>
                <span className="relation-toolbar-hint">{t("relation.toolbarHint")}</span>
              </div>
              <button className="secondary sheet-action" onClick={addLink}>{t("relation.add")}</button>
            </div>
            {links.length ? links.map((link) => (
              <article className="bind-card relation-card" key={link.id}>
                <div className="relation-card-header">
                  <div className="relation-card-title">
                    <span className="relation-badge">{t("relation.title")}</span>
                    <strong>{text(link.label) || link.id}</strong>
                    <code>{link.id}</code>
                  </div>
                  <button className="text-button danger-text" onClick={() => void removeDocument(link.id)}>{t("relation.delete")}</button>
                </div>
                <LinkEditor document={link} documents={documents} onChange={(next) => onChange(replaceDocument(documents, next))} />
              </article>
            )) : <p className="empty">{t("relation.empty")}</p>}
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
            <p className="mapping-hint">{t("rule.hint")}{publishedExecutionHint()}</p>
            {quick ? null : <button className="secondary sheet-action" onClick={addRule}>{t("rule.add")}</button>}
            {rules.length ? rules.map((rule) => (
              <article className="bind-card" key={rule.id}>
                {quick ? (
                  <>
                    <strong>{text(rule.label) || rule.id}</strong>
                    <small>{text(rule.description) || t("rule.noDesc")}</small>
                  </>
                ) : (
                  <>
                    <label className="form-field"><span>{t("entity.label")}</span>
                      <input aria-label={t("rule.name")} value={text(rule.label)} onChange={(event) => onChange(replaceDocument(documents, { ...rule, label: event.target.value }))} />
                    </label>
                    <label className="form-field"><span>{t("common.desc")}</span>
                      <textarea rows={2} aria-label={t("rule.desc")} value={text(rule.description)} onChange={(event) => onChange(replaceDocument(documents, { ...rule, description: event.target.value || undefined }))} />
                    </label>
                    <RuleFields document={rule} documents={documents} onChange={(next) => onChange(replaceDocument(documents, next))} />
                    <button className="text-button" onClick={() => void removeDocument(rule.id)}>{t("rule.delete")}</button>
                  </>
                )}
              </article>
            )) : <p className="empty">{quick ? t("rule.emptyQuick") : t("rule.emptyFull")}</p>}
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
            <p className="mapping-hint">{t("action.hint")}</p>
            <button className="secondary sheet-action" onClick={addAction}>{t("action.add")}</button>
            {actions.length ? actions.map((action) => (
              <article className="bind-card" key={action.id}>
                <label className="form-field"><span>{t("entity.label")}</span>
                  <input aria-label={t("action.name")} value={text(action.label)} onChange={(event) => onChange(replaceDocument(documents, { ...action, label: event.target.value }))} />
                </label>
                <ActionFields
                  document={action}
                  objects={documents.filter((item) => item.kind === "ObjectType")}
                  allDocuments={documents}
                  onDocumentsChange={onChange}
                  onChange={(next) => onChange(replaceDocument(documents, next))}
                />
                <label className="form-field"><span>{t("common.desc")}</span>
                  <textarea rows={2} aria-label={t("action.desc")} value={text(action.description)} onChange={(event) => onChange(replaceDocument(documents, { ...action, description: event.target.value || undefined }))} />
                </label>
                <button className="text-button" onClick={() => void removeDocument(action.id)}>{t("action.delete")}</button>
              </article>
            )) : <p className="empty">{t("action.empty")}</p>}
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
  const { t } = useI18n();
  const [profiles, setProfiles] = useState<SourceProfileSummary[]>([]);

  useEffect(() => {
    fetch("/v0.1/studio/sources?draftId=default")
      .then(checkedJson)
      .then((payload) => setProfiles(payload.sources ?? []))
      .catch((cause) => onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR"));
  }, [onError]);

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
      <p className="mapping-hint">{t("mapping.dialogHint")}</p>
      {compact ? null : <button className="secondary" onClick={addMapping}>{t("mapping.addSource")}</button>}
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
      {mappings.length === 0 ? <p className="empty">{t("mapping.noSourcesYet")}</p> : null}
    </div>
  );
}

function LinkEditor({ document, documents, onChange }: { document: DraftDocument; documents: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
  const { t } = useI18n();
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
        <span>{t("entity.label")}</span>
        <input aria-label={t("entity.label")} value={text(document.label)} onChange={(event) => onChange({ ...working, label: event.target.value })} placeholder={t("relation.placeholderName")} />
      </label>
      <LinkFields document={working} objects={objects} onChange={onChange} />
      <label className="form-field">
        <span>{t("entity.descriptionColleague")}</span>
        <textarea rows={2} aria-label={t("relation.desc")} value={text(document.description)} onChange={(event) => onChange({ ...working, description: event.target.value || undefined })} placeholder={t("relation.placeholderDesc")} />
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

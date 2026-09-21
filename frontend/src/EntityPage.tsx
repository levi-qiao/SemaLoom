import { useMemo, useState } from "react";

import { LOCAL_ID, makeObjectType, ownedByEntity } from "./doc";
import { namespaceLabel, type PackLabel } from "./labels";
import { EntityEditor, Panel, loadDeleteImpacts } from "./StudioDialog";
import { useI18n } from "./i18n";
import type { DraftDocument } from "./types";

type Props = {
  documents: DraftDocument[];
  savedDocuments: DraftDocument[];
  savedRevision: number;
  search: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onChange: (documents: DraftDocument[]) => void;
  onError: (message: string | null) => void;
  packs?: PackLabel[];
};

export function EntityPage({
  documents,
  savedDocuments,
  savedRevision,
  search,
  selectedId,
  onSelect,
  onChange,
  onError,
  packs = [],
}: Props) {
  const { t, locale } = useI18n();
  const namespaces = [...new Set(documents.filter((item) => item.kind === "ObjectType").map((item) => item.id.split(".")[0] ?? ""))].filter(Boolean);
  const [namespace, setNamespace] = useState("");
  const [label, setLabel] = useState("");
  const [localId, setLocalId] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const objects = useMemo(
    () =>
      documents.filter((item) => {
        if (item.kind !== "ObjectType") return false;
        if (namespace && !item.id.startsWith(`${namespace}.`)) return false;
        return `${item.id} ${item.label ?? ""}`.toLowerCase().includes(search.toLowerCase());
      }),
    [documents, search, namespace],
  );
  const selected = documents.find((item) => item.kind === "ObjectType" && item.id === selectedId)
    ?? (selectedId ? null : objects[0] ?? null);

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
    const prefix = namespace || namespaces[0];
    if (!prefix) {
      setFormError(t("entity.selectNamespaceFirst"));
      return;
    }
    const document = makeObjectType(prefix, local, display);
    if (documents.some((item) => item.id === document.id)) {
      setFormError(t("entity.idExists"));
      return;
    }
    onChange([...documents, document]);
    onSelect(document.id);
    setLabel("");
    setLocalId("");
    setFormError(null);
    onError(null);
  }

  async function requestDelete() {
    if (!selected) return;
    try {
      const impacts = await loadDeleteImpacts(selected.id, documents);
      if (impacts.length) {
        const sep = locale === "en" ? ", " : "、";
        onError(t("entity.referencedCannotDelete", { impacts: impacts.slice(0, 3).map((item) => item.id).join(sep) }));
        setConfirmDelete(false);
        return;
      }
      setConfirmDelete(true);
      onError(null);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    }
  }

  function confirmRemove() {
    if (!selected) return;
    onChange(
      documents.filter((item) => item.id !== selected.id && !ownedByEntity(item, selected.id)),
    );
    onSelect(objects.find((item) => item.id !== selected.id)?.id ?? "");
    setConfirmDelete(false);
  }

  return (
    <>
      <div className="content-pane">
        <div className="entity-list">
          <div className="entity-create">
            <select
              aria-label={t("entity.namespace")}
              value={namespace}
              onChange={(event) => {
                setNamespace(event.target.value);
                const next = documents.find((item) => item.kind === "ObjectType" && (!event.target.value || item.id.startsWith(`${event.target.value}.`)));
                if (next) onSelect(next.id);
              }}
            >
              <option value="">{t("entity.allNamespaces")}</option>
              {namespaces.map((item) => <option key={item} value={item}>{namespaceLabel(item, packs)}</option>)}
            </select>
            <input aria-label={t("entity.label")} value={label} onChange={(event) => setLabel(event.target.value)} placeholder={t("entity.labelPlaceholder")} />
            <input aria-label={t("entity.id")} value={localId} onChange={(event) => setLocalId(event.target.value)} placeholder={t("entity.idPlaceholder")} />
            <button className="secondary" onClick={create}>{t("entity.create")}</button>
            {formError ? <p className="field-error" role="alert">{formError}</p> : null}
          </div>
          <ul className="definition-browser-list">
            {objects.map((item) => (
              <li key={item.id}>
                <button className={selected?.id === item.id ? "active" : ""} onClick={() => onSelect(item.id)}>
                  <span>{String(item.label || item.id)}</span>
                  <code>{item.id}</code>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
      {selected ? (
        <Panel title={String(selected.label || selected.id)}>
          <EntityEditor
            document={selected}
            documents={documents}
            savedDocuments={savedDocuments}
            savedRevision={savedRevision}
            variant="full"
            onChange={onChange}
            onError={onError}
          />
          <div className="entity-danger-card">
            {confirmDelete ? (
              <div className="confirm-delete">
                <p>{t("entity.deletePrompt", { name: String(selected.label || selected.id) })}</p>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="danger-button" onClick={confirmRemove}>{t("common.confirmDelete")}</button>
                  <button className="secondary" onClick={() => setConfirmDelete(false)}>{t("common.cancel")}</button>
                </div>
              </div>
            ) : (
              <div className="entity-danger-bar">
                <div className="entity-danger-info">
                  <strong>{t("entity.delete")}</strong>
                  <span>{t("entity.deleteHint")}</span>
                </div>
                <button className="danger-button outline" onClick={() => void requestDelete()}>{t("entity.deleteThis")}</button>
              </div>
            )}
          </div>
        </Panel>
      ) : (
        <Panel title={t("entity.title")}>
          <div className="inspector-empty">
            <h2>{t("entity.maintain")}</h2>
            <p>{t("entity.maintainHint")}</p>
          </div>
        </Panel>
      )}
    </>
  );
}

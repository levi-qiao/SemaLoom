import { useMemo, useState } from "react";

import { LOCAL_ID, makeObjectType, ownedByEntity } from "./doc";
import { namespaceLabel } from "./labels";
import { EntityEditor, Panel, loadDeleteImpacts } from "./StudioDialog";
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
}: Props) {
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
      setFormError("请填写显示名称");
      return;
    }
    if (!LOCAL_ID.test(local)) {
      setFormError("请填写英文语义 ID，字母开头，仅含字母数字和下划线");
      return;
    }
    const prefix = namespace || namespaces[0] || "procurement";
    const document = makeObjectType(prefix, local, display);
    if (documents.some((item) => item.id === document.id)) {
      setFormError("该语义 ID 已存在");
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
        onError(`仍被 ${impacts.slice(0, 3).map((item) => item.id).join("、")} 引用，不能删除`);
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
              aria-label="领域"
              value={namespace}
              onChange={(event) => {
                setNamespace(event.target.value);
                const next = documents.find((item) => item.kind === "ObjectType" && (!event.target.value || item.id.startsWith(`${event.target.value}.`)));
                if (next) onSelect(next.id);
              }}
            >
              <option value="">全部领域</option>
              {namespaces.map((item) => <option key={item} value={item}>{namespaceLabel(item)}</option>)}
            </select>
            <input aria-label="显示名称" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="显示名称，例如 仓库" />
            <input aria-label="语义 ID" value={localId} onChange={(event) => setLocalId(event.target.value)} placeholder="英文语义 ID，例如 Warehouse" />
            <button className="secondary" onClick={create}>新建实体</button>
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
          {confirmDelete ? (
            <div className="confirm-delete">
              <p>确定删除实体「{String(selected.label || selected.id)}」？其他未保存修改会保留。</p>
              <button className="danger-button" onClick={confirmRemove}>确认删除</button>
              <button className="secondary" onClick={() => setConfirmDelete(false)}>取消</button>
            </div>
          ) : (
            <button className="danger-button" onClick={() => void requestDelete()}>删除此实体</button>
          )}
        </Panel>
      ) : (
        <Panel title="实体">
          <div className="inspector-empty">
            <h2>维护实体</h2>
            <p>在左侧新建或选择一个实体，这里改属性、来源对应、判断和操作。</p>
          </div>
        </Panel>
      )}
    </>
  );
}

import { useEffect, useMemo, useState } from "react";

import { checkedJson } from "./api";
import { mappingResourceLabel, text } from "./doc";
import { makeMappingDocument, MappingEditor } from "./MappingEditor";
import type { DraftDocument, SourceProfileSummary } from "./types";

type Props = {
  documents: DraftDocument[];
  savedDocuments?: DraftDocument[];
  savedRevision?: number;
  search: string;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onChange: (documents: DraftDocument[]) => void;
  onError: (message: string | null) => void;
};

export function MappingPage({
  documents,
  savedDocuments = [],
  savedRevision = 0,
  search,
  selectedId,
  onSelect,
  onChange,
  onError,
}: Props) {
  const objects = documents.filter((item) => item.kind === "ObjectType");
  const mappingDocs = useMemo(
    () =>
      documents.filter(
        (item) =>
          item.kind === "Mapping" &&
          `${item.id} ${item.target ?? ""} ${item.objectType ?? ""}`.toLowerCase().includes(search.toLowerCase()),
      ),
    [documents, search],
  );
  const selected = documents.find((item) => item.id === selectedId && item.kind === "Mapping") ?? null;
  const [profiles, setProfiles] = useState<SourceProfileSummary[]>([]);

  useEffect(() => {
    if (!mappingDocs.some((item) => item.id === selectedId)) onSelect(mappingDocs[0]?.id ?? null);
  }, [mappingDocs, selectedId, onSelect]);

  useEffect(() => {
    void fetch("/v0.1/studio/source-profiles")
      .then(checkedJson)
      .then((payload) => setProfiles(payload.profiles ?? []))
      .catch(() => setProfiles([]));
  }, []);

  function createMapping() {
    const objectType = objects[0];
    if (!objectType) {
      onError("请先创建实体");
      return;
    }
    const source = profiles[0];
    const document = makeMappingDocument(objectType, source?.sourceId ?? "orders_pg", source?.provider ?? "postgres", documents);
    onChange([...documents, document]);
    onSelect(document.id);
  }

  const objectType = objects.find((item) => item.id === text(selected?.objectType) || item.id === text(selected?.target));
  const saved = savedDocuments.find((item) => item.id === selected?.id && item.kind === "Mapping");

  return (
    <div className="draft-editor mapping-page">
      <section className="definition-browser" aria-label="Mapping 列表">
        <div className="draft-tools">
          <button className="secondary" onClick={createMapping}>新建 Mapping</button>
        </div>
        <ul className="definition-browser-list">
          {mappingDocs.map((item) => (
            <li key={item.id}>
              <button className={selectedId === item.id ? "active" : ""} onClick={() => onSelect(item.id)}>
                <span>{String(item.label || item.target || item.id)}</span>
                <code>{text(item.sourceId)} / {mappingResourceLabel(item)}</code>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="definition-form mapping-form" aria-label="字段映射">
        {selected ? (
          <>
            <div className="definition-form-head">
              <div><span>MAPPING</span><h2>{selected.id}</h2></div>
            </div>
            <p className="mapping-hint">
              {text(selected.provider) === "openapi"
                ? "先选已授权 GET 操作，再把属性对到响应字段。不要求表名或列名。"
                : "先选实体和数据源里的表，再把属性对到列。不要手填表名或列名。"}
            </p>
            <div className="form-grid">
              <label className="form-field">
                <span>业务实体</span>
                <select
                  aria-label="业务实体"
                  value={text(selected.objectType)}
                  onChange={(event) => onChange(documents.map((item) => item.id === selected.id ? { ...selected, objectType: event.target.value, target: event.target.value } : item))}
                >
                  {objects.map((item) => <option key={item.id} value={item.id}>{String(item.label || item.id)}</option>)}
                </select>
              </label>
            </div>
            <MappingEditor
              mapping={selected}
              objectType={objectType}
              documents={documents}
              profiles={profiles}
              saved={Boolean(saved) && JSON.stringify(saved) === JSON.stringify(selected)}
              savedRevision={savedRevision}
              onChange={onChange}
              onError={onError}
            />
          </>
        ) : (
          <div className="inspector-empty">
            <h2>配置 Mapping</h2>
            <p>选择或新建一条 Mapping。PostgreSQL 绑定表和列，OpenAPI 绑定操作和响应字段。</p>
          </div>
        )}
      </section>
    </div>
  );
}

import { useEffect, useState } from "react";

import { checkedJson } from "./api";
import { MappingEditor } from "./MappingEditor";
import { cardinalityLabel } from "./labels";
import type { DraftDocument, Inspector, SourceProfileSummary } from "./types";

type Section = "properties" | "relations" | "actions" | "sources";

type Props = {
  inspector: Inspector | null;
  documents: DraftDocument[];
  savedDocuments?: DraftDocument[];
  savedRevision?: number;
  onSelect: (id: string) => void;
  onDocuments: (documents: DraftDocument[]) => void;
  onOpenSource: (sourceId: string) => void;
  onEdit: (view: "objects" | "links" | "actions" | "mappings", id: string) => void;
  onError: (message: string | null) => void;
};

export function EntityPanel({ inspector, documents, savedDocuments = [], savedRevision = 0, onSelect, onDocuments, onOpenSource, onEdit, onError }: Props) {
  const [section, setSection] = useState<Section | null>(null);
  const [activeMapping, setActiveMapping] = useState<string | null>(null);

  useEffect(() => {
    setSection(null);
    setActiveMapping(null);
  }, [inspector?.id]);

  if (!inspector) {
    return (
      <aside className="inspector" aria-label="实体检查器">
        <div className="inspector-empty">
          <h2>选择一个实体</h2>
          <p>图谱只读浏览。点节点查看详情；新增和修改请到左侧「实体 / 关系 / 规则 / 操作」。</p>
        </div>
      </aside>
    );
  }

  const mapping = inspector.mappings.find((item) => item.id === activeMapping) ?? null;
  const live = documents.find((item) => item.id === inspector.id);
  const label = typeof live?.label === "string" ? live.label : inspector.label;

  return (
    <aside className="inspector" aria-label="实体检查器">
      <div className="inspector-kicker">
        <span>{inspector.namespace}</span>
        <span>v{inspector.version}</span>
      </div>
      <h2>{label}</h2>
      <code className="semantic-id">{inspector.id}</code>
      <div className="chip-row">
        <button className="secondary" onClick={() => onEdit("objects", inspector.id)}>编辑实体</button>
        {inspector.mappings[0] ? <button className="secondary" onClick={() => onEdit("mappings", inspector.mappings[0].id)}>配置映射</button> : null}
      </div>
      <div className="chip-row">
        <Chip label="属性" count={inspector.properties.length} active={section === "properties"} onClick={() => setSection(section === "properties" ? null : "properties")} />
        <Chip label="关系" count={inspector.relations.length} active={section === "relations"} onClick={() => setSection(section === "relations" ? null : "relations")} />
        <Chip label="操作" count={inspector.actions.length} active={section === "actions"} onClick={() => setSection(section === "actions" ? null : "actions")} />
        <Chip label="来源" count={inspector.mappings.length} active={section === "sources"} onClick={() => setSection(section === "sources" ? null : "sources")} />
      </div>
      {section === "properties" ? (
        <ul className="definition-list">
          {inspector.properties.map((item) => (
            <li key={item.id}>
              <span>
                <strong>{item.label ?? item.id}</strong>
                <code>{item.id}</code>
              </span>
              <small>{item.valueType}{item.unit ? ` · ${item.unit}` : ""}{item.required ? " · 必需" : ""}</small>
            </li>
          ))}
        </ul>
      ) : null}
      {section === "relations" ? (
        inspector.relations.length ? (
          <ul className="definition-list">
            {inspector.relations.map((item) => (
              <li key={item.id}>
                <button className="definition-link" onClick={() => onSelect(item.target)}>
                  <span>{item.label}</span>
                  <small>{item.direction === "OUTGOING" ? "→" : "←"} {item.targetLabel} · {cardinalityLabel(item.cardinality)}</small>
                </button>
                <button className="text-button" onClick={() => onEdit("links", item.id)}>编辑</button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">尚无业务关系。请到「关系」菜单新建。</p>
        )
      ) : null}
      {section === "actions" ? (
        inspector.actions.length ? (
          <ul className="definition-list">
            {inspector.actions.map((item) => (
              <li key={item.id} className="action-item">
                <span>
                  <strong>{item.label}</strong>
                  <code>{item.id}</code>
                  <small className="action-effect">{item.effect}</small>
                </span>
                <button className="text-button" onClick={() => onEdit("actions", item.id)}>编辑</button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">尚无业务操作</p>
        )
      ) : null}
      {section === "sources" ? (
        <div className="source-bind-list">
          {inspector.mappings.length ? inspector.mappings.map((item) => (
            <button
              key={item.id}
              className={item.id === activeMapping ? "bind-card active" : "bind-card"}
              aria-label={`绑定 ${item.id}`}
              onClick={() => setActiveMapping(item.id === activeMapping ? null : item.id)}
            >
              <strong>{item.target}</strong>
              <small>{item.sourceId} / {item.resource}</small>
            </button>
          )) : <p className="empty">此实体尚未配置来源</p>}
          {mapping ? (
            <MappingBind
              mappingId={mapping.id}
              documents={documents}
              savedDocuments={savedDocuments}
              savedRevision={savedRevision}
              onDocuments={onDocuments}
              onOpenSource={onOpenSource}
              onError={onError}
            />
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}

function Chip({ label, count, active, onClick }: { label: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button className={active ? "chip active" : "chip"} onClick={onClick} aria-pressed={active}>
      {label} {count}
    </button>
  );
}

function MappingBind({
  mappingId,
  documents,
  savedDocuments,
  savedRevision,
  onDocuments,
  onOpenSource,
  onError,
}: {
  mappingId: string;
  documents: DraftDocument[];
  savedDocuments: DraftDocument[];
  savedRevision: number;
  onDocuments: (documents: DraftDocument[]) => void;
  onOpenSource: (sourceId: string) => void;
  onError: (message: string | null) => void;
}) {
  const mapping = documents.find((item) => item.id === mappingId);
  const [profiles, setProfiles] = useState<SourceProfileSummary[]>([]);
  useEffect(() => {
    void fetch("/v0.1/studio/source-profiles")
      .then(checkedJson)
      .then((payload) => setProfiles(payload.profiles ?? []))
      .catch(() => setProfiles([]));
  }, []);
  if (!mapping) return null;
  const objectType = documents.find((item) => item.id === mapping.objectType || item.id === mapping.target);
  const saved = savedDocuments.find((item) => item.id === mapping.id && item.kind === "Mapping");
  return (
    <div className="mapping-bind">
      <div className="meta-row">
        <span>数据源</span>
        <button className="text-button" onClick={() => onOpenSource(String(mapping.sourceId))}>{String(mapping.sourceId)}</button>
      </div>
      <MappingEditor
        mapping={mapping}
        objectType={objectType}
        documents={documents}
        profiles={profiles}
        saved={Boolean(saved) && JSON.stringify(saved) === JSON.stringify(mapping)}
        savedRevision={savedRevision}
        onChange={onDocuments}
        onError={onError}
      />
    </div>
  );
}

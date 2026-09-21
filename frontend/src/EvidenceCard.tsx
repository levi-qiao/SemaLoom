import { useState, type ReactNode } from "react";
import { Modal } from "./Modal";
import { currentLocale, useI18n, evidenceLabels, evidenceOperations, evidenceToolNames, translate } from "./i18n";

export type Evidence = { id: string; tool: string; result: Record<string, any>; lineage?: Record<string, any>[] };

function labelMap() {
  const loc = currentLocale();
  return evidenceLabels[loc] ?? evidenceLabels["zh-CN"];
}
function operationMap() {
  const loc = currentLocale();
  return evidenceOperations[loc] ?? evidenceOperations["zh-CN"];
}
function toolNameMap() {
  const loc = currentLocale();
  return evidenceToolNames[loc] ?? evidenceToolNames["zh-CN"];
}

const typeLabels: Record<string, string> = {
  DECIMAL: "DECIMAL",
  INTEGER: "INTEGER",
  STRING: "STRING",
  BOOLEAN: "BOOLEAN",
  DATE: "DATE",
  TIMESTAMP: "TIMESTAMP",
};

const text = (value: any): string => {
  const localLabels = labelMap();
  const localOperations = operationMap();
  const loc = currentLocale();
  const en = loc === "en";
  return value === null || value === undefined
    ? "—"
    : typeof value === "boolean"
    ? value
      ? translate(loc, "common.yes")
      : translate(loc, "common.no")
    : Array.isArray(value)
    ? value.length === 0
      ? "—"
      : value.map(text).join(en ? ", " : "、")
    : typeof value === "object"
    ? Object.entries(value)
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => `${localLabels[k] ?? k}${en ? ": " : "："}${text(v)}`)
        .join(en ? "; " : "；") || "—"
    : localOperations[String(value)] ?? String(value);
};

function grainText(grain: any, names?: Record<string, string>): string {
  const localLabels = labelMap();
  const separator = currentLocale() === "en" ? ": " : "：";
  if (!grain || typeof grain !== "object") return text(grain);
  return Object.entries(grain).map(([key, value]) => {
    const shown = names?.[key];
    return shown
      ? `${localLabels[key] ?? key}${separator}${shown} (${text(value)})`
      : `${localLabels[key] ?? key}${separator}${text(value)}`;
  }).join(currentLocale() === "en" ? "; " : "；") || "—";
}

function formatPerspectiveUnit(item: Record<string, any>, t: (k: string) => string): string {
  const localOperations = operationMap();
  const parts: string[] = [];
  if (item.perspective && item.perspective !== "—") {
    parts.push(`${t("evidence.grain")}：${localOperations[item.perspective] ?? item.perspective}`);
  }
  if (item.unit && item.unit !== "—") {
    parts.push(`${t("evidence.unit")}：${item.unit}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "—";
}

function Table({ heads, rows }: { heads: string[]; rows: ReactNode[][] }) {
  return rows.length ? (
    <div className="evidence-table-wrap">
      <table>
        <thead><tr>{heads.map(h => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j}>{v}</td>)}</tr>)}</tbody>
      </table>
    </div>
  ) : null;
}

function Fields({ value }: { value: Record<string, any> }) {
  const { t } = useI18n();
  const entries = Object.entries(value).filter(([, v]) => {
    if (v === undefined || v === null || v === "") return false;
    if (Array.isArray(v) && v.length === 0) return false;
    return true;
  });
  const localLabels = labelMap();
  return <Table heads={[t("evidence.item"), t("evidence.value")]} rows={entries.map(([k, v]) => [localLabels[k] ?? k, text(v)])} />;
}

function Records({ items }: { items: Record<string, any>[] }) {
  const localLabels = labelMap();
  const keys = [...new Set(items.flatMap(item => Object.keys(item)))];
  return <Table heads={keys.map(k => localLabels[k] ?? k)} rows={items.map(item => keys.map(k => text(item[k])))} />;
}

function Observations({ items }: { items: any[] }) {
  const { t } = useI18n();
  const localOperations = operationMap();
  const heads = [
    t("evidence.metricOrObject"),
    t("evidence.engineValue"),
    t("evidence.statusOrReason"),
    t("evidence.sourceMapping"),
    t("evidence.observedAt"),
  ];
  return (
    <Table
      heads={heads}
      rows={items.map(o => {
        let value = o.value;
        if (o.valueType === "OBJECT" || (typeof value === "string" && value.startsWith("{"))) {
          try { value = JSON.parse(value); } catch { /* Preserve a plain source string. */ }
        }
        return [
          o.target,
          <>{text(value)} {o.unit ?? ""}</>,
          `${localOperations[o.kind] ?? o.kind}${o.reason ? ` · ${o.reason}` : ""}`,
          text(o.mappingId ?? o.ruleId),
          text(o.observedAt),
        ];
      })}
    />
  );
}

type InspectData = {
  title: string;
  kind?: string;
  data: Record<string, any>;
};

function collectCatalog(evidence: Evidence): Record<string, string> {
  const catalog: Record<string, string> = {};
  const result = evidence.result ?? {};
  if (result.labels && typeof result.labels === "object") {
    for (const [key, value] of Object.entries(result.labels)) {
      if (typeof value === "string" && value) catalog[key] = value;
    }
  }
  for (const item of result.definitions ?? []) {
    if (item?.id && item.label) catalog[item.id] = item.label;
  }
  for (const item of evidence.lineage ?? []) {
    if (item?.id && item.label) catalog[item.id] = item.label;
    if (item?.sourceId && item.label) catalog[item.sourceId] = item.label;
  }
  return catalog;
}

function named(id: string | undefined, catalog: Record<string, string>, fallback?: string): string {
  if (!id) return fallback ?? "—";
  return catalog[id] ?? fallback ?? id;
}

function EvidenceModal({
  item,
  lineage,
  catalog,
  onClose,
}: {
  item: InspectData;
  lineage?: Record<string, any>[];
  catalog: Record<string, string>;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const localOperations = operationMap();
  const localLabels = labelMap();
  const data = item.data;
  const kind = data.kind ?? item.kind;
  const humanLabel = data.label ?? named(data.id, catalog);
  const effectText = data.effect ? String(data.effect) : null;
  const descText = data.description ?? effectText ?? null;

  // Find sources either on data itself or from evidence lineage
  const sources: any[] = Array.isArray(data.sources) && data.sources.length > 0
    ? data.sources
    : (lineage ?? []).filter((m: any) => m.target === data.id || m.objectType === data.id);

  return (
    <Modal
      open={true}
      onClose={onClose}
      title={humanLabel}
      subtitle={data.id ? <code className="evidence-modal-id">{data.id}</code> : undefined}
      badge={
        kind ? (
          <span className={`evidence-modal-badge kind-${String(kind).toLowerCase()}`}>
            {localOperations[kind] ?? localLabels[kind] ?? kind}
          </span>
        ) : undefined
      }
      size="lg"
      className="evidence-modal"
      bodyClassName="evidence-modal-inner"
    >
      <div className="evidence-modal-content-wrap">
        {/* 1. Business explanation */}
        <div className="evidence-inspect-card">
          <h4 className="inspect-section-title">{t("evidence.inspectTitle")}</h4>
          {descText && <p className="inspect-desc">{descText}</p>}
          {effectText && effectText !== descText && (
            <div className="inspect-callout">
              <strong>{t("evidence.executionEffect")}</strong>
              <span>{effectText}</span>
            </div>
          )}
          {(data.perspective || data.unit) && (
            <div className="inspect-tags-row">
              {data.perspective && (
                <span className="inspect-tag">{t("evidence.grain")}：{localOperations[data.perspective] ?? data.perspective}</span>
              )}
              {data.unit && (
                <span className="inspect-tag">{t("evidence.unit")}：{data.unit}</span>
              )}
            </div>
          )}
        </div>

        {/* 2. Target Object & Rules */}
        {(data.targetObject || (Array.isArray(data.preconditions) && data.preconditions.length > 0)) && (
          <div className="evidence-inspect-card">
            <h4 className="inspect-section-title">{t("evidence.associatedEntitiesRules")}</h4>
            {data.targetObject && (
              <div className="inspect-kv-row">
                <span className="kv-label">{t("evidence.assocBusinessObject")}</span>
                <span className="kv-value">
                  <strong>{named(data.targetObject, catalog)}</strong>
                  <code>{data.targetObject}</code>
                </span>
              </div>
            )}
            {Array.isArray(data.preconditions) && data.preconditions.length > 0 && (
              <div className="inspect-kv-row">
                <span className="kv-label">{t("evidence.preconditionRule")}</span>
                <div className="kv-list">
                  {data.preconditions.map((p: string) => (
                    <div key={p} className="rule-chip">
                      <span className="rule-name">{named(p, catalog)}</span>
                      <code>{p}</code>
                      <span className="rule-badge">{t("evidence.preconditionBadge")}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* 3. Input Parameters */}
        {Array.isArray(data.parameters) && data.parameters.length > 0 && (
          <div className="evidence-inspect-card">
            <h4 className="inspect-section-title">{t("evidence.inputParamsTitle", { count: data.parameters.length })}</h4>
            <Table
              heads={[t("evidence.paramName"), t("evidence.paramMeaning"), t("evidence.paramDataType"), t("evidence.paramRequirement")]}
              rows={data.parameters.map((p: any) => [
                <code key="p-name">{p.name}</code>,
                named(p.name, catalog, p.label ?? "—"),
                <span key="p-type" className="evidence-type-badge">{typeLabels[p.valueType] ?? p.valueType ?? p.type ?? "STRING"}</span>,
                p.required ? <span key="p-req" className="badge-required">{t("evidence.badgeRequired")}</span> : <span key="p-opt" className="badge-optional">{t("evidence.badgeOptional")}</span>
              ])}
            />
          </div>
        )}

        {/* 4. Source Provenance */}
        <div className="evidence-inspect-card source-lineage-card">
          <h4 className="inspect-section-title">{t("evidence.provenanceTitle")}</h4>
          {sources.length > 0 ? (
            sources.map((s: any, idx: number) => (
              <div key={idx} className="source-item">
                <div className="source-header">
                  <div className="source-badge-wrap">
                    <span className="source-provider-badge">{s.provider ?? (s.type === "actionBinding" ? "openapi" : "database")}</span>
                    <strong>{s.label ?? named(s.sourceId, catalog)}</strong>
                  </div>
                  {s.resource && <code className="source-resource">{s.resource}</code>}
                </div>
                {s.operation && (
                  <div className="source-prop">
                    <span className="prop-label">{t("evidence.correspondingOp")}</span>
                    <code>{s.operation}</code>
                  </div>
                )}
                {s.idempotent !== undefined && (
                  <div className="source-flags">
                    {s.idempotent && <span className="flag-tag">{t("evidence.idempotentBadge")}</span>}
                    {s.reconcilable && <span className="flag-tag">{t("evidence.reconcilableBadge")}</span>}
                  </div>
                )}
                {Array.isArray(s.fields) && s.fields.length > 0 && (
                  <div className="source-fields-table">
                    <Table
                      heads={[t("evidence.businessField"), t("evidence.physicalField"), t("evidence.fieldUsage")]}
                      rows={s.fields.map((f: any) => [
                        <strong key="sf">{named(f.semanticField, catalog)}</strong>,
                        <code key="pf">{f.physicalField}</code>,
                        <span key="role" className="role-tag">{localOperations[f.role] ?? localLabels[f.role] ?? f.role}</span>
                      ])}
                    />
                  </div>
                )}
              </div>
            ))
          ) : (
            <p className="inspect-note">{t("evidence.unmappedNotice")}</p>
          )}
        </div>

        {/* 5. Technical Metadata (Collapsed) */}
        <details className="evidence-inspect-tech">
          <summary>{t("evidence.techSpecsSummary")}</summary>
          <Fields value={{
            [t("evidence.semanticVersion")]: data.version,
            [t("evidence.apiVersion")]: data.apiVersion,
            [t("evidence.releaseDigest")]: data.releaseDigest,
            [t("evidence.namespace")]: data.namespace,
          }} />
        </details>
      </div>
    </Modal>
  );
}

export function EvidenceCard({evidence}:{evidence:Evidence}){
  const { t, locale } = useI18n();
  const names = toolNameMap();
  const [inspectItem, setInspectItem] = useState<InspectData | null>(null);
  const d=evidence.result;const claim=d.claim&&typeof d.claim==="object"?d.claim:null;
  const catalog = collectCatalog(evidence);
  const skip=new Set(["observations","checks","sourceActivities","objects","members","candidates","definitions","claim","comparison","comparisonRequest","values","evidence","mappingFields","scope","labels"]);
  const comparison = d.comparison ?? d.scope?.comparison;
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <details
        className={`evidence-card${d.definitions ? " ontology-catalog" : ""}`}
        open={isOpen}
        onToggle={(e) => setIsOpen(e.currentTarget.open)}
      >
        <summary>
          {evidence.id} · {names[evidence.tool]??evidence.tool}
          {d.definitions ? t("evidence.definitionsCount", { count: d.definitions.length }) : ""}
          {claim?` · ${claim.truth}`:""}
        </summary>
        {claim&&<><h4>{t("evidence.engineTruth")}：{claim.truth}</h4><Fields value={claim}/></>}
        {d.values&&<Table heads={[t("evidence.metric"), t("evidence.calcMethod"), t("evidence.grain"), t("evidence.engineValue"), t("evidence.unit")]} rows={d.values.map((v:any)=>[v.metric,text(v.aggregation),grainText(v.grain,v.labels),text(v.value),v.unit])}/>}
        {d.evidence?.rows&&<Table heads={(d.evidence.columns??[]).map((c:any)=>c.label??c.id)} rows={d.evidence.rows}/>}
        {d.mappingFields&&<Table heads={[t("evidence.mapping"), t("evidence.source"), t("evidence.table"), t("evidence.columns")]} rows={d.mappingFields.map((m:any)=>[m.mappingId,m.sourceId,m.table,(m.columns??[]).join(", ")])}/>}
        {d.scope&&typeof d.scope==="object"&&<Fields value={Object.fromEntries(Object.entries(d.scope).filter(([k])=>k!=="comparison"))}/>}
        {d.observations&&<Observations items={d.observations}/>}
        {d.objects&&<Records items={d.objects.map((o:any)=>({...o.identity,...o.properties}))}/>}
        {d.members&&<><h4>{t("evidence.perItemCalc")}</h4><Table heads={[t("evidence.objectIdentity"), t("evidence.statisticalUnit"), t("evidence.engineValue"), t("evidence.unit"), t("evidence.status"), t("evidence.sampleInfo")]} rows={d.members.map((m:any)=>[text(m.identity),text(m.properties?.[d.statisticalUnit]),text(m.observation.value),m.observation.unit,m.observation.kind,<button key="m-inspect" type="button" className="evidence-inspect-btn" onClick={()=>setInspectItem({title:`${text(m.identity)} · ${t("evidence.propertiesDetails")}`, data:m.properties})}>{t("evidence.viewProperties")}</button>])}/></>}
        {comparison&&<><h4>{t("evidence.comparisonResult")}</h4><Fields value={comparison}/><Fields value={d.comparisonRequest??{}}/></>}
        {d.checks?.map((c:any,i:number)=><section key={i}><h4>{t("evidence.ruleCheck", { truth: c.claim?.truth ?? t("labels.validation.pending") })}</h4><Fields value={c.claim??{claimId:c.claimId,reason:c.error}}/>{c.observations&&<Observations items={c.observations}/>}</section>)}
        {d.definitions&&<>
          <p className="evidence-note">{t("evidence.disclaimer")}</p>
          <Table
            heads={[t("evidence.tableType"), t("evidence.tableName"), t("evidence.tableScope"), t("evidence.tableDesc"), t("evidence.tableDetails")]}
            rows={d.definitions.map((item:any)=>[
              text(item.kind),
              <div key="id" className="evidence-entity-id">
                <strong>{item.label ?? named(item.id, catalog)}</strong>
                <br/>
                <code>{item.id}</code>
              </div>,
              formatPerspectiveUnit(item, t),
              item.description ?? item.effect ?? "—",
              <button
                key="inspect"
                type="button"
                className="evidence-inspect-btn"
                onClick={() => setInspectItem({
                  title: item.label ?? named(item.id, catalog),
                  kind: item.kind,
                  data: item
                })}
              >
                {t("evidence.viewDef")}
              </button>
            ])}
          />
          {d.hasMore&&<p className="evidence-note">{t("evidence.moreDefs")}</p>}
        </>}
        {d.candidates&&d.candidates.map((c:any)=><details key={c.id}><summary>{c.label??c.id}</summary><Fields value={c}/></details>)}
        <details><summary>{t("evidence.businessDefAndScope")}</summary><Fields value={Object.fromEntries(Object.entries(d).filter(([k])=>!skip.has(k)))}/></details>
        {!!evidence.lineage?.length&&<><h4>{t("evidence.lineageTitle")}</h4><p className="evidence-note">{t("evidence.lineageNote")}</p>{evidence.lineage.map(m=><section key={m.id}><Fields value={{[t("evidence.dataSource")]:m.sourceId,[t("evidence.tableOrApiOp")]:m.resource,[t("evidence.mappingId")]:m.id}}/><Table heads={[t("evidence.businessField"),t("evidence.physicalField"),t("evidence.fieldUsage")]} rows={m.fields.map((f:any)=>[f.semanticField,f.physicalField,f.role])}/></section>)}</>}
        {d.sourceActivities?.length>0&&<details><summary>{t("evidence.sourceActivitiesTitle", { count: d.sourceActivities.length })}</summary><Table heads={[t("evidence.dataSource"),t("evidence.mapping"),t("evidence.observedAt"),t("evidence.sourceVersion"),t("evidence.queryDigest")]} rows={d.sourceActivities.map((a:any)=>[a.sourceId,a.mappingId,text(a.observedAt),text(a.sourceVersion),a.queryDigest])}/></details>}
        {!evidence.lineage?.length&&d.sourceActivities?.length>0&&<p className="evidence-note">{t("evidence.lineageOmittedNote")}</p>}
      </details>
      {inspectItem && <EvidenceModal item={inspectItem} lineage={evidence.lineage} catalog={catalog} onClose={() => setInspectItem(null)} />}
    </>
  );
}

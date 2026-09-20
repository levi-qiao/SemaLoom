import { useState, type ReactNode } from "react";
import { Modal } from "./Modal";
import { currentLocale, useI18n } from "./i18n";

export type Evidence = { id: string; tool: string; result: Record<string, any>; lineage?: Record<string, any>[] };
const namesZh: Record<string, string> = {list_semantics:"当前业务模型目录",search_semantics:"业务定义候选",describe_semantic:"业务口径",find_objects:"对象与样本",semantic_query:"指标与事实",evaluate_claim:"规则判断",prepare_semantic_query:"语义分析"};
const namesEn: Record<string, string> = {list_semantics:"Ontology catalog",search_semantics:"Definition candidates",describe_semantic:"Semantic definition",find_objects:"Objects and samples",semantic_query:"Metrics and facts",evaluate_claim:"Rule evaluation",prepare_semantic_query:"Semantic analysis"};
const labels: Record<string,string> = {metric:"指标",label:"名称",description:"业务说明",value:"引擎值",unit:"单位",operation:"计算方式",year:"年度",statisticalUnit:"统计单位",populationDescription:"样本范围",populationCount:"范围内数量",observedCount:"有效数量",missingCount:"缺失数量",missingPolicy:"缺失处理",complete:"范围读取完整",status:"状态",reason:"原因",kind:"类型",numerator:"分子",denominator:"分母",formula:"计算公式",direction:"比较方向",decimalPrecision:"十进制精度",consistency:"一致性",truth:"判断",claimId:"命题",evaluationId:"执行编号",predicateVersion:"规则版本",reasonCodes:"判断原因",objectType:"对象类型",identityKeys:"身份字段",grain:"指标粒度",perspective:"口径",aggregation:"计算方式",additivity:"可加性",derivedFrom:"依赖指标",releaseDigest:"语义版本",hasMore:"还有未读取对象",requiresSelection:"需要选择对象",name:"名称",identity:"对象",target:"目标",mappingId:"映射编号",ruleId:"规则编号",observedAt:"观测时间",sourceId:"数据源",resource:"表 / API 操作",semanticField:"业务字段",physicalField:"物理字段 / 响应路径",role:"用途",sourceVersion:"来源版本",queryDigest:"查询摘要",analysisCapabilities:"分析能力",pointLookup:"对象点查",keyedFind:"按业务键查找",collectionJoin:"跨表集合 JOIN",sameTableCollection:"同表集合分析",property:"业务属性",dimension:"分析维度"};
const operations:Record<string,string>={ObjectType:"对象",Metric:"指标",Link:"业务关系",Rule:"规则",Policy:"业务政策",Action:"业务操作",property:"业务属性",dimension:"分析维度",value:"度量值",identity:"身份键",SUM:"合计",AVG:"平均值",MIN:"最小值",MAX:"最大值",COUNT:"有效观测数量",SOURCE_REPEATABLE_READ:"同源只读一致快照",mean:"算术平均",sum:"合计",min:"最小值",max:"最大值",count:"有效观测数量",shareOfTotal:"占总体总额",percentAboveMean:"相对均值增幅",outperforms:"严格超过同行比例",reject:"存在缺失则不计算",exclude:"明确排除缺失",BOUNDED_SEQUENTIAL_READS_NOT_GLOBAL_SNAPSHOT:"有界逐次读取，非全局数据库快照",PRESENT:"已观测",MISSING:"缺失",UNKNOWN:"未知",ERROR:"异常"};
const labelsEn: Record<string,string> = {metric:"Metric",label:"Name",description:"Business description",value:"Engine value",unit:"Unit",operation:"Operation",year:"Year",statisticalUnit:"Statistical unit",populationDescription:"Population",populationCount:"Population count",observedCount:"Observed count",missingCount:"Missing count",missingPolicy:"Missing policy",complete:"Complete scope",status:"Status",reason:"Reason",kind:"Type",numerator:"Numerator",denominator:"Denominator",formula:"Formula",direction:"Direction",truth:"Result",claimId:"Claim",evaluationId:"Evaluation",objectType:"Object type",identityKeys:"Identity properties",grain:"Grain",perspective:"Perspective",aggregation:"Aggregation",additivity:"Additivity",releaseDigest:"Semantic release",hasMore:"More records",name:"Name",identity:"Object",target:"Target",mappingId:"Mapping",ruleId:"Rule",observedAt:"Observed at",sourceId:"Source",resource:"Table / API operation",semanticField:"Business property",physicalField:"Physical field / response path",role:"Role",sourceVersion:"Source version",queryDigest:"Query digest"};
const operationsEn: Record<string,string> = {ObjectType:"Object",Metric:"Metric",Link:"Relationship",Rule:"Rule",Policy:"Policy",Action:"Action",property:"Property",dimension:"Dimension",value:"Measure",identity:"Identity",SUM:"Total",AVG:"Average",MIN:"Minimum",MAX:"Maximum",COUNT:"Observed count",mean:"Average",sum:"Total",min:"Minimum",max:"Maximum",count:"Observed count",shareOfTotal:"Share of total",percentAboveMean:"Relative to mean",outperforms:"Outperforms peers",reject:"Reject missing values",exclude:"Exclude missing values",PRESENT:"Observed",MISSING:"Missing",UNKNOWN:"Unknown",ERROR:"Error"};

function labelMap(){ return currentLocale() === "en" ? labelsEn : labels; }
function operationMap(){ return currentLocale() === "en" ? operationsEn : operations; }

const typeLabels: Record<string, string> = {
  DECIMAL: "数值 (DECIMAL)",
  INTEGER: "整数 (INTEGER)",
  STRING: "文本 (STRING)",
  BOOLEAN: "布尔值 (BOOLEAN)",
  DATE: "日期 (DATE)",
  TIMESTAMP: "时间戳 (TIMESTAMP)",
};

const text=(value:any):string=>{const localLabels=labelMap();const localOperations=operationMap();const en=currentLocale()==="en";return value===null||value===undefined?"—":typeof value==="boolean"?(value?(en?"Yes":"是"):(en?"No":"否")):Array.isArray(value)?value.length===0?"—":value.map(text).join(en?", ":"、"):typeof value==="object"?Object.entries(value).filter(([,v])=>v!==null&&v!==undefined&&v!=="").map(([k,v])=>`${localLabels[k]??k}${en?": ":"："}${text(v)}`).join(en?"; ":"；")||"—":localOperations[String(value)]??String(value);};

function grainText(grain:any, names?:Record<string,string>):string{
  const localLabels = labelMap();
  const separator = currentLocale() === "en" ? ": " : "：";
  if(!grain||typeof grain!=="object") return text(grain);
  return Object.entries(grain).map(([key,value])=>{
    const shown=names?.[key];
    return shown?`${localLabels[key]??key}${separator}${shown} (${text(value)})`:`${localLabels[key]??key}${separator}${text(value)}`;
  }).join(currentLocale() === "en" ? "; " : "；")||"—";
}

function formatPerspectiveUnit(item: Record<string, any>): string {
  const en = currentLocale() === "en";
  const localOperations = operationMap();
  const parts: string[] = [];
  if (item.perspective && item.perspective !== "—") {
    parts.push(`${en ? "Perspective: " : "口径："}${localOperations[item.perspective] ?? item.perspective}`);
  }
  if (item.unit && item.unit !== "—") {
    parts.push(`${en ? "Unit: " : "单位："}${item.unit}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "—";
}

function Table({heads,rows}:{heads:string[];rows:ReactNode[][]}){
  return rows.length ? (
    <div className="evidence-table-wrap">
      <table>
        <thead><tr>{heads.map(h=><th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j}>{v}</td>)}</tr>)}</tbody>
      </table>
    </div>
  ) : null;
}

function Fields({value}:{value:Record<string,any>}){
  const entries = Object.entries(value).filter(([,v]) => {
    if (v === undefined || v === null || v === "") return false;
    if (Array.isArray(v) && v.length === 0) return false;
    return true;
  });
  const localLabels = labelMap();
  return <Table heads={currentLocale() === "en" ? ["Item","Value"] : ["项目","内容"]} rows={entries.map(([k,v])=>[localLabels[k]??k,text(v)])}/>;
}

function Records({items}:{items:Record<string,any>[]}){
  const keys=[...new Set(items.flatMap(item=>Object.keys(item)))];
  return <Table heads={keys.map(k=>labels[k]??k)} rows={items.map(item=>keys.map(k=>text(item[k])))}/>;
}

function Observations({items}:{items:any[]}){
  return <Table heads={["指标 / 对象","引擎值","状态 / 原因","来源映射","观测时间"]} rows={items.map(o=>{let value=o.value;if(o.valueType==="OBJECT"||typeof value==="string"&&value.startsWith("{")){try{value=JSON.parse(value);}catch{/* Preserve a plain source string. */}}return [o.target,<>{text(value)} {o.unit??""}</>,`${operations[o.kind]??o.kind}${o.reason?` · ${o.reason}`:""}`,text(o.mappingId??o.ruleId),text(o.observedAt)];})}/>;
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
            {operations[kind] ?? labels[kind] ?? kind}
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
            <h4 className="inspect-section-title">业务说明与作用</h4>
            {descText && <p className="inspect-desc">{descText}</p>}
            {effectText && effectText !== descText && (
              <div className="inspect-callout">
                <strong>业务执行效果：</strong>
                <span>{effectText}</span>
              </div>
            )}
            {(data.perspective || data.unit) && (
              <div className="inspect-tags-row">
                {data.perspective && (
                  <span className="inspect-tag">口径：{operations[data.perspective] ?? data.perspective}</span>
                )}
                {data.unit && (
                  <span className="inspect-tag">单位：{data.unit}</span>
                )}
              </div>
            )}
          </div>

          {/* 2. Target Object & Rules */}
          {(data.targetObject || (Array.isArray(data.preconditions) && data.preconditions.length > 0)) && (
            <div className="evidence-inspect-card">
              <h4 className="inspect-section-title">关联实体与规则约束</h4>
              {data.targetObject && (
                <div className="inspect-kv-row">
                  <span className="kv-label">关联业务对象</span>
                  <span className="kv-value">
                    <strong>{named(data.targetObject, catalog)}</strong>
                    <code>{data.targetObject}</code>
                  </span>
                </div>
              )}
              {Array.isArray(data.preconditions) && data.preconditions.length > 0 && (
                <div className="inspect-kv-row">
                  <span className="kv-label">前置核验规则</span>
                  <div className="kv-list">
                    {data.preconditions.map((p: string) => (
                      <div key={p} className="rule-chip">
                        <span className="rule-name">{named(p, catalog)}</span>
                        <code>{p}</code>
                        <span className="rule-badge">前置强制核验</span>
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
              <h4 className="inspect-section-title">输入参数定义 ({data.parameters.length})</h4>
              <Table
                heads={["参数名称", "业务含义", "数据类型", "必填要求"]}
                rows={data.parameters.map((p: any) => [
                  <code key="p-name">{p.name}</code>,
                  named(p.name, catalog, p.label ?? "—"),
                  <span key="p-type" className="evidence-type-badge">{typeLabels[p.valueType] ?? p.valueType ?? p.type ?? "STRING"}</span>,
                  p.required ? <span key="p-req" className="badge-required">必填</span> : <span key="p-opt" className="badge-optional">选填</span>
                ])}
              />
            </div>
          )}

          {/* 4. Source Provenance (追溯来源) */}
          <div className="evidence-inspect-card source-lineage-card">
            <h4 className="inspect-section-title">数据来源与物理追溯</h4>
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
                      <span className="prop-label">对应接口操作：</span>
                      <code>{s.operation}</code>
                    </div>
                  )}
                  {s.idempotent !== undefined && (
                    <div className="source-flags">
                      {s.idempotent && <span className="flag-tag">幂等执行保障 (Idempotent)</span>}
                      {s.reconcilable && <span className="flag-tag">支持对账与补偿 (Reconcilable)</span>}
                    </div>
                  )}
                  {Array.isArray(s.fields) && s.fields.length > 0 && (
                    <div className="source-fields-table">
                      <Table
                        heads={["业务字段", "物理字段 / 响应路径", "字段用途"]}
                        rows={s.fields.map((f: any) => [
                          <strong key="sf">{named(f.semanticField, catalog)}</strong>,
                          <code key="pf">{f.physicalField}</code>,
                          <span key="role" className="role-tag">{operations[f.role] ?? labels[f.role] ?? f.role}</span>
                        ])}
                      />
                    </div>
                  )}
                </div>
              ))
            ) : (
              <p className="inspect-note">
                当前版本定义通过统一语义协议解析，尚未绑定直接物理数据库表，或当前登录身份未开通底层物理映射查看权限。
              </p>
            )}
          </div>

          {/* 5. Technical Metadata (Collapsed) */}
          <details className="evidence-inspect-tech">
            <summary>底层架构与版本规格（技术参考）</summary>
            <Fields value={{
              "语义版本": data.version,
              "接口规范版本": data.apiVersion,
              "语义指纹摘要": data.releaseDigest,
              "命名空间": data.namespace,
            }} />
          </details>
        </div>
    </Modal>
  );
}

export function EvidenceCard({evidence}:{evidence:Evidence}){
  const { locale } = useI18n();
  const names = locale === "en" ? namesEn : namesZh;
  const [inspectItem, setInspectItem] = useState<InspectData | null>(null);
  const d=evidence.result;const claim=d.claim&&typeof d.claim==="object"?d.claim:null;
  const catalog = collectCatalog(evidence);
  const skip=new Set(["observations","checks","sourceActivities","objects","members","candidates","definitions","claim","comparison","comparisonRequest","values","evidence","mappingFields","scope","labels"]);
  const comparison = d.comparison ?? d.scope?.comparison;
  // Provenance is intentionally opt-in. Human answers stay focused on the
  // business conclusion; raw identifiers and physical mappings belong behind
  // this audit drawer and must never open by themselves.
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
          {d.definitions ? ` (${d.definitions.length} ${locale === "en" ? "definitions" : "项定义"})` : ""}
          {claim?` · ${claim.truth}`:""}
        </summary>
        {claim&&<><h4>{locale === "en" ? "Engine evaluation" : "引擎判断"}：{claim.truth}</h4><Fields value={claim}/></>}
        {d.values&&<Table heads={locale === "en" ? ["Metric","Operation","Grain","Engine value","Unit"] : ["指标","计算方式","粒度","引擎值","单位"]} rows={d.values.map((v:any)=>[v.metric,text(v.aggregation),grainText(v.grain,v.labels),text(v.value),v.unit])}/>}
        {d.evidence?.rows&&<Table heads={(d.evidence.columns??[]).map((c:any)=>c.label??c.id)} rows={d.evidence.rows}/>}
        {d.mappingFields&&<Table heads={["映射","来源","表","列"]} rows={d.mappingFields.map((m:any)=>[m.mappingId,m.sourceId,m.table,(m.columns??[]).join(", ")])}/>}
        {d.scope&&typeof d.scope==="object"&&<Fields value={Object.fromEntries(Object.entries(d.scope).filter(([k])=>k!=="comparison"))}/>}
        {d.observations&&<Observations items={d.observations}/>}
        {d.objects&&<Records items={d.objects.map((o:any)=>({...o.identity,...o.properties}))}/>}
        {d.members&&<><h4>{locale === "en" ? "Per-item calculation" : "逐项计算依据"}</h4><Table heads={locale === "en" ? ["Object identity","Statistical unit","Engine value","Unit","Status","Sample"] : ["对象身份","统计单位","引擎值","单位","状态","样本信息"]} rows={d.members.map((m:any)=>[text(m.identity),text(m.properties?.[d.statisticalUnit]),text(m.observation.value),m.observation.unit,m.observation.kind,<button key="m-inspect" type="button" className="evidence-inspect-btn" onClick={()=>setInspectItem({title:`${text(m.identity)} · ${locale === "en" ? "Properties" : "属性详情"}`, data:m.properties})}>{locale === "en" ? "View properties" : "查看属性"}</button>])}/></>}
        {comparison&&<><h4>{locale === "en" ? "Comparison" : "比较结果"}</h4><Fields value={comparison}/><Fields value={d.comparisonRequest??{}}/></>}
        {d.checks?.map((c:any,i:number)=><section key={i}><h4>自动规则校验：{c.claim?.truth??"未完成"}</h4><Fields value={c.claim??{claimId:c.claimId,reason:c.error}}/>{c.observations&&<Observations items={c.observations}/>}</section>)}
        {d.definitions&&<>
          <p className="evidence-note">{locale === "en" ? "These definitions come from the current ontology release; they do not prove that source records exist or are available." : "以下是当前版本声明的业务模型，不代表来源数据已存在或可用。"}</p>
          <Table
            heads={["类型","名称 / 标识","口径 / 单位","业务说明","定义详情"]}
            rows={d.definitions.map((item:any)=>[
              text(item.kind),
              <div key="id" className="evidence-entity-id">
                <strong>{item.label ?? named(item.id, catalog)}</strong>
                <br/>
                <code>{item.id}</code>
              </div>,
              formatPerspectiveUnit(item),
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
                {locale === "en" ? "View definition" : "查看定义"}
              </button>
            ])}
          />
          {d.hasMore&&<p className="evidence-note">{locale === "en" ? "More definitions are available." : "还有未展示的定义。"}</p>}
        </>}
        {d.candidates&&d.candidates.map((c:any)=><details key={c.id}><summary>{c.label??c.id}</summary><Fields value={c}/></details>)}
        <details><summary>{locale === "en" ? "Business definitions and calculation scope" : "业务定义与统计口径"}</summary><Fields value={Object.fromEntries(Object.entries(d).filter(([k])=>!skip.has(k)))}/></details>
        {!!evidence.lineage?.length&&<><h4>实际访问来源 · 表与字段映射</h4><p className="evidence-note">这些映射来自本次执行所固定的版本；字段列表说明映射定义，并非每列均参与当前计算。</p>{evidence.lineage.map(m=><section key={m.id}><Fields value={{"数据源":m.sourceId,"表 / API 操作":m.resource,"映射编号":m.id}}/><Table heads={["业务字段","物理字段 / 响应路径","用途"]} rows={m.fields.map((f:any)=>[f.semanticField,f.physicalField,f.role])}/></section>)}</>}
        {d.sourceActivities?.length>0&&<details><summary>读取活动与时间（{d.sourceActivities.length}）</summary><Table heads={["数据源","映射","观测时间","来源版本","查询摘要"]} rows={d.sourceActivities.map((a:any)=>[a.sourceId,a.mappingId,text(a.observedAt),text(a.sourceVersion),a.queryDigest])}/></details>}
        {!evidence.lineage?.length&&d.sourceActivities?.length>0&&<p className="evidence-note">该证据未附物理映射快照，或当前身份没有模型查看权限。上表保留实际来源引用。</p>}
      </details>
      {inspectItem && <EvidenceModal item={inspectItem} lineage={evidence.lineage} catalog={catalog} onClose={() => setInspectItem(null)} />}
    </>
  );
}

import { useState, type ReactNode } from "react";

export type Evidence = { id: string; tool: string; result: Record<string, any>; lineage?: Record<string, any>[] };
const names: Record<string, string> = {list_semantics:"当前业务模型目录",search_semantics:"业务定义候选",describe_semantic:"业务口径",find_objects:"对象与样本",semantic_query:"指标与事实",evaluate_claim:"规则判断",analyze_population:"集合统计",prepare_semantic_query:"语义分析"};
const labels: Record<string,string> = {metric:"指标",label:"名称",description:"业务说明",value:"引擎值",unit:"单位",operation:"计算方式",year:"年度",statisticalUnit:"统计单位",populationDescription:"样本范围",populationCount:"范围内数量",observedCount:"有效数量",missingCount:"缺失数量",missingPolicy:"缺失处理",complete:"范围读取完整",status:"状态",reason:"原因",kind:"类型",numerator:"分子",denominator:"分母",formula:"计算公式",direction:"比较方向",decimalPrecision:"十进制精度",consistency:"一致性",truth:"判断",claimId:"命题",evaluationId:"执行编号",predicateVersion:"规则版本",reasonCodes:"判断原因",objectType:"对象类型",identityKeys:"身份字段",grain:"指标粒度",perspective:"口径",aggregation:"来源聚合",derivedFrom:"依赖指标",releaseDigest:"语义版本",hasMore:"还有未读取对象",requiresSelection:"需要选择对象",companyId:"企业编号",companyName:"企业名称",name:"名称",identity:"对象",target:"目标",mappingId:"映射编号",ruleId:"规则编号",observedAt:"观测时间",sourceId:"数据源",resource:"表 / API 操作",semanticField:"业务字段",physicalField:"物理字段 / 响应路径",role:"用途",sourceVersion:"来源版本",queryDigest:"查询摘要",analysisCapabilities:"分析能力",pointLookup:"对象点查",keyedFind:"按业务键查找",collectionJoin:"跨表集合 JOIN",sameTableCollection:"同表集合分析"};
const operations:Record<string,string>={ObjectType:"对象",Metric:"指标",Link:"业务关系",Rule:"规则",Policy:"业务政策",Action:"业务操作",SUM:"合计",AVG:"平均值",MIN:"最小值",MAX:"最大值",COUNT:"有效观测数量",SOURCE_REPEATABLE_READ:"同源只读一致快照",mean:"算术平均",sum:"合计",min:"最小值",max:"最大值",count:"有效观测数量",shareOfTotal:"占总体总额",percentAboveMean:"相对均值增幅",outperforms:"严格超过同行比例",reject:"存在缺失则不计算",exclude:"明确排除缺失",BOUNDED_SEQUENTIAL_READS_NOT_GLOBAL_SNAPSHOT:"有界逐次读取，非全局数据库快照",WAREHOUSE:"仓库口径",FINANCIAL:"财务口径"};

const businessLabels: Record<string, string> = {
  // Actions
  "procurement.CreatePurchaseDraft": "创建采购草稿",
  "tax.CreateTaxAdjustmentDraft": "创建纳税调整草稿",
  // Rules
  "procurement.amountWithinLimit": "采购金额未超授权",
  "tax.incomeReconciles": "申报纳税收入与审计收入核对一致",
  "tax.revenueComplete": "纳税申报收入完整性校验",
  "tax.roundedTaxableIncome": "应纳税所得额取整规则",
  "tax.vatPresent": "增值税申报存在性校验",
  // Policies
  "procurement.amountWithinLimitOrgA": "组织A采购限额适用策略",
  "tax.incomeReconcilesY2024": "2024年度纳税收入核对策略",
  "tax.incomeReconcilesY2025": "2025年度纳税收入核对策略",
  // Objects
  "procurement.Order": "采购订单",
  "procurement.Organization": "采购组织",
  "procurement.Supplier": "供应商",
  "tax.Taxpayer": "纳税人 (企业主体)",
  "tax.Filing": "纳税申报记录",
  // Metrics
  "procurement.orderAmount": "采购订单金额",
  "procurement.approvalLimit": "组织审批授权限额",
  "procurement.orderQuantity": "采购订单数量",
  "tax.reportedIncome": "申报纳税收入",
  "tax.auditIncome": "税务审计核查收入",
  "tax.operatingRevenue": "营业收入",
  "tax.otherRevenue": "其他业务收入",
  "tax.vatPayable": "应纳增值税额",
  "tax.adjustmentAmount": "纳税调整金额",
  "inventory.stock": "库存数量",
  // Parameters & Properties
  "amount": "金额",
  "note": "备注说明",
  "taxYear": "纳税年度",
  "supplierId": "供应商编号",
  "orderId": "订单编号",
  "organizationId": "采购组织编号",
  "deliveryRisk": "交货履约风险",
  "status": "业务状态",
  "quantity": "数量",
  "jurisdiction": "管辖税务机关 / 属地",
  // Sources
  "orders_pg": "采购主数据库 (orders_pg · PostgreSQL)",
  "suppliers_pg": "供应商数据库 (suppliers_pg · PostgreSQL)",
  "proc_draft_api": "采购协同开放接口 (proc_draft_api · OpenAPI)",
  "tax_pg": "税务征管数据库 (tax_pg · PostgreSQL)",
  "tax_draft_api": "税务草稿开放接口 (tax_draft_api · OpenAPI)",
  "warehouse_db": "仓储系统数据库 (warehouse_db · PostgreSQL)",
  // Physical tables
  "proc_order": "采购订单事实表 (proc_order)",
  "proc_organization": "采购组织维度表 (proc_organization)",
  "proc_supplier": "供应商主数据表 (proc_supplier)",
  "tax_taxpayer": "纳税人主体表 (tax_taxpayer)",
  "tax_metric": "纳税申报度量表 (tax_metric)",
};

const effectTranslations: Record<string, string> = {
  "Create a purchase draft in the synthetic order system": "在采购业务系统中生成采购草稿，经授权额度核验后可转为正式采购订单",
  "Create a tax adjustment draft in the synthetic filing system": "在税务征管系统中生成纳税申报调整草稿，用于审计差额比对修正",
};

function translateEffect(effect: string): string {
  if (!effect) return "";
  if (effectTranslations[effect]) return effectTranslations[effect];
  const lower = effect.toLowerCase();
  if (lower.includes("purchase") && lower.includes("draft")) {
    return "在采购业务系统中生成采购草稿单据，经授权额度核验后可转为正式采购订单";
  }
  if (lower.includes("tax") && lower.includes("adjustment")) {
    return "在税务征管系统中生成纳税申报调整草稿，用于审计差额比对修正";
  }
  return effect;
}

const typeLabels: Record<string, string> = {
  DECIMAL: "数值 (DECIMAL)",
  INTEGER: "整数 (INTEGER)",
  STRING: "文本 (STRING)",
  BOOLEAN: "布尔值 (BOOLEAN)",
  DATE: "日期 (DATE)",
  TIMESTAMP: "时间戳 (TIMESTAMP)",
};

const text=(value:any):string=>value===null||value===undefined?"—":typeof value==="boolean"?(value?"是":"否"):Array.isArray(value)?value.length===0?"—":value.map(text).join("、"):typeof value==="object"?Object.entries(value).filter(([,v])=>v!==null&&v!==undefined&&v!=="").map(([k,v])=>`${labels[k]??k}：${text(v)}`).join("；")||"—":operations[String(value)]??String(value);

function grainText(grain:any, names?:Record<string,string>):string{
  if(!grain||typeof grain!=="object") return text(grain);
  return Object.entries(grain).map(([key,value])=>{
    const shown=names?.[key];
    return shown?`${labels[key]??key}：${shown}（${text(value)}）`:`${labels[key]??key}：${text(value)}`;
  }).join("；")||"—";
}

function formatPerspectiveUnit(item: Record<string, any>): string {
  const parts: string[] = [];
  if (item.perspective && item.perspective !== "—") {
    parts.push(`口径：${operations[item.perspective] ?? item.perspective}`);
  }
  if (item.unit && item.unit !== "—") {
    parts.push(`单位：${item.unit}`);
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
  return <Table heads={["项目","内容"]} rows={entries.map(([k,v])=>[labels[k]??k,text(v)])}/>;
}

function Records({items}:{items:Record<string,any>[]}){
  const keys=[...new Set(items.flatMap(item=>Object.keys(item)))];
  return <Table heads={keys.map(k=>labels[k]??k)} rows={items.map(item=>keys.map(k=>text(item[k])))}/>;
}

function Observations({items}:{items:any[]}){
  return <Table heads={["指标 / 对象","引擎值","状态 / 原因","来源映射","观测时间"]} rows={items.map(o=>{let value=o.value;if(o.valueType==="OBJECT"||typeof value==="string"&&value.startsWith("{")){try{value=JSON.parse(value);}catch{/* Preserve a plain source string. */}}return [o.target,<>{text(value)} {o.unit??""}</>,`${o.kind}${o.reason?` · ${o.reason}`:""}`,text(o.mappingId??o.ruleId),text(o.observedAt)];})}/>;
}

type InspectData = {
  title: string;
  kind?: string;
  data: Record<string, any>;
};

function EvidenceModal({
  item,
  lineage,
  onClose,
}: {
  item: InspectData;
  lineage?: Record<string, any>[];
  onClose: () => void;
}) {
  const data = item.data;
  const kind = data.kind ?? item.kind;
  const humanLabel = data.label ?? businessLabels[data.id] ?? labels[data.id] ?? data.id;
  const effectText = data.effect ? translateEffect(data.effect) : null;
  const descText = data.description ?? effectText ?? null;

  // Find sources either on data itself or from evidence lineage
  const sources: any[] = Array.isArray(data.sources) && data.sources.length > 0
    ? data.sources
    : (lineage ?? []).filter((m: any) => m.target === data.id || m.objectType === data.id);

  return (
    <div className="evidence-modal-backdrop" onClick={onClose}>
      <div className="evidence-modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="evidence-modal-header">
          <div className="evidence-modal-title-group">
            {kind && (
              <span className={`evidence-modal-badge kind-${String(kind).toLowerCase()}`}>
                {operations[kind] ?? labels[kind] ?? kind}
              </span>
            )}
            <div>
              <h3 className="evidence-modal-title">{humanLabel}</h3>
              <code className="evidence-modal-id">{data.id}</code>
            </div>
          </div>
          <button type="button" className="evidence-modal-close" onClick={onClose} aria-label="关闭">✕</button>
        </div>

        <div className="evidence-modal-body">
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
                    <strong>{businessLabels[data.targetObject] ?? data.targetObject}</strong>
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
                        <span className="rule-name">{businessLabels[p] ?? p}</span>
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
                  businessLabels[p.name] ?? labels[p.name] ?? "—",
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
                      <strong>{businessLabels[s.sourceId] ?? s.sourceId}</strong>
                    </div>
                    {s.resource && <code className="source-resource">{businessLabels[s.resource] ?? s.resource}</code>}
                  </div>
                  {s.operation && (
                    <div className="source-prop">
                      <span className="prop-label">对应接口操作：</span>
                      <code>{s.operation}</code>
                    </div>
                  )}
                  {s.idempotent !== undefined && (
                    <div className="source-flags">
                      {s.idempotent && <span className="flag-tag">✓ 幂等执行保障 (Idempotent)</span>}
                      {s.reconcilable && <span className="flag-tag">✓ 支持对账与补偿 (Reconcilable)</span>}
                    </div>
                  )}
                  {Array.isArray(s.fields) && s.fields.length > 0 && (
                    <div className="source-fields-table">
                      <Table
                        heads={["业务字段", "物理字段 / 响应路径", "字段用途"]}
                        rows={s.fields.map((f: any) => [
                          <strong key="sf">{businessLabels[f.semanticField] ?? labels[f.semanticField] ?? f.semanticField}</strong>,
                          <code key="pf">{f.physicalField}</code>,
                          <span key="role" className="role-tag">{labels[f.role] ?? f.role}</span>
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
      </div>
    </div>
  );
}

export function EvidenceCard({evidence}:{evidence:Evidence}){
  const [inspectItem, setInspectItem] = useState<InspectData | null>(null);
  const d=evidence.result;const claim=d.claim&&typeof d.claim==="object"?d.claim:null;
  const skip=new Set(["observations","checks","sourceActivities","objects","members","candidates","definitions","claim","comparison","comparisonRequest","values","evidence","mappingFields","scope"]);
  const defaultOpen = Boolean(!d.definitions && (claim||d.observations||d.members||d.objects||d.values||d.evidence?.rows||d.kind==="PopulationAnalysis"));
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <>
      <details
        className={`evidence-card${d.definitions ? " ontology-catalog" : ""}`}
        open={isOpen}
        onToggle={(e) => setIsOpen(e.currentTarget.open)}
      >
        <summary>
          {evidence.id} · {names[evidence.tool]??evidence.tool}
          {d.definitions ? ` (${d.definitions.length} 项定义)` : ""}
          {claim?` · ${claim.truth}`:""}
        </summary>
        {claim&&<><h4>引擎判断：{claim.truth}</h4><Fields value={claim}/></>}
        {d.kind==="PopulationAnalysis"&&<><h4>{d.label}：{d.value??"未计算"} {d.unit}</h4><p className="evidence-note">完整指上述筛选范围读取完整，不代表全行业或全部原始报告。</p></>}
        {d.values&&<Table heads={["指标","计算方式","粒度","引擎值","单位"]} rows={d.values.map((v:any)=>[v.metric,text(v.aggregation),grainText(v.grain,v.labels),text(v.value),v.unit])}/>}
        {d.evidence?.rows&&<Table heads={(d.evidence.columns??[]).map((c:any)=>c.label??c.id)} rows={d.evidence.rows}/>}
        {d.mappingFields&&<Table heads={["映射","来源","表","列"]} rows={d.mappingFields.map((m:any)=>[m.mappingId,m.sourceId,m.table,(m.columns??[]).join(", ")])}/>}
        {d.scope&&typeof d.scope==="object"&&<Fields value={d.scope}/>}
        {d.observations&&<Observations items={d.observations}/>}
        {d.objects&&<Records items={d.objects.map((o:any)=>({...o.identity,...o.properties}))}/>}
        {d.members&&<><h4>逐项计算依据</h4><Table heads={["对象身份","统计单位","引擎值","单位","状态","样本信息"]} rows={d.members.map((m:any)=>[text(m.identity),text(m.properties?.[d.statisticalUnit]),text(m.observation.value),m.observation.unit,m.observation.kind,<button key="m-inspect" type="button" className="evidence-inspect-btn" onClick={()=>setInspectItem({title:`${text(m.identity)} · 属性详情`, data:m.properties})}>查看属性</button>])}/></>}
        {d.comparison&&<><h4>比较结果</h4><Fields value={d.comparison}/><Fields value={d.comparisonRequest??{}}/></>}
        {d.checks?.map((c:any,i:number)=><section key={i}><h4>自动规则校验：{c.claim?.truth??"未完成"}</h4><Fields value={c.claim??{claimId:c.claimId,reason:c.error}}/>{c.observations&&<Observations items={c.observations}/>}</section>)}
        {d.definitions&&<>
          <p className="evidence-note">以下是当前版本声明的业务模型，不代表来源数据已存在或可用。</p>
          <Table
            heads={["类型","名称 / 标识","口径 / 单位","业务说明","定义详情"]}
            rows={d.definitions.map((item:any)=>[
              text(item.kind),
              <div key="id" className="evidence-entity-id">
                <strong>{item.label ?? businessLabels[item.id] ?? item.id}</strong>
                <br/>
                <code>{item.id}</code>
              </div>,
              formatPerspectiveUnit(item),
              item.description ?? (item.effect ? translateEffect(item.effect) : "—"),
              <button
                key="inspect"
                type="button"
                className="evidence-inspect-btn"
                onClick={() => setInspectItem({
                  title: item.label ?? businessLabels[item.id] ?? item.id,
                  kind: item.kind,
                  data: item
                })}
              >
                查看定义
              </button>
            ])}
          />
          {d.hasMore&&<p className="evidence-note">还有未展示的定义。</p>}
        </>}
        {d.candidates&&d.candidates.map((c:any)=><details key={c.id}><summary>{c.label??c.id}</summary><Fields value={c}/></details>)}
        <details><summary>业务定义与统计口径</summary><Fields value={Object.fromEntries(Object.entries(d).filter(([k])=>!skip.has(k)))}/></details>
        {!!evidence.lineage?.length&&<><h4>实际访问来源 · 表与字段映射</h4><p className="evidence-note">这些映射来自本次执行所固定的版本；字段列表说明映射定义，并非每列均参与当前计算。</p>{evidence.lineage.map(m=><section key={m.id}><Fields value={{"数据源":m.sourceId,"表 / API 操作":m.resource,"映射编号":m.id}}/><Table heads={["业务字段","物理字段 / 响应路径","用途"]} rows={m.fields.map((f:any)=>[f.semanticField,f.physicalField,f.role])}/></section>)}</>}
        {d.sourceActivities?.length>0&&<details><summary>读取活动与时间（{d.sourceActivities.length}）</summary><Table heads={["数据源","映射","观测时间","来源版本","查询摘要"]} rows={d.sourceActivities.map((a:any)=>[a.sourceId,a.mappingId,text(a.observedAt),text(a.sourceVersion),a.queryDigest])}/></details>}
        {!evidence.lineage?.length&&d.sourceActivities?.length>0&&<p className="evidence-note">该证据未附物理映射快照，或当前身份没有模型查看权限。上表保留实际来源引用。</p>}
      </details>
      {inspectItem && <EvidenceModal item={inspectItem} lineage={evidence.lineage} onClose={() => setInspectItem(null)} />}
    </>
  );
}



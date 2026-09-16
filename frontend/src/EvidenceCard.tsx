import type { ReactNode } from "react";

export type Evidence = { id: string; tool: string; result: Record<string, any>; lineage?: Record<string, any>[] };
const names: Record<string, string> = {list_semantics:"当前业务模型目录",search_semantics:"业务定义候选",describe_semantic:"业务口径",find_objects:"对象与样本",semantic_query:"指标与事实",evaluate_claim:"规则判断",analyze_population:"集合统计",prepare_semantic_query:"语义分析"};
const labels: Record<string,string> = {metric:"指标",label:"名称",description:"业务说明",value:"引擎值",unit:"单位",operation:"计算方式",year:"年度",statisticalUnit:"统计单位",populationDescription:"样本范围",populationCount:"范围内数量",observedCount:"有效数量",missingCount:"缺失数量",missingPolicy:"缺失处理",complete:"范围读取完整",status:"状态",reason:"原因",kind:"类型",numerator:"分子",denominator:"分母",formula:"计算公式",direction:"比较方向",decimalPrecision:"十进制精度",consistency:"一致性",truth:"判断",claimId:"命题",evaluationId:"执行编号",predicateVersion:"规则版本",reasonCodes:"判断原因",objectType:"对象类型",identityKeys:"身份字段",grain:"指标粒度",perspective:"口径",aggregation:"来源聚合",derivedFrom:"依赖指标",releaseDigest:"语义版本",hasMore:"还有未读取对象",requiresSelection:"需要选择对象",companyId:"企业编号",companyName:"企业名称",name:"名称",identity:"对象"};
const operations:Record<string,string>={ObjectType:"对象",Metric:"指标",Link:"业务关系",Rule:"规则",Policy:"业务政策",Action:"业务操作",SUM:"合计",AVG:"平均值",MIN:"最小值",MAX:"最大值",COUNT:"有效观测数量",SOURCE_REPEATABLE_READ:"同源只读一致快照",mean:"算术平均",sum:"合计",min:"最小值",max:"最大值",count:"有效观测数量",shareOfTotal:"占总体总额",percentAboveMean:"相对均值增幅",outperforms:"严格超过同行比例",reject:"存在缺失则不计算",exclude:"明确排除缺失",BOUNDED_SEQUENTIAL_READS_NOT_GLOBAL_SNAPSHOT:"有界逐次读取，非全局数据库快照"};
const text=(value:any):string=>value===null||value===undefined?"—":typeof value==="boolean"?(value?"是":"否"):Array.isArray(value)?value.map(text).join("、"):typeof value==="object"?Object.entries(value).map(([k,v])=>`${labels[k]??k}：${text(v)}`).join("；"):operations[String(value)]??String(value);
function grainText(grain:any, names?:Record<string,string>):string{
  if(!grain||typeof grain!=="object") return text(grain);
  return Object.entries(grain).map(([key,value])=>{
    const shown=names?.[key];
    return shown?`${labels[key]??key}：${shown}（${text(value)}）`:`${labels[key]??key}：${text(value)}`;
  }).join("；")||"—";
}
function Table({heads,rows}:{heads:string[];rows:ReactNode[][]}){return rows.length?<div className="evidence-table-wrap"><table><thead><tr>{heads.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j}>{v}</td>)}</tr>)}</tbody></table></div>:null;}
function Fields({value}:{value:Record<string,any>}){return <Table heads={["项目","内容"]} rows={Object.entries(value).filter(([,v])=>v!==undefined).map(([k,v])=>[labels[k]??k,text(v)])}/>;}
function Records({items}:{items:Record<string,any>[]}){const keys=[...new Set(items.flatMap(item=>Object.keys(item)))];return <Table heads={keys.map(k=>labels[k]??k)} rows={items.map(item=>keys.map(k=>text(item[k])))}/>;}
function Observations({items}:{items:any[]}){return <Table heads={["指标 / 对象","引擎值","状态 / 原因","来源映射","观测时间"]} rows={items.map(o=>{let value=o.value;if(o.valueType==="OBJECT"||typeof value==="string"&&value.startsWith("{")){try{value=JSON.parse(value);}catch{/* Preserve a plain source string. */}}return [o.target,<>{text(value)} {o.unit??""}</>,`${o.kind}${o.reason?` · ${o.reason}`:""}`,text(o.mappingId??o.ruleId),text(o.observedAt)];})}/>;}
export function EvidenceCard({evidence}:{evidence:Evidence}){
 const d=evidence.result;const claim=d.claim&&typeof d.claim==="object"?d.claim:null;
 const skip=new Set(["observations","checks","sourceActivities","objects","members","candidates","definitions","claim","comparison","comparisonRequest","values","evidence","mappingFields","scope"]);
 return <details className={`evidence-card${d.definitions ? " ontology-catalog" : ""}`} open={Boolean(d.definitions||claim||d.observations||d.members||d.objects||d.values||d.evidence?.rows||d.kind==="PopulationAnalysis")}>
  <summary>{evidence.id} · {names[evidence.tool]??evidence.tool}{claim?` · ${claim.truth}`:""}</summary>
  {claim&&<><h4>引擎判断：{claim.truth}</h4><Fields value={claim}/></>}
  {d.kind==="PopulationAnalysis"&&<><h4>{d.label}：{d.value??"未计算"} {d.unit}</h4><p>完整指上述筛选范围读取完整，不代表全行业或全部原始报告。</p></>}
  {d.values&&<Table heads={["指标","计算方式","粒度","引擎值","单位"]} rows={d.values.map((v:any)=>[v.metric,text(v.aggregation),grainText(v.grain,v.labels),text(v.value),v.unit])}/>}
  {d.evidence?.rows&&<Table heads={(d.evidence.columns??[]).map((c:any)=>c.label??c.id)} rows={d.evidence.rows}/>}
  {d.mappingFields&&<Table heads={["映射","来源","表","列"]} rows={d.mappingFields.map((m:any)=>[m.mappingId,m.sourceId,m.table,(m.columns??[]).join(", ")])}/>}
  {d.scope&&typeof d.scope==="object"&&<Fields value={d.scope}/>}
  {d.observations&&<Observations items={d.observations}/>}
  {d.objects&&<Records items={d.objects.map((o:any)=>({...o.identity,...o.properties}))}/>}
  {d.members&&<><h4>逐项计算依据</h4><Table heads={["对象身份","统计单位","引擎值","单位","状态","样本信息"]} rows={d.members.map((m:any)=>[text(m.identity),text(m.properties?.[d.statisticalUnit]),text(m.observation.value),m.observation.unit,m.observation.kind,<details><summary>查看属性</summary><Fields value={m.properties}/></details>])}/></>}
  {d.comparison&&<><h4>比较结果</h4><Fields value={d.comparison}/><Fields value={d.comparisonRequest??{}}/></>}
  {d.checks?.map((c:any,i:number)=><section key={i}><h4>自动规则校验：{c.claim?.truth??"未完成"}</h4><Fields value={c.claim??{claimId:c.claimId,reason:c.error}}/>{c.observations&&<Observations items={c.observations}/>}</section>)}
  {d.definitions&&<><p>以下是当前版本声明的业务模型，不代表来源数据已存在或可用。</p><Table heads={["类型","名称 / 标识","口径 / 单位","业务说明","定义详情"]} rows={d.definitions.map((item:any)=>[text(item.kind),<>{item.label??item.id}<br/><code>{item.id}</code></>,text({perspective:item.perspective??"—",unit:item.unit??"—"}),item.description??"—",<details><summary>查看字段与定义</summary><Fields value={item}/></details>])}/>{d.hasMore&&<p>还有未展示的定义。</p>}</>}
  {d.candidates&&d.candidates.map((c:any)=><details key={c.id}><summary>{c.label??c.id}</summary><Fields value={c}/></details>)}
  <details><summary>业务定义与统计口径</summary><Fields value={Object.fromEntries(Object.entries(d).filter(([k])=>!skip.has(k)))}/></details>
  {!!evidence.lineage?.length&&<><h4>实际访问来源 · 表与字段映射</h4><p>这些映射来自本次执行所固定的版本；字段列表说明映射定义，并非每列均参与当前计算。</p>{evidence.lineage.map(m=><section key={m.id}><Fields value={{"数据源":m.sourceId,"表 / API 操作":m.resource,"映射编号":m.id}}/><Table heads={["业务字段","物理字段 / 响应路径","用途"]} rows={m.fields.map((f:any)=>[f.semanticField,f.physicalField,f.role])}/></section>)}</>}
  {d.sourceActivities?.length>0&&<details><summary>读取活动与时间（{d.sourceActivities.length}）</summary><Table heads={["数据源","映射","观测时间","来源版本","查询摘要"]} rows={d.sourceActivities.map((a:any)=>[a.sourceId,a.mappingId,text(a.observedAt),text(a.sourceVersion),a.queryDigest])}/></details>}
  {!evidence.lineage?.length&&d.sourceActivities?.length>0&&<p className="evidence-note">该证据未附物理映射快照，或当前身份没有模型查看权限。上表保留实际来源引用。</p>}
 </details>;
}

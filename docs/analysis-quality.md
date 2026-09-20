# 可核验的业务分析与独立验收

## 现在是什么，尚未是什么

SemaLoom 已按业务本体方式建模：ObjectType/Property/Identity/Link 表达业务结构，Metric/Grain/Perspective 表达计量口径，Rule/Claim 表达确定性判断，Mapping 连接物理来源，Release 固定定义版本。它是业务语义层，不是 OWL 推理器；画出关系图本身也不证明取数正确。

按 [Palantir 官方 Ontology 概述](https://www.palantir.com/docs/foundry/ontology/overview)，其本体把对象、属性、关系和操作与分析及业务应用连接起来。我们采用了相近的建模方向，但不等于具有它的平台完整性。[官方对象集合接口](https://www.palantir.com/docs/foundry/functions/api-object-sets) 支持过滤和聚合；[对象后端说明](https://www.palantir.com/docs/foundry/object-backend/overview) 描述了搜索、过滤、聚合所依托的服务。下面是结合本项目代码做的判断，不是对 Palantir 产品的基准测试。

| 能力 | SemaLoom 当前情况 | 判断 |
|---|---|---|
| 业务对象、关系、指标、来源绑定 | 已有版本化定义与运行接口 | 本体方向成立 |
| 精确数值、三值规则、来源引用 | 可运行，并有独立对照测试 | 可验证具体问题，不承诺原始报告真实性 |
| 对象集合分析 | 本轮增加受控年度统计、分母及逐项证据 | 明确受限能力，不能当作无限查询平台 |
| 大规模集合、任意分组、窗口函数、跨来源统一快照 | 尚未实现 | 不能声称与成熟平台齐全 |
| 动作、治理、生产身份、协作与部署 | 存在原型及未关闭 gate | 不能声称生产平台等价 |

## 自然语言如何准确落到执行

`用户问题 → pi 调用 prepare_semantic_query → 确定年份/口径/统计单位/筛选范围 → 同一 SemanticQuery prepare/execute → 服务器事实和来源表格 → 引擎结果说明（集合统计）`。HTTP 为 `POST /v0.1/semantic/prepare` 与 execute，没有第二条分析入口。

模型不提交 SQL。对于已经能表达的语义查询，SQL 是 adapter 的执行实现；尚不能表达的问题应澄清或报未支持，不通过自由 text-to-SQL 绕开租户、粒度与口径。**已声明 ONE、单键 PostgreSQL Link 可用于按关联属性分组/筛选**；同源下推 JOIN，跨源有界按键对齐。一对多、复合键或多跳请求应得到明确 UNSUPPORTED，而不是静默改写。新增常见分析算子应该扩展同一受控请求及执行器，而非给每个自然语言问题写专用接口。

| 问法 | 必须确定的含义 | 当前执行 |
|---|---|---|
| 2025 年利润平均值 | 哪个利润、哪些对象、是否排除缺失 | `aggregation=AVG`，默认拒绝缺失 |
| 某企业占总额多少 | 同口径、同年度、同筛选集合 | `shareOfTotal`：企业值 / 集合合计 |
| 某企业比平均高多少 | 相对均值增幅，均值必须为正 | `percentAboveMean` |
| 某企业超过多少同行 | 越大越好还是越小越好 | `outperforms`：严格胜出同行 / 全部有效同行；排除自身，并列只进入分母 |
| 占优百分之多少 | 上述三者无法区分 | 应先澄清，不能猜分母 |

Metric 必须显式声明 `population`，包括统计单位属性、年度属性和范围说明。示例 financial-review 的 ReviewCase 指标声明按 companyId/taxYear 统计；重复企业年度直接失败，不随便取第一条，也不按报告份数平均。示例与测试使用合成数据；接入方应独立复核实际来源数据；即使读取完整，也不代表全国/全行业/全部正式申报。

当前限制（以 [能力边界](capabilities.md) 为准）：同源同事实表上的类型化过滤与聚合、已声明 ONE 同源 Link 的关联属性分组/筛选、分组预算（单请求最多 8 指标 / 8 分组键 / 1000 结果分组）、证据明细每指标最多 50 行分页。一对多展开、跨库 SQL JOIN、窗口函数、任意用户 SQL、集合分析复合 Link、多指标联合排序/比较未支持并返回明确能力错误。点查与声明式 Link 遍历保留完整结构化身份。来源单次超时仍由 adapter 控制。多次取数明确标记为非全局快照（同请求同源分析共用只读快照除外）。来源错误/重复 grain/单位错误不作为可排除的缺失；NULL/MISSING 只有显式 `missingPolicy=exclude` 才排除，并公布数量。

`complete` 仅指筛选对象枚举完整。结果可能因为缺失或空集合而没有数值；不能把 complete 解读为数据已复核。比例为零分母、负数总额占比、非正均值等情况返回具体原因。Decimal 运算精度 28 位，页面保留结果字符串，不经 JS 浮点重新计算。

## 证据和图谱

证据卡用表格展示引擎值、单位、观察状态、对象身份、样本属性、统计数量、分子分母和计算公式。来源表格显示本次访问的 Mapping 所绑定的数据源、表/API operation、语义字段和物理列/响应路径。映射定义与当前实际读取活动分别标明；不把全部映射列伪称为全部参加计算。物理映射从固定 release 生成，仅保存在浏览器展示记录，不进入模型工具上下文；普通 analyst 不返回物理映射。既有 Studio modeler/model-viewer/source-admin 权限可查看它；历史记录仍按当前角色过滤。

图谱使用现有 React Flow 的曲线和 [官方标签层](https://reactflow.dev/api-reference/components/edge-label-renderer)，标签避让节点及已放置标签；密集图仍应拖动/筛选，不承诺任意大图零重叠。画布工具栏支持就地新建实体、点击两实体建立关系、自动整理和适应画布；定义保存沿用现有草稿流程，图坐标不改变发布模型。

## 可复现的测试层次

1. `tests/test_population.py`：真实隔离 PostgreSQL，独立 SQL 对照五类统计；精确比较分子分母、并列、负值、零分母、缺失、重复单位、超限、年份、权限及元数据边界；REST 与 Chat IPC 使用同一引擎。
2. `tests/test_chat.py` + `harness/test/plugin.test.mjs`：进程 IPC、持久化、取消、来源证据，以及官方 pi Agent 原生 hook。离线 provider 测试不会证明真实模型理解率。
3. `frontend/tests/chat.spec.ts` + `frontend/tests/studio.spec.ts`：浏览器交互、元数据表格、无 JSON、图谱工具与原有保存/校验/发布回归。
4. `ops/ai/evaluate_chat.py`：受限真实模型问答，对照直接 `/v0.1/semantic/prepare` + execute 的结果、范围、版本、数量及分母。每次最多 20 个问题，必须明确 `--max-calls`。报告不输出业务数值或秘密。它校验事实卡与澄清类型，不能证明每句解释或用户意图都正确；仍需要独立 agent 审查文本是否扩大范围、改变分母或夸大合规结论。

真实评测 case 文件结构（普通开发者可使用合成环境；本机样本评测文件留 `.agents/`）：

```json
[
  {"id":"mean-2025","question":"当前样本中2025年的选定申报利润平均值是多少？缺失不要排除。","query":{"apiVersion":"semaloom/v0.1","metrics":[{"id":"finance.review.declared_profit","aggregation":"AVG"}],"filters":{"field":"taxYear","op":"EQ","value":{"valueType":"INTEGER","value":2025}}}},
  {"id":"ambiguous","question":"某企业占优百分之多少？未指定指标与范围。","kind":"clarification"}
]
```

```sh
uv run python ops/ai/evaluate_chat.py --cases .agents/analysis-quality/live-cases.json --output .agents/analysis-quality/live-report.md --max-calls 2
```

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

`用户问题 → pi 调用 prepare_semantic_query → 确定年份/口径/统计单位/筛选范围 → 同一 SemanticQuery prepare/execute → 服务器事实和来源表格 → 引擎结果说明（集合统计）`。REST `analyze_population` 只翻译到该链。

模型不提交 SQL。对于已经能表达的语义查询，SQL 是 adapter 的执行实现；尚不能表达的问题应澄清或报未支持，不通过自由 text-to-SQL 绕开租户、粒度与口径。新增常见分析算子应该扩展同一受控请求及执行器，而非给每个自然语言问题写专用接口。

| 问法 | 必须确定的含义 | 当前执行 |
|---|---|---|
| 2025 年利润平均值 | 哪个利润、哪些对象、是否排除缺失 | `operation=mean`，默认拒绝缺失 |
| 某企业占总额多少 | 同口径、同年度、同筛选集合 | `shareOfTotal`：企业值 / 集合合计 |
| 某企业比平均高多少 | 相对均值增幅，均值必须为正 | `percentAboveMean` |
| 某企业超过多少同行 | 越大越好还是越小越好 | `outperforms`：严格胜出同行 / 全部有效同行；排除自身，并列只进入分母 |
| 占优百分之多少 | 上述三者无法区分 | 应先澄清，不能猜分母 |

Metric 必须显式声明 `population`，包括统计单位属性、年度属性和范围说明。本轮 financial-review 的 ReviewCase 指标声明按 companyId/taxYear 统计；重复企业年度直接失败，不随便取第一条，也不按报告份数平均。数据仍是选定的本地样本；即使读取完整，也不代表全国/全行业/全部正式申报。

当前限制：精确相等的属性筛选、单一可搜索对象 Mapping、单一统计单位/年度、最多 50 个完整成员、10 秒调度预算。超过 50 个返回 `POPULATION_TOO_LARGE_REFINE_FILTERS`，不计算截断样本总数；来源单次超时仍由 adapter 控制。多次取数明确标记为非全局快照。暂不支持任意 group-by、加权平均、滚动窗口、跨年度复合粒度或无界 SQL 下推。来源错误/重复 grain/单位错误不作为可排除的缺失；NULL/MISSING 只有显式 `missingPolicy=exclude` 才排除，并公布数量。

`complete` 仅指筛选对象枚举完整。结果可能因为缺失或空集合而没有数值；不能把 complete 解读为数据已复核。比例为零分母、负数总额占比、非正均值等情况返回具体原因。Decimal 运算精度 28 位，页面保留结果字符串，不经 JS 浮点重新计算。

## 证据和图谱

证据卡用表格展示引擎值、单位、观察状态、对象身份、样本属性、统计数量、分子分母和计算公式。来源表格显示本次访问的 Mapping 所绑定的数据源、表/API operation、语义字段和物理列/响应路径。映射定义与当前实际读取活动分别标明；不把全部映射列伪称为全部参加计算。物理映射从固定 release 生成，仅保存在浏览器展示记录，不进入模型工具上下文；普通 analyst 不返回物理映射。既有 Studio modeler/model-viewer/source-admin 权限可查看它；历史记录仍按当前角色过滤。

图谱使用现有 React Flow 的曲线和 [官方标签层](https://reactflow.dev/api-reference/components/edge-label-renderer)，标签避让节点及已放置标签；密集图仍应拖动/筛选，不承诺任意大图零重叠。画布工具栏支持就地新建实体、点击两实体建立关系、自动整理和适应画布；定义保存沿用现有草稿流程，图坐标不改变发布模型。

## 可复现的测试层次

1. `tests/test_population.py`：真实隔离 PostgreSQL，独立 SQL 对照五类统计；精确比较分子分母、并列、负值、零分母、缺失、重复单位、超限、年份、权限及元数据边界；REST 与 Chat IPC 使用同一引擎。
2. `tests/test_chat.py` + `harness/test/plugin.test.mjs`：进程 IPC、持久化、取消、来源证据，以及官方 pi Agent 原生 hook。离线 provider 测试不会证明真实模型理解率。
3. `frontend/tests/chat.spec.ts` + `frontend/tests/studio.spec.ts`：浏览器交互、元数据表格、无 JSON、图谱工具与原有保存/校验/发布回归。
4. `ops/ai/evaluate_chat.py`：受限真实模型问答，对照直接 `/v0.1/analyze` 的结果、范围、版本、数量及分母。每次最多 20 个问题，必须明确 `--max-calls`。报告不输出业务数值或秘密。它校验事实卡与澄清类型，不能证明每句解释或用户意图都正确；仍需要独立 agent 审查文本是否扩大范围、改变分母或夸大合规结论。

真实评测 case 文件结构（普通开发者可使用合成环境；本机样本评测文件留 `.agents/`）：

```json
[
  {"id":"mean-2025","question":"当前样本中2025年的选定申报利润平均值是多少？缺失不要排除。","population":{"metric":"finance.review.declared_profit","year":2025}},
  {"id":"ambiguous","question":"某企业占优百分之多少？未指定指标与范围。","kind":"clarification"}
]
```

```sh
uv run python ops/ai/evaluate_chat.py --cases .agents/analysis-quality/live-cases.json --output .agents/analysis-quality/live-report.md --max-calls 2
```

## 分派给独立 Agent 的 goal 提示词

每个 agent 新建自己的 `.agents/<task>/` 和临时测试目录，先读 AGENTS.md、本文、semantic contract、acceptance。禁止 reset 本地样本库、修改共享运行实例的发布指针、打印秘密和把真实数据提交 Git。默认不修实现；报告最小复现交回主 agent，避免并行修改同一文件。数据库测试必须用隔离 PostgreSQL，清楚记录连接的端口和库名（不记录密码）。

### A — 数值和范围独立验收

> Goal：证明对象集合分析的结果正确且范围不被扩大。审查 runtime/population.py、核心契约与 financial-review 定义，在自己的隔离库构造至少 30 个金问题，使用独立 SQL 或 Decimal 手工期望计算，不调用被测函数生成期望。覆盖 2024/2025 混合、跨租户同键、重复企业年度、零/负数/并列、单企业、空集合、缺失、全部缺失、50/51 对象、不同口径、派生指标、精度边界和来源错误。逐例核对值、单位、数量、分母、完整性和来源活动。发现有错值仍返回成功视为最高优先级。输出通过/失败/未覆盖矩阵和可运行复现测试，不把限制项改成成功。

### B — 真实 AI 意图与解释验收

> Goal：验证自然语言是否正确选择本体口径与统计接口。先做离线检查，然后在现有授权 provider 上最多调用 12 次，不循环重试。围绕明确均值、含糊“收入”、总额占比、相对均值、超过同行、未指定“占优”、不存在企业和缺失等场景，给相同意图至少两种说法。可用 ops/ai/evaluate_chat.py 对照事实卡；另外独立检查文本每个数字、年份、对象范围、分母和结论，不能只看回答流畅。不得认为 SQL 对照一致就证明意图正确。记录模型、prompt/代码版本、完整分母、失败工具码和延迟；业务内容仅保留脱敏证据。未澄清就猜口径、将样本说成行业、将 TRUE 说成审计认可均记失败。

### C — Hooks、身份与来源链验收

> Goal：在离线模型及隔离元数据库验收 HTTP → Chat → pi → semantic tools → Runtime → Provider → 证据持久化 → 页面数据的边界。测试伪造对象身份、工具结果和 evidenceId、SQL/URL/角色注入、发布中途切换、取消、超时、并发、跨主体历史和当前权限撤销。检查物理表列只从实际 Mapping 引用生成、不会进入模型上下文、普通 analyst/降权后不能读取已有 lineage；模拟元数据库保存失败，不能给成功完成。输出每个环节的可复现结果。既有 JWT/MCP gate 单列，不混为这轮功能通过。

### D — 图谱与证据页面验收

> Goal：按真实用户路径验收图谱与 Chat。检查 1280/1440、小屏和 200% 缩放；长中文标签、平行边、拖动后标签、筛选、工具栏新建实体后保存重载、点击起终点连线、取消连线、整理和适应画布。证据必须能直接读到表、字段、单位、状态及分母，无需阅读 JSON；核对页面没有把 Rule 定义当 Claim 执行。使用合成接口或隔离测试服务，不污染用户样本/草稿。提交截图及最小复现；没有执行的负载场景明确列未验证。

验收报告统一包含：代码状态/环境、用例 ID、输入口径、独立期望、实际结果、通过/失败/未执行、证据路径、优先级。必须把真实模型理解、确定性计算、源数据可靠性分开评分，不能合并成一个虚假的“100% 准确率”。

## 本轮执行结果（2026-09-14 独立 A–D 验收）

以下记录是修复前的独立审计基线，审计时实现代码未改。后续实现与复测见 [审计修复](audit-fixes.md)。四个独立 agent 按上文 A–D 提示词在隔离 PostgreSQL / 隔离端口跑完。问题清单（按 P0/P1/P2，三层分开计分）见仓库内 `.agents/analysis-quality-audit/issues.md`。

| 层 | 结果 | 不要合并 |
|---|---|---|
| 确定性计算 | A：60 金问题 PASS（独立 SQL/Decimal，含 HTTP `/v0.1/analyze`）。C：14 边界 PASS；保存失败不报成功。提交 `tests/test_analysis_quality_gold.py` 9 项对照通过 | 不是「分析 100% 准确」 |
| 真实模型意图/解释 | 离线 prompt/schema PASS。Live qwen3.7-plus 10 次：引擎卡 5 PASS / 5 FAIL；散文/意图 **4 PASS / 6 FAIL** | 引擎卡一致 ≠ 意图正确 |
| 源数据可靠性 | 本轮只用发明值隔离库，未读用户 `semaloom_samples` | 未评估原始报告真实性 |

P0（均在 live 意图，非算错仍成功）：含糊「收入」未澄清；shareOfTotal / outperforms 无合法回答；percentAboveMean 对 mean 卡心算。P1：用户禁止排除缺失仍走 `exclude`；390 宽图谱画布空白；边标签叠加工具栏。JWT（A58）与原生 MCP 仍 NOT_RUN。大图 50+ 节点 NOT_RUN。

旁证（不关闭独立覆盖）：`tests/test_population.py` 23、`tests/test_chat.py` 6、harness 3、隔离 Studio 上 `frontend/tests/*.spec.ts` 19。

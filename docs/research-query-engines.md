# 语义查询与 SQL 编译开源项目调研

调研日期：2026-09-14。本文是 MetricFlow、SQLGlot、Ibis 三者范围内的备选研究，只核查了项目自己的仓库、源码和文档，不按 GitHub stars 判断成熟度，也没有安装依赖或访问业务数据。综合架构决策以 [semantic-query-design.md](semantic-query-design.md) 为准；当前总体顺序是优先验证 Wren 可嵌入 planner。本文提出的 `SemanticQuery -> RelationalPlan` 是接口和验收目标，不把先编写自研关系执行器当作既定决策。重点是回答一个架构问题：企业只配置业务本体和来源绑定后，core 能否用同一套逻辑回答新的聚合、筛选、分组和比较问题。

## 结论

SemaLoom 不应该为“平均值”“占比”“排名”等每种问法各写一个企业特判。可复用边界应是一个受约束的关系查询代数：本体配置提供指标、实体、维度、粒度、关系和口径；AI 只把自然语言解析为带语义 ID 的查询；通用 planner 再把查询编译成带参数的 SQL。这样新增企业主要增加配置和绑定，不增加 core 分支。

三个项目的职责不同：MetricFlow 最接近语义指标 planner，SQLGlot 是 SQL AST/方言/血缘工具，Ibis 是可移植的 Python dataframe 表达式层。它们都不能直接替代 SemaLoom 的授权、来源故障语义、Evidence 或领域本体。

在这三者范围内，建议保留 SemaLoom 已有的 SQLAlchemy Core、adapter 和 Evidence 边界：先定义通用 `SemanticQuery` 契约并验证 Wren 可嵌入 planner，再决定采用第三方 planner 的适配层还是实现最小自有计划层。SQLGlot 可作为 SQL 生成后的限定、类型检查和血缘辅助；MetricFlow 只做隔离的兼容性实验；暂不把 Ibis 变成 core 必选依赖。无论选择哪种 planner，都要先通过 Decimal、NULL/UNKNOWN、粒度和 join 放大、参数化及 Evidence 的对照测试。

## 项目能力与适配判断

| 项目 | 官方资料确认的能力 | 对 SemaLoom 的可复用部分 | 不能直接承担的部分 |
| --- | --- | --- | --- |
| [dbt MetricFlow](https://github.com/dbt-labs/metricflow) | 以 semantic model、entity、dimension、measure/metric 描述业务测量；支持简单、派生、比率和累计指标，并将请求编译为 dataflow plan 和方言 SQL。 | 指标/实体/维度/时间粒度的对象划分；按请求动态选择维度和 join path；以“输出粒度”解释结果。 | 当前项目要求工作中的 dbt project 和 dbt adapter；仓库将自身描述为 query compilation/rendering library，且 PyPI 项目标记为 Beta。它不是 SemaLoom 的授权、跨来源组合、证据或 Action 生命周期。 |
| [SQLGlot](https://github.com/tobymao/sqlglot) | 无依赖的 SQL parser、transpiler、optimizer 和实验性 engine；支持多方言。optimizer 可 qualify、类型标注、谓词/投影处理，lineage 可追踪列来源。 | 对已生成 SQL 做 AST 级 allowlist 检查、表列限定、类型/方言检查、规范化和列血缘；辅助生成 Evidence 的物理来源摘要。 | 官方 FAQ 明确 parser 有意保持宽松，SQLGlot 是 transpiler 而不是 validator；optimizer 主要是逻辑优化，也不拥有业务指标、实体基数、grain 或权限语义。不能让模型直接提交 SQL。 |
| [Ibis](https://github.com/ibis-project/ibis) | 提供惰性、可组合的 Python 表达式，编译到多个 SQL/DataFrame backend；表达式覆盖 filter、join、aggregate、window、order/limit 等。 | 作为一个可选的关系表达式后端编译实验；借鉴其“一套表达式、多 backend”接口。 | 表达式从物理 table/schema 和列开始，不提供企业本体目录、业务指标认证、关系基数、授权范围或 Evidence；其 `table.sql(...)` 也不能成为 SemaLoom 的请求入口。它不能作为与被测引擎共享实现的独立 oracle。 |

### MetricFlow：最接近，但不要整套搬进 core

MetricFlow 的官方语义文档把 metric 定义成“在一个 scope 上计算的命名值”。scope 由 metric 自身定义、查询过滤器、group-by 和时间约束共同决定；没有 group-by 时返回整个过滤集合的一行，按时间或维度分组时返回各组的值。[Metric semantics](https://github.com/dbt-labs/dbt-core/blob/main/crates/dbt-metricflow/docs/metric-semantics.md) 给出了 `revenue`、`order_count`、derived、ratio 和 cumulative 的完整 SQL 示例。

它把 entity 当作连接 semantic model 的 join key，把 dimension 当作改变输出粒度的切片；官方 dbt 文档还区分了 primary、foreign、unique、natural entity，并要求模型能确定 primary entity。[Semantic models](https://docs.getdbt.com/docs/build/semantic-models) 和 [MetricFlow semantic model proposal](https://github.com/dbt-labs/dbt-core/discussions/7456) 是这套设计的直接来源。MetricFlow 的发布记录也显示它会拒绝 ambiguous join path，而不是任意猜一条路径。[CHANGELOG](https://github.com/dbt-labs/metricflow/blob/main/CHANGELOG.md)

这正好说明 SemaLoom 缺少的通用能力不是更多意图正则，而是“语义查询 + 粒度感知的计划”。不过，MetricFlow 当前 README 明确写着它需要一个可工作的 dbt project 和 dbt adapter，`compile` 负责输出 SQL，执行由后续 SQL engine 完成。[MetricFlow README](https://github.com/dbt-labs/metricflow/blob/main/README.md) 当前 `pyproject.toml` 还将项目标为 Beta，并通过依赖文件带入 dbt 生态和 SQLGlot。[pyproject.toml](https://github.com/dbt-labs/metricflow/blob/main/pyproject.toml)

因此建议先写一个隔离的 `MetricFlowBridge` 兼容性实验，而不是让 core 依赖 dbt manifest、dbt adapter 或 MetricFlow 的内部对象。实验至少要证明：SemaLoom domain pack 能无损表达；不同 source binding 能生成同一语义结果；Decimal、NULL/UNKNOWN、缺失、权限过滤、join 基数和 evidence lineage 不被第三方计划抹平。实验没有通过前，不应声称已经复用了 MetricFlow planner。

还要锁定版本和许可证。当前 MetricFlow 仓库的 `LICENSE` 是 Apache-2.0，但其 README 记录了历史版本 0–0.140.0 为 AGPL、0.150.0–0.208.2 为 BSL、0.209.0 及以后为 Apache-2.0。[LICENSE](https://github.com/dbt-labs/metricflow/blob/main/LICENSE) [License history](https://github.com/dbt-labs/metricflow/blob/main/README.md#license-history) 若将来嵌入，必须明确 pin 到允许的版本并随发行物保留 NOTICE/许可证。

### SQLGlot：应当放在 SQL 边界

SQLGlot 的官方 onboarding 将流程拆成 tokenizer、parser、generator，并把 schema 作为 qualify、类型推断和 column-level lineage 的输入。[Onboarding](https://github.com/tobymao/sqlglot/blob/main/posts/onboarding.md) 其 optimizer 的默认规则包括 qualify、pushdown projections/predicates、join optimization、type annotation、canonicalize 和 simplify，但官方同时说明 optimizer 只做逻辑优化，物理 join reorder 留给执行层。[Optimizer source](https://github.com/tobymao/sqlglot/blob/main/sqlglot/optimizer/optimizer.py) [Python SQL engine notes](https://github.com/tobymao/sqlglot/blob/main/posts/python_sql_engine.md)

SQLGlot 对 SemaLoom 的正确位置是“计划之后、执行之前”：

1. 从已验证的 integration binding 生成 SQLAlchemy/内部 SQL，再解析成 AST；
2. 检查所有 table、column、function、dialect 是否来自绑定和 capability allowlist；
3. 用 schema 做 qualify/type annotation，得到稳定 SQL 和物理列血缘；
4. 交给只读 adapter 执行，并把计划摘要、SQL digest、表列映射放进 Evidence。

SQLGlot 自己不能证明 join 是业务上正确的，也不能证明解析成功的 SQL 一定能执行。官方 README 明确说明 parser 有意宽松，SQLGlot 是 transpiler 而不是 validator；方言转换在缺失信息时还可能需要 schema 和类型信息。[SQLGlot README](https://github.com/tobymao/sqlglot/blob/main/README.md) 所以必须保留数据库执行/预编译检查和 SemaLoom 的语义校验。

当前 SQLGlot `LICENSE` 是 MIT。[SQLGlot LICENSE](https://github.com/tobymao/sqlglot/blob/main/LICENSE)

### Ibis：可选的关系表达式，不是本体层

Ibis 官方 README 将自身定义为 portable Python dataframe library：表达式惰性求值，可以编译为 SQL，并在多个 backend 间复用。[Ibis README](https://github.com/ibis-project/ibis) 官方 SQL 教程展示了 `join`、`aggregate`、`group_by`、条件 aggregate、window、top-k 和 `limit` 等关系操作如何生成 SQL。[Ibis SQL tutorial](https://ibis-project.org/tutorials/coming-from/sql)

这对 SemaLoom 有两个启发：关系查询可以用一套组合式表达式描述，不需要为每个统计问法写一个函数；聚合和比较可以在 SQL 中一次完成，不依赖模型心算。限制同样清楚：Ibis 的输入是物理表及列，`join` 由调用者提供条件，它没有 SemaLoom 所需的 semantic ID、业务口径、授权 scope、来源版本和 Evidence。它更适合作为未来可选 backend 编译实验，而不是 core 的默认依赖。Ibis 与被测 planner/执行器共享关系实现时不能充当独立 oracle；正确性仍应由独立 SQL 和 Decimal 结果作为基准。

Ibis 当前仓库的 `LICENSE.txt` 是 Apache-2.0。[Ibis LICENSE](https://github.com/ibis-project/ibis/blob/main/LICENSE.txt)

## 对 SemaLoom 的通用设计

“只配置本体即可”需要把配置分成三类。它们都是声明式数据，不应让每个企业触发一段 Python 特判。

| 层 | 只声明什么 | 谁使用 |
| --- | --- | --- |
| Domain pack | ObjectType/Entity、稳定身份、Dimension、Measure、Metric 及公式、业务别名、时间维度、单位、允许聚合、默认缺失策略、Link 的业务基数和有效方向 | Semantic resolver、planner、规则和 Evidence |
| Integration binding | semantic source 到物理表/视图/列的映射、类型转换、方言、快照/分页/批量能力、来源版本 | SQL compiler 和 adapter |
| Core runtime | 语义查询 IR、粒度/基数校验、关系计划、参数绑定、预算、授权、Observation/UNKNOWN、Evidence | 所有领域和所有来源 |

本体只描述“收入”是什么、在哪个 semantic source、什么单位和粒度；它不应描述 PostgreSQL `SELECT` 字符串，也不应把某家企业的税率、表名或 API URL写进 core。反过来，只有 ObjectType 和标签也不够回答严肃统计问题，至少需要声明 metric 的 measure、aggregation、时间维度、dimension、join cardinality 和派生公式。

建议把现有受限请求逐步扩展为这样的中立查询对象：

```text
SemanticQuery
  metrics: [semantic metric ids]
  group_by: [semantic dimensions/entities + optional time grain]
  filters: [semantic dimension, typed operator, typed value]
  time_range: [business time]
  comparison: optional {operation, subject identity/filter, denominator scope}
  order_by / limit: bounded
```

planner 的内部节点可以保持很小：`Scan -> Filter -> Project -> Join -> Aggregate -> Window -> Sort -> Limit`。每个节点带有已知 `grain`、可见字段、来源活动和行数预算。`Metric` 只是这些节点的声明式入口；平均值、总额、占比、超过均值、top-k 都是同一套 Aggregate/Window/Join 组合。

### 必须由通用 planner 证明的正确性

- **粒度**：每个 measure 声明输入粒度，输出节点声明结果粒度。`average` 要明确是行平均、对象平均还是先按对象聚合后再平均。
- **join 基数**：每个 Link 声明 one-to-one、many-to-one 等方向。若 measure 所在侧接入一对多表，planner 必须先按 join key 聚合或拒绝，不能让 SQL join 放大金额。
- **分母**：占比、排名和“超过均值”需要独立的 denominator scope。主体筛选只能选择分母中的对象，不能把主体条件偷偷加到分母。
- **空值与缺失**：SQL `NULL`、没有行、来源故障和未授权结果必须映射到不同 Observation 状态；不能用 `COALESCE(..., 0)` 伪造事实。
- **时间**：年份和日期范围必须绑定 metric 的时间维度及粒度；跨来源年份相同不等于同一快照。
- **执行安全**：AI 只产生 semantic ID 和 typed value；表名、列名、join 条件、SQL 方言和 URL 都从已发布 binding 解析。SQL 必须参数化，并在执行前检查 allowlist、预算和只读能力。

例如“2025 年所有企业营业收入平均值”应被解析为 `metric=declared_revenue, year=2025, operation=mean`，然后由 planner 根据该 metric 的 population/grain 生成聚合 SQL；“某企业占总额百分比”应生成同一 metric、同一年度和同一过滤范围下的 subject numerator 与完整 denominator 两个子计划。回答中展示的表字段、实体键、join 路径、聚合口径和实际行数来自计划与 Evidence，模型只负责自然语言表达。

## 建议的落地顺序

1. 先在现有 SQLAlchemy Core 边界上抽出 `SemanticQuery` 契约，把 `analyze_population` 变成一个查询模板/算子，而不是唯一统计入口；同步做 Wren planner 的嵌入性验证，不预设先写完整自研关系执行器。
2. 在选定的 planner 适配边界上验证 grain、cardinality 和 denominator scope；用“多对多、重复键、空值、缺失、主体筛选误缩分母”的 fixture 做独立 SQL/Decimal oracle 测试。
3. 由 binding 生成参数化 SQL；先用现有 adapter 执行。可选加入 SQLGlot 做 AST 限定、schema qualification、方言检查和 lineage，不把它当业务 planner。
4. 用税务和采购两个领域各写一套纯配置，验证“换名称、表列和别名不改 core”，再增加一个完全不同粒度的领域验证泛化，而不是继续给财税用例加分支。
5. 另建 MetricFlow bridge spike，比较同一个 manifest/query 的 SQL、结果和 Evidence；只在 bridge 能保留 SemaLoom 语义且依赖/许可证可接受时考虑嵌入。Ibis 只作为可选 backend 编译实验，不作为与被测引擎共享实现的独立 oracle；正确性 oracle 继续使用独立 SQL/Decimal，不进入默认发行物。

## 验收标准

这条路线达到“通用”应以行为证明，而不是代码里出现了某个开源库为准：

- 新增一个 domain pack 只改 domain YAML 和 integration binding；core、planner、SQL adapter、Chat tool 不改；
- 同一 semantic query 在至少两个 SQL 方言或来源绑定上产生等价结果；
- 生成 SQL 中不存在模型提供的表名、列名、join 或 URL，所有值参数化；
- 任何无法证明粒度、唯一性、完整性、时间范围或分母的请求都返回可解释的拒绝/UNKNOWN；
- Evidence 能从 semantic metric 追到 measure、维度、Link、物理表列、执行版本和结果行，UI 以表格展示这些元数据；
- 查询结果由数据库/引擎计算，模型不能通过改写文字改变数值、分母或缺失策略。

以上标准比“支持更多自然语言模板”更能防止每新增一种问法就定向修复，同时保留了企业本体配置的灵活性。

# 指标应在哪一层：本体定义 vs 物理聚合

调研日期：2026-09-18。问题：指标是否应作为本体一级公民（跨 SQL 与 API 同一套配置），若把 AVG 等放在上层会否把明细拉进进程、浪费资源。本文只核查论文、官方文档与本仓库已落地代码；不安装第三方引擎、不访问业务数据。既有引擎选型见 [research-query-engines.md](research-query-engines.md)、[ADR-0011](adr/0011-semantic-query-planner.md)；作者面词条见 [ADR-0012](adr/0012-facts-and-business-vocabulary.md)。

## 结论

**指标定义必须留在本体；AVG 的物理执行必须下推或按代数合并，二者不是同一层。**

把「营业收入」写成 PostgreSQL `AVG(amount)` 或某个 REST path，会把本体绑死在一种协议上。把 AVG 做成「先把所有行拉进 Python 再算」则会浪费 IO 和内存，并破坏 Decimal 与缺失语义。权威系统都把这件事拆成三步：

1. **本体**：这个数叫什么、单位、粒度、沿哪些维可加。
2. **逻辑计划**：这次请求要 `AVG` 还是 `SUM`，按什么分组。
3. **接入**：SQL 下推 `SUM`/`COUNT`，或调用已按 grain 返回的 API，或在预算内合并**固定大小的中间量**（对 AVG 就是 `(sum, count)`），禁止拉全量明细。

SemaLoom 的 PostgreSQL 集合分析已经按第 3 步做了（`AVG` 编译为 `SUM` + `COUNT`，见 `src/semaloom/adapters/analysis.py`）。缺口是把同一套「可分解聚合」写成 Mapping 能力，而不是 Postgres 特判，从而使 OpenAPI 与跨源走同一逻辑 IR。

## 权威分类：什么能下推、什么必须上层收尾

### Gray / Chaudhuri：聚合函数三分法

Jim Gray、Surajit Chaudhuri 等，*Data Cube: A Relational Aggregation Operator Generalizing Group-By, Cross-Tab, and Sub-Totals*（Microsoft Research TR-95-22；期刊 Data Mining and Knowledge Discovery, 1997）。[MSR PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-22.pdf) [arXiv](https://arxiv.org/abs/cs/0701155)

| 类 | 定义 | 例子 | 跨分区怎么算 |
| --- | --- | --- | --- |
| Distributive（分配） | 先对子集算 F，再对部分结果用 G 合并 | `SUM` `COUNT` `MIN` `MAX` | 各源返回标量，Runtime 再 `G` |
| Algebraic（代数） | 子集可收成**固定长度**中间量，最后用 H 得到答案 | `AVG`、标准差 | AVG 的中间量是 `(sum, count)`；H 为相加后再除 |
| Holistic（整体） | 没有固定大小的中间量 | 中位数、众数、精确排名 | 不能按分区合并；来源算不了就应 `UNSUPPORTED` |

对「AVG 放上层会不会浪费」的直接回答：**逻辑 AVG 在上层是对的；物理 AVG 若扫全表则是错的。** 正确做法是各源只返回 `(sum, count)`，上层只做一次除法。论文原文：Average 的 G 记录子集的 sum 与 count，H 把两分量相加再相除。

### Kimball：可加性决定「允许哪些算子」

Ralph Kimball / Margy Ross，*The Data Warehouse Toolkit*；官方技法卡 [Additive, Semi-Additive, and Non-Additive Facts](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/additive-semi-additive-non-additive-fact/) 与 [2013 技法汇编 PDF](https://www.kimballgroup.com/wp-content/uploads/2013/08/2013.09-Kimball-Dimensional-Modeling-Techniques11.pdf)：

- **Fully additive**：销售额、数量，沿所有维可 SUM。
- **Semi-additive**：余额、库存，沿实体可 SUM，沿时间不可 SUM（两天的余额相加不是「两倍钱」）。
- **Non-additive**：比率。应保存可加的分子分母，**先聚合再相除**。Kimball 写明这最后一步常在 BI / OLAP 层做——正是「本体声明比率、执行层先 SUM 再除」，不是把比率写进 SQL 列。

本体应声明可加性；查询层按可加性拒绝非法 `SUM(余额 across 时间)`，而不是让 adapter 猜。

## 开源系统怎么分层

### Apache Calcite：逻辑 Aggregate vs 按 convention 下推

官方 [Adapters](https://calcite.apache.org/docs/adapter.html)：联邦查询时，计划树按 calling convention「着色」；planner 用规则把 Filter/Project/**Aggregate** 推进能执行它们的数据源。源不支持某算子则规则不触发，算子留在 Enumerable（本地）执行。成本决定是否下推。JDBC adapter 的 `JdbcAggregateRule` 仅在方言支持该聚合、且无非法 `DISTINCT`/`FILTER` 时把整个 GROUP BY 推到远端。[JdbcAggregateRule](https://calcite.apache.org/javadocAggregate/org/apache/calcite/adapter/jdbc/JdbcRules.JdbcAggregateRule.html)

这是跨 SQL/非 SQL 的标准答案：**同一套逻辑算子，每条 Mapping 声明自己能下推什么。**

### Substrait：把「分解阶段」写成协议

[Aggregate Functions](https://substrait.io/expressions/aggregate_functions/)：聚合可 `Decomposable = NONE | ONE | MANY`，绑定带 **Phase**：`INITIAL_TO_INTERMEDIATE` / `INTERMEDIATE_TO_INTERMEDIATE` / `INTERMEDIATE_TO_RESULT` / `INITIAL_TO_RESULT`。AVG 是 MANY/ONE：各 worker 出中间 struct，coordinator 做 `INTERMEDIATE_TO_RESULT`。不可分解函数只允许 `INITIAL_TO_RESULT`。

SemaLoom 若要跨 API+SQL 做 AVG，Mapping 能力应接近这套 phase，而不是一个布尔 `supportsAvg`。

### dbt MetricFlow：指标在语义模型，SQL 只是编译产物

[About MetricFlow](https://docs.getdbt.com/docs/build/about-metricflow)、[Creating metrics](https://docs.getdbt.com/docs/build/metrics-overview)：

- Simple metric：对一列做 `sum` / `count` / `average`（作者声明聚合，仓库生成 SQL）。
- Ratio：分子分母**分别聚合再相除**，避免「比率之和 ≠ 之和的比率」。
- Derived：对已有指标做表达式。
- 执行：`compile` 出方言 SQL，由 warehouse 跑，MetricFlow 自己不当执行引擎。

可借鉴：指标是命名语义对象；SQL 是 adapter 产物。不可直接搬：它要求可工作的 dbt project / SQL warehouse，不是 OpenAPI；本仓库已决定不把 MetricFlow 纳入发行物（ADR-0011）。

### Cube：度量在模型，查询走 REST；来源几乎必须是 SQL

[Measures](https://docs.cube.dev/reference/data-modeling/measures)：`type: sum | avg | count | number`，`sql` 只给**未聚合表达式**，Cube 生成 `GROUP BY`。[Queries](https://docs.cube.dev/product/apis-integrations/queries) 区分 regular（下推聚合 + 可用 pre-aggregation）、post-processing、pushdown（不过 GROUP BY）。[Pre-aggregations](https://docs.cube.dev/product/caching/using-pre-aggregations) 是物化的 aggregate awareness。

限制（对 SemaLoom 很关键）：官方 [Data sources](https://cube.dev/docs/product/configuration/data-sources) 写明 Cube **不是为 REST/GraphQL 取数设计的**；要用 API 数据必须先入支持 SQL 的库，或自写 driver。Cube 的 REST 是**对外查询 API**，不是来源协议。

### LookML：度量类型在模型，但 `sql:` 侵入物理层

[Measure types](https://cloud.google.com/looker/docs/reference/param-measure-types)：`type: sum | average` 决定生成 `SUM`/`AVG`；`sql:` 引用维度而非另一度量。Looker 禁止对度量再套 SUM/AVG（避免双重聚合），比率用 `type: number` 组合已聚合度量。这在 SQL 仓里正确，但 **measure 文档里写 SQL 片段**正是「本体侵入查询层」——SemaLoom 的 Agent 契约禁止请求携带 SQL，LookML 作者面也不该成为样板。

### Malloy：measure 是源上的命名聚合，编译期才变 SQL

[Aggregates](https://docs.malloydata.dev/documentation/language/aggregates)；编译两阶段见 [malloy CONTEXT](https://github.com/malloydata/malloy/blob/main/packages/malloy/CONTEXT.md)：解析到 IR，再按方言生成 SQL。强调 **aggregate locality**（在哪个 grain 上 SUM/AVG）和 symmetric aggregate，避免 JOIN 放大重复计数。仍是 SQL 后端语言，不是 API 联邦。

## 对「跨 API 和 SQL 配同一指标」意味着什么

主流 BI（Looker / Cube / MetricFlow / Malloy）**几乎都假设来源会 SQL**。联邦非 SQL 的权威模式是 Calcite adapter convention，而不是把 AVG 写进本体 YAML。

因此跨协议指标应是：

| 层 | 配置什么 | 不配置什么 |
| --- | --- | --- |
| Domain pack | Metric ID、单位、grain、口径、可加性、允许的查询算子、派生 Rule | 表名、`AVG()`、URL、JSON Pointer |
| Mapping | 目标 Metric/测量槽、provider、物理字段或 GET operation、**聚合能力**（能下推哪些 phase） | 业务别名、口径含义 |
| Adapter | 把逻辑 `Aggregate(AVG)` 编成 SQL 或 HTTP；返回 Observation 或 `(sum,count)` 中间量 | 行业公式 |

同一 `tax.operatingRevenue` 可以：

- PostgreSQL Mapping：`COLLECTION_READ` + `PUSH_AGGREGATE{SUM,COUNT,MIN,MAX}` → 集合 AVG 在库内完成。
- OpenAPI Mapping：接口已按纳税人+年度返回金额 → 能力只有 `POINT_READ`，查询 AVG 若 grain 已匹配则就是该点值；若请求跨多年平均，要么另绑一个统计 GET，要么对有界点查结果做代数合并（每年一个 `(sum,count)`，不是拉凭证明细）。
- 跨源：各 Mapping 返回中间量，Runtime 做 `INTERMEDIATE_TO_RESULT`；任一侧 holisitic 或无界列表 → `UNSUPPORTED`。

Cube 明确做不到第二种；SemaLoom 的独立接入层（ADR-0006）反而更接近 Calcite，而不是更接近 Cube。

## 与当前 SemaLoom 的对照

已对齐权威分层：

- ADR-0012：Metric 是查询面入口；作者面是测量槽 + 词条，合计是 Query 算子。
- ADR-0006：领域包不拥有表列/URL；adapter 编译物理计划。
- PostgreSQL 分析路径已把 AVG 写成 `SUM(col), COUNT(col)`，再在引擎侧相除（Gray 的 G/H）。
- OpenAPI `fetch_metric` 是 grain 点查，读 `valuePointer`，不做集合 AVG。
- 跨源集合 SQL 明确 `CROSS_SOURCE_SQL` / `UNSUPPORTED`（ADR-0011）。

尚未写成通用能力的：

- Mapping 没有 `PUSH_AGGREGATE` / 中间量类型；AVG 下推是 Postgres 分析器里的 if。
- 没有「API 已聚合」与「API 仅点查」的能力区分，除现有 `POINT_READ` / `COLLECTION_READ`。
- 没有跨 Mapping 的 `(sum, count)` 合并协议（Substrait phase）。
- 词条未强制 Kimball 可加性；`aggregation: NONE|SUM|MAX|MIN` 不够表达「沿时间不可 SUM」。

## 建议设计（不改发行物，除非另开 ADR）

保持「指标在本体、物理在接入」，把聚合从「Postgres 函数名」提升为**可分解逻辑算子**：

```text
SemanticQuery.metrics[].aggregation = AVG
        │
        ▼
Planner 按 Metric.additivity 与 Mapping.capabilities 选择：
  FULL + PUSH SUM/COUNT     → adapter 下推，返回 (sum, n) 或直接 AVG
  SEMI 沿非法维             → 拒绝或改为 LAST/声明的 snapshot 策略
  仅 POINT_READ 且 grain 已齐 → 一次点查，聚合是恒等
  多源均可出中间量          → 各源 INITIAL_TO_INTERMEDIATE，Runtime H()
  holistic / 无界 API 列表  → UNSUPPORTED，不扫明细
```

资源约束写成验收，而不是实现细节：集合分析的远程调用与返回行数仍受预算；AVG 的热路径**禁止**「先 SELECT 明细再 Python mean」。证据明细分页（现 50）继续与总体聚合分开。

派生指标继续用 Rule/`outputMetric`（比率先聚合再除），不要在本体穷举 SQL 公式。这与 MetricFlow ratio、Kimball non-additive、Looker `type: number` 一致，且不把 SQL 交给调用方。

若要冻结为架构决策，见已落地的 [ADR-0013](adr/0013-measure-additivity.md)（可加性 + 单查询链）。Mapping 聚合能力与跨源中间量 Observation 仍不在本切片。

# 通用语义模型到关系代数/SQL 的安全规划研究

调研日期：2026-09-21。范围：研究本体/领域语义如何安全地转换成关系代数、SQL 或其他来源协议；回答领域配置是否应承载 SQL 表达式、如何支持派生表达式/过滤/join/聚合/方言能力，以及 Jev 这类模型如何参与候选选择而不获得 SQL 注入能力。本文只修改文档，不改变实现。

本文使用规范、官方文档、官方源码和论文原文作为依据。被研究项目是参照物，不是 SemaLoom 的运行时依赖。

## 结论先行

### 1. raw SQL 不进入 domain ontology；受控 SQL 只能留在受审核的 integration mapping

领域包应该表达稳定的业务语义：语义对象/属性/指标、类型、粒度、链接、可用算子、派生表达式的**结构化 AST**以及可加性/缺失语义。它不应该表达表名、列名、方言函数、`WHERE` 片段、join 条件或可替换的 SQL 字符串。

接入绑定则拥有物理关系、列映射、来源协议和能力。若某个来源只能通过视图或静态查询暴露事实，可以在受信任、版本化的 provider-specific mapping 中保留源查询；这与调用方提交 SQL 是两种不同的信任边界。W3C R2RML 明确把 base table/view/SQL query 作为 logical table 的 mapping 输入，并用 term map 将行映射成目标语义三元组，[R2RML logical tables](https://www.w3.org/TR/r2rml/#logical-tables)、[R2RML term maps](https://www.w3.org/TR/r2rml/#term-maps)。Ontop 也把 source SQL 放在 mapping language 中，再将 source columns/templates 映射到 ontology target，[Ontop mapping language](https://ontop-vkg.org/guide/advanced/mapping-language.html)、[Ontop concepts](https://ontop-vkg.org/guide/concepts.html)。这证明“SQL 可以是受信任映射的实现细节”，不证明“SQL 应成为本体或请求语言”。

因此，明确的规则是：

| 位置 | 允许表达 | 明确禁止 |
| --- | --- | --- |
| domain ontology | semantic ID、类型、业务粒度、Link ID、聚合/可加性、有限 typed expression AST | 表/列、SQL 函数名、SQL 字符串、join 文本、动态占位符 |
| integration mapping | semantic field → physical column、来源关系、受审核 source query、方言能力和 capability | 未审核脚本、DML、调用方值拼接、绕过租户范围的表达式 |
| SemanticQuery 请求 | metric/field/link/function 的 semantic ID、typed literal、结构化 filter/group/aggregate | table/column、SQL/SQL AST、任意 join condition、任意函数名 |
| adapter/planner | 将逻辑算子选择性下推为参数化 SQL/API 请求 | 把模型输出当作可信计划或字符串模板直接执行 |

### 2. 核心路径应是“语义请求 → 逻辑关系代数 → 物理计划 → adapter”，而不是“自然语言 → SQL”

推荐的不可变链路如下：

```text
用户问题
  ↓
Jev/确定性解析：只选候选 semantic IDs
  ↓
SemanticQuery：typed values + Filter/Group/Aggregate/Link
  ↓ Compiler
LogicalPlan：Scan / Project / Filter / Join / Aggregate / Sort / Limit
  ↓ CapabilityPlanner
PhysicalPlan：mapping + provider capabilities + parameter slots + policy scope
  ↓ adapter
参数化 SQL、API 请求或有界的进程内组合
  ↓
typed observations + lineage/evidence
```

SPARQL 1.1 把 graph pattern 先翻译成 algebra，再定义 `Join`、`Filter`、`Project`、`Group`、`Union` 等运算的语义；这正是“语义层先固定逻辑算子，后选择物理执行”的可迁移原则，[SPARQL 1.1 translation to algebra](https://www.w3.org/TR/sparql11-query/#sparqlAlgebra)、[SPARQL filter and join semantics](https://www.w3.org/TR/sparql11-query/#sparqlAlgebra)。Apache Calcite 同样把查询表示成 relational operator tree，并由规则、代价和 convention 将 logical expression 变为物理实现，[Calcite algebra](https://calcite.apache.org/docs/algebra.html)、[Calcite adapters](https://calcite.apache.org/docs/adapter)。

### 3. 当前最小竖切应优先完成“typed Expr → logical expression → SQL lowering”，而不是先增加 `physical computed field`

两者不是互斥功能，但顺序应是：

1. 先把本体中的派生规则保持为受限、可类型检查的 `Expr`，在 Compiler 解析为 protocol-neutral logical expression；完成引用解析、类型、NULL/缺失、Decimal、可加性和跨来源拒绝。
2. 再由 PostgreSQL adapter 将该逻辑表达式 lowering 为 SQL AST/参数化 SQL，并由其他 adapter 明确报告 unsupported 或采用自己的表达式实现。
3. 最后才增加 integration 里的 `computed field`/预计算列绑定，作为物理优化或来源已算字段的替代实现；它不能改变 domain expression 的语义，也不能让调用方提交表达式。

理由是：派生指标是语义契约的一部分，必须在没有某个特定物理列时仍可验证、解释、迁移和在不同 provider 上拒绝；computed field 只是一个来源优化。当前 SemaLoom 已经有闭集 [Expr parser](../../src/semaloom/core/expr.py)、Compiler 的引用/类型检查（见 [`_check_rules`](../../src/semaloom/compiler/api.py)）以及 PostgreSQL 中“不解析配置 SQL 文本”的 lowering（见 [`_sql_expr_ast`](../../src/semaloom/adapters/analysis.py)）。因此最小增量是把现有 lowering 提升为明确的 LogicalPlan/Expression seam，并补齐能力拒绝和跨 provider 测试，而不是把 `physical.computedSql` 作为第一优先级。

## 一手项目得到的共同结构

### W3C R2RML / Ontop：mapping 可以有 source query，但它不是 ontology

R2RML 的 mapping 由 logical table、subject map、predicate-object map 等组成。logical table 可以来自数据库表、view 或 SQL query；`rr:column` 从行列取值，`rr:template` 只在受定义的模板位置插入列值，ref-object map 表达外键关系，[R2RML logical tables](https://www.w3.org/TR/r2rml/#logical-tables)、[R2RML column term map](https://www.w3.org/TR/r2rml/#from-a-column)、[R2RML template term map](https://www.w3.org/TR/r2rml/#from-a-template)、[R2RML referencing object map](https://www.w3.org/TR/r2rml/#foreign-key)。

这个分层有两个重要启发：

- 物理 source selector 和目标语义 term map 是两个对象；本体不需要知道 source column 的名字。
- 模板不是任意字符串替换。R2RML 规定 column/template 的解析、NULL 传播、term type 和有效列名；它不是给调用者的 SQL 拼接机制。

Ontop 的官方文档说明它接受 W3C R2RML 和自己的 mapping language，并把 SPARQL 翻译为在关系来源上执行的 SQL，[Ontop guide](https://ontop-vkg.org/guide/)。其 mapping 示例将 `source SELECT ...` 与 target template 分开；target literal 的类型需与 ontology 一致，动态 language tag 等未声明形式会被拒绝，[Ontop mapping language](https://ontop-vkg.org/guide/advanced/mapping-language.html)。

**适用于 SemaLoom 的结论**：可在部署方审核的 integration mapping 中保留静态 source query，但必须将它视为物理来源定义、独立校验和版本化发布；domain 只引用 semantic field/metric ID。R2RML/ Ontop 不应被简化为“在 YAML 中允许 `${column}`”。

### SPARQL：先定义可证明的逻辑算子

SPARQL 规范先将查询语法翻译为 algebra，再规定 graph pattern、join compatibility、filter effective boolean value、projection、grouping 和 aggregate 的语义，[SPARQL algebra](https://www.w3.org/TR/sparql11-query/#sparqlAlgebra)、[SPARQL aggregates](https://www.w3.org/TR/sparql11-query/#aggregates)。

对 SemaLoom 来说，这意味着：

- filter 是 `Predicate(fieldRef, operator, typedLiteral)`，而不是 `WHERE` 字符串；
- join 是已声明的 `LinkRef` 加 key pair/cardinality，而不是调用方 join condition；
- aggregate 是 `MetricRef + AggregateOp`，不是把 `SUM(...)` 放进本体；
- group/project 的输入和输出字段都必须来自编译后语义 schema。

### Apache Calcite：RelNode/RexNode 是可组合的 planner seam

Calcite 官方 algebra 文档把查询描述成 relational operator tree，`RelBuilder` 可以构造 `TableScan`、`Project`、`Filter`、`Aggregate`、`Join` 等节点，规则可以做 filter pushdown 等语义保持变换，[Calcite algebra](https://calcite.apache.org/docs/algebra.html)。Adapter 文档将逻辑算子与 adapter-specific physical implementation 分开，并允许 provider 只实现一个受限子集，[Calcite adapter rules](https://calcite.apache.org/docs/adapter)。

Calcite 的 `RexNode` 是有类型的 row expression，包含 field reference、literal、variable 和 call；它与尚未校验、缺乏类型信息的 SQL `SqlNode` 不同，[RexNode Javadoc](https://calcite.apache.org/javadocAggregate/org/apache/calcite/rex/RexNode.html)。`RelNode` 是关系表达式，不是 scalar expression，并携带用于物理选择的 trait/convention，[RelNode Javadoc](https://calcite.apache.org/javadocAggregate/org/apache/calcite/rel/RelNode.html)。

**可借鉴但不必引入 Calcite**：SemaLoom 需要同样的“logical vs physical、typed expression、capability/convention”边界；但根据 [ADR-0011](../adr/0011-semantic-query-planner.md)，当前发行物不应为了模仿 Calcite 而引入第二套查询后端。

### Volcano 论文：逻辑代数、物理代数、规则和代价是可替换边界

Graefe 与 McKenna 的 Volcano Optimizer Generator 论文把 data model、logical algebra、physical algebra、optimization rules、cost model 和 physical properties 作为可扩展的独立部分；规则由逻辑表达式转换为物理实现，优化器据此搜索低成本计划，[Volcano Optimizer Generator 原文](https://15721.courses.cs.cmu.edu/spring2023/papers/16-optimizer1/graefe-icde1993.pdf)、[IEEE DOI](https://doi.org/10.1109/ICDE.1993.344061)。Volcano 执行系统进一步强调算子统一接口和实现可替换性，[Volcano 执行系统论文](https://people.eecs.berkeley.edu/~prabal/teaching/resources/eecs582/graefe94volcano.pdf)。

对 SemaLoom 的直接启发是：把“是否能由某来源完成”放进 capability/planner seam，不要让 domain 或 Jev 了解 SQL 方言；将来优化器可以变强，但 semantic request 和 adapter contract 不需要改变。

### Substrait：函数必须有 typed signature 和扩展身份

Substrait 将 field reference、scalar/aggregate/window function、logical relation、extension 和 serialization 都纳入协议；扩展通过 URN、function anchor 和签名声明能力，[Substrait specification](https://substrait.io/spec/specification/)、[Substrait extensions](https://substrait.io/extensions/)、[Substrait scalar functions](https://substrait.io/expressions/scalar_functions/)。其函数声明还区分参数类型、返回类型、nullability、determinism 和 session dependence，[Substrait scalar function behavior](https://substrait.io/expressions/scalar_functions/)。

SemaLoom 不需要直接采用尚在演进的 Substrait wire format，但应采用同一个设计方向：本体和逻辑 IR 使用受控 `FunctionId` 与 typed signature；provider 报告是否支持该函数及其 lowering；未知函数不是“把名字拼进 SQL”，而是 `UNSUPPORTED`。

### dbt MetricFlow：结构化 semantic query 到 dataflow/SQL

MetricFlow 的官方文档将 semantic model、entities、dimensions、measures 和 metrics 分开；CLI/compiler 接受 semantic manifest 与结构化 query options，再生成 dataflow plan 和 warehouse-specific SQL，[MetricFlow repository](https://github.com/dbt-labs/metricflow)、[MetricFlow metric semantics](https://github.com/dbt-labs/dbt/blob/main/crates/dbt-metricflow/docs/metric-semantics.md)。`metric_time`、dimensions、entities、group-by 和 filters 都在 metric/query 语义中声明或选择，能够在同一 query 中复用来源和 grain。

MetricFlow 也展示了反例：`expr`、`where_sql_template` 等字段允许把 warehouse SQL 带入 semantic manifest。它们适合 dbt 自己控制的 warehouse-specific 项目，却会使语义随方言、数据库 schema 和安全约束漂移。SemaLoom 可以借鉴结构化 metric query、默认时间维度和 dataflow 分层，不应把 `where_sql_template` 当作公共领域抽象。

### Cube / Wren：结构化 query 有助于 agent，但 SQL expression 仍是物理耦合

Cube 的 dimension model 允许 `sql` expression/column，time dimension 通过类型和粒度查询，并支持 custom granularity 和 calendar cube，[Cube dimensions](https://docs.cube.dev/docs/data-modeling/dimensions)、[Cube calendar cubes](https://docs.cube.dev/docs/data-modeling/concepts/calendar-cubes)。这适合 SQL-first semantic layer；它的 `sql` 不是安全的 agent 输入，也不适合 API 来源或通用领域包。

Wren 的 MDL 将 cube、measure、dimension、time dimension 分开；CLI 以 cube、measure、dimension、`time-dimension name:granularity` 和 filters 的结构化参数查询，明确避免让 agent 手写 `GROUP BY`/`DATE_TRUNC`，[Wren MDL](https://docs.getwren.ai/oss/reference/mdl)、[Wren cube query](https://docs.getwren.ai/oss/reference/cli#query_cube)、[Wren cubes guide](https://docs.getwren.ai/oss/guides/cubes)。这是 SemaLoom 接入 Jev 的正确方向：模型选择语义候选，服务端重新验证；但 Wren 的 cube expression 仍应留在物理 SQL model 层。

## SemaLoom 当前基线与缺口

### 已有的正确边界

- [ADR-0006](../adr/0006-independent-integration-layer.md) 已规定 domain pack 拥有对象、身份、指标词汇、Link、规则与策略；integration 拥有 Mapping、物理列/API operation、协议与认证。Core/公共 Compiler 不解析 SQL/OpenAPI 专属字段。
- [ADR-0011](../adr/0011-semantic-query-planner.md) 明确公共入口是 `SemanticQuery`/`prepare`/`execute`，请求只有 semantic ID 和 typed value，不开放 semantic SQL/raw SQL。
- [ADR-0012](../adr/0012-facts-and-business-vocabulary.md) 将表事实与业务词条分开，SUM/AVG 等是查询算子，不是 YAML 中的 SQL 公式；[ADR-0013](../adr/0013-measure-additivity.md) 继续将可加性放在测量槽元数据。
- `SemanticQuery` 已有 typed `FilterAtom`/`FilterGroup`、metric、group、order、aggregation 等结构；`TimeGrain` 虽已泛化为可配置字符串，仍需由编译后的 temporal definition 校验，而不是把任意文本转成 SQL。
- `MappingCompiler` 是 protocol-neutral 的接入校验 seam；`MappingDef` 携带 source/provider/capabilities 与 provider-owned `physical`；`ReadProvider` 文档要求所有 key 为 semantic key，物理翻译留给 adapter。
- PostgreSQL analysis 使用 `require_ident`、参数绑定和 SQLGlot 之后置检查；`_sql_expr_ast` 只从闭集 Expr AST 构造 SQL AST，拒绝配置 SQL 文本。这是 defense-in-depth 的好起点。

### 需要补齐的结构

1. `MappingDef.physical: dict[str, Any]` 目前是 provider 约定的自由字典，缺少一个可被 Compiler/adapter 共同理解的 typed mapping contract；物理字段仍可能通过不同 key 产生隐式语义。
2. `MappingCapability` 目前主要是 `POINT_READ`、`COLLECTION_READ`、`EQUI_JOIN`，没有明确声明 projection/filter/aggregate/time grain/function pushdown、null/missing semantics、成本和参数化保证。
3. PostgreSQL `_compile` 已能生成受限 SQL，但 `_Plan` 是 adapter 私有结构，没有明确的 protocol-neutral LogicalPlan，因此 filter pushdown、join 选择、派生表达式和证据 lineage 不易由其他 provider 复用。
4. `_assert_sql` 的 AST allowlist 是后置防线，不应成为字符串 SQL 的主抽象。安全的首要边界应是 typed field/operator/function AST 和 provider capability；解析已生成 SQL 只能发现遗漏，不能证明任意模板语义正确。
5. `_derived_sql` 当前能把有限 arithmetic/round Expr lower 到同源 PostgreSQL 列，但缺少统一的表达式签名、NULL/缺失规则、跨 adapter lowering contract、函数能力注册和不可下推时的明确计划节点。

## 推荐的 protocol-neutral IR

### 1. 三层 IR，不让物理字段跨层泄漏

```text
SemanticQuery
  field/metric/link/time-grain = semantic ID
  values = TypedValue
  filter/group/order/aggregate = closed structures

LogicalPlan
  Scan(logical source/object)
  Project(semantic Expr)
  Filter(Predicate)
  Join(LinkRef, key pairs, cardinality)
  Aggregate(MetricRef, AggregateOp)
  GroupBy(FieldRef, GrainRef)
  Sort / Limit

PhysicalPlan
  MappingRef(mapping ID)
  source relation/column bindings (adapter-private)
  chosen capabilities and pushdowns
  policy/tenant predicates
  parameter slots
  dialect lowering and execution budget
```

Logical operators可参考 SPARQL algebra/Calcite `RelNode`，但 IR 中的名字必须是 SemaLoom 自己的稳定协议；不要直接把 Calcite、SQLAlchemy、SQLGlot AST 泄漏到 core 公共契约。`PhysicalPlan` 可以由 Postgres adapter 保存 SQL AST/SQLAlchemy statement，但只能通过 adapter 执行。

### 2. 表达式 AST 用语义引用和受控函数 ID

建议将 domain expression 规范化为如下闭集（实际字段名可沿用现有 `Expr` 风格）：

```text
Expr :=
  FieldRef(semantic_field_id)
  | Literal(typed_value)
  | Call(function_id, args)
  | Compare(operator, left, right)
  | Bool(operator, args)
  | Case(when_then, else)
```

`function_id` 不是 SQL 函数名。每个函数由注册表声明：参数类型、返回类型、NULL 输入行为、是否 deterministic、是否允许聚合、是否允许跨行、版本和 provider lowering。标准集合可以有 `ADD`、`SUBTRACT`、`DIVIDE`、`ROUND`、`COALESCE`（只有明确的缺失政策才允许）、`DATE_BUCKET` 等；provider 扩展用稳定 namespace/version，而不是任意 UDF 字符串。Substrait 的 function signature/extension 设计可作为参考，[Substrait function extensions](https://substrait.io/extensions/)、[Substrait scalar functions](https://substrait.io/expressions/scalar_functions/)。

domain 可定义命名派生指标：

```yaml
id: finance.review.margin
derivedFrom: [finance.review.revenue, finance.review.cost]
expression:
  op: div
  args:
    - {op: sub, args: [{op: ref, name: revenue}, {op: ref, name: cost}]}
    - {op: ref, name: revenue}
```

这个例子表达业务公式，但没有表列、SQL 运算符优先级、方言、别名或租户条件。Compiler 负责引用闭包、类型和可加性；adapter 负责将同一 AST lower 成自己的物理表达式或拒绝。

### 3. Mapping contract 应回答“能否执行”，不只回答“列在哪”

将来可以把当前自由 `physical` 归一化为 provider-owned `CompiledMapping`，其跨层可见摘要至少包括：

- semantic object/field → typed source projection 的绑定摘要；物理 table/column 只由 adapter 读取；
- identity/grain/property/value 的完整性和基数；
- 支持的 `Scan`、filter operators、join/link/cardinality、aggregate operators、time grains、function IDs；
- filter/aggregate/function 是否可 pushdown，若不能是否有安全 fallback；
- null/missing/empty semantics、精度、时区、排序和分页语义；
- 参数化保证、tenant/policy scope hook、只读保证、最大行/调用/成本估计；
- mapping release/version、dialect/version、物理 lineage 和 evidence digest。

这些信息可以让 planner 选择候选 capability，而不让 core 猜 PostgreSQL；也符合 Calcite adapter 的“logical operator + provider-specific implementation”边界，[Calcite adapter](https://calcite.apache.org/docs/adapter)。

### 4. 每个算子怎么安全表达

| 业务能力 | Logical IR | 允许的配置 | 不接受 |
| --- | --- | --- | --- |
| 列/属性 | `FieldRef(id)` | semantic field → mapping column 的审核绑定 | `SELECT ${userField}`、裸列名 |
| 派生字段 | `Call/Case/Arithmetic` typed AST | 命名 expression、函数签名、依赖声明 | `expr: "...SQL..."`、任意函数/UDF |
| 过滤 | `Predicate(FieldRef, Op, Literal)` | `EQ/IN/BETWEEN` 等闭集、值类型 | `where: "..."`、拼接用户值 |
| join | `Join(LinkRef, key pairs, cardinality)` | 已发布 Link、基数、来源 capability | 调用方 join SQL/任意 ON |
| 聚合 | `Aggregate(MetricRef, SUM/AVG/...)` | metric additivity、NULL policy、provider support | `SUM(${column})`、隐式去重/COALESCE |
| 时间/桶 | `GroupBy(FieldRef, GrainRef)` | 已声明 grain/calendar、provider capability | `DATE_TRUNC(${text})` |
| 方言函数 | `FunctionId + typed args` | registry + adapter lowering | 任意函数名或方言片段 |

过滤值必须始终进入 parameter slot；列/表标识符必须从已编译 mapping 解析后通过 adapter 的 identifier quoting 生成。所有 scope/tenant predicate 由 planner/adapter 注入，不能由 query expression 覆盖。

## Planner、adapter 和 Jev 的职责

### 建议的三个深模块/接缝

1. **SemanticCompiler**：输入 domain/integration bundle 与 `SemanticQuery`，验证 semantic ID、类型、Link、grain、aggregation/additivity、规则依赖和授权前置条件，输出不可变 `LogicalPlan` 与诊断。它不知道 SQL 方言。
2. **CapabilityPlanner**：输入 LogicalPlan、mapping capability、权限 scope、预算和来源 profile，选择 pushdown/fallback，输出 PhysicalPlan。它不能接受模型生成的物理 patch；选择必须可重复并记录理由/成本。
3. **Adapter compiler/executor**：输入 PhysicalPlan 中属于自己的 mapping/capability，生成参数化 SQL、API 请求或有界读取；维护 dialect function lowering、identifier quoting、连接、错误和来源 evidence。SQL renderer 是私有实现，不是公共接口。

现有 `MappingCompiler` 可以演化为第二、第三层之间的 seam：先保留 `compile_mappings`/`derive_metric` 兼容签名，再新增 typed capability/compiled mapping 返回值。不要把 SQLAlchemy/SQLGlot 的 AST 作为 core 类型。

### Jev 只做受限候选排序，不做 planner 或 SQL 生成

Jev 的优雅接入点是分类路由、候选判断和打分：

1. Python 根据编译 release、授权 scope 和当前问题生成候选 `metric_id`、`field_id`、`link_id`、`grain_id`、`aggregation_op`、`filter slot`；不把 table/column/SQL 发给模型。
2. Jev 返回候选 ID、类别和可选 score/排序；返回值只能是候选集合内的枚举，不能创建新字段、函数、join 或 predicate 文本。
3. Python 重新校验每一个 ID、值类型、Link 基数、metric additivity、grain capability、tenant scope、预算和来源实际可观测值，再编译 LogicalPlan。
4. 无候选、低置信度、歧义或 Jev 超时均回到确定性解析/clarification；Jev 禁用时，语义结果和安全边界不变。分数是路由元数据，不是业务真值，也不直接展示为事实。

这样 Jev 可以提高“用户说的是收入还是利润、按哪个时间轴、SUM 还是 AVG”的路由速度，但不能影响 SQL 的语法/权限边界。Wren 采用结构化 cube query 而非 agent 手写 GROUP BY 的实践可作为对照，[Wren cube query](https://docs.getwren.ai/oss/reference/cli#query_cube)。

## raw SQL、模板和占位符的风险与可接受替代

### 风险

看似中性的 `${field}`、`{column}`、`{{where}}` 会把不同类别混为一谈：

- 标识符替换可能越过允许列/表边界或产生方言注入；参数占位符只能绑定值，不能安全绑定任意 identifier。
- filter/join 字符串可能移除 tenant predicate、改变 outer/inner join、改变 NULL 语义、引入多对多放大或绕过 aggregation/additivity。
- expression 字符串可能调用 UDF、窗口、递归 CTE、子查询或昂贵函数；事后 parser allowlist 只能做补救。
- 让 agent 生成物理 SQL 会同时泄露 schema、扩大提示上下文、破坏 release 重放和 evidence 可验证性。

MetricFlow 的 `where_sql_template`、Cube 的 `sql`、Wren MDL 的 physical expression 说明 SQL-first 产品可以接受这种耦合，但它们也说明表达式会随 warehouse/dialect 绑定，[MetricFlow semantics](https://github.com/dbt-labs/dbt/blob/main/crates/dbt-metricflow/docs/metric-semantics.md)、[Cube dimensions](https://docs.cube.dev/docs/data-modeling/dimensions)、[Wren MDL](https://docs.getwren.ai/oss/reference/mdl)。SemaLoom 的 domain/integration 分层需要更严格的边界。

### 可以接受的替代

1. **物理字段绑定**：`semantic field ID → physical column`，仅在 integration mapping，使用 adapter-owned identifier validator。
2. **命名 logical expression**：`FieldRef/Literal/Call/Compare/Case` AST，函数注册表和类型检查在 Compiler；不保留原始 expression 字符串。
3. **静态 provider source query**：仅在审核的 integration artifact；发布前解析并拒绝 DML、未知表/列、未知函数、窗口/递归/危险扩展；使用只读凭证和固定 tenant/scope 注入；记录 mapping digest 和 lineage。调用方/Jev 无权修改 query。
4. **provider extension**：通过版本化 `FunctionId`/capability namespace 宣布一个已安装的扩展；扩展自行实现参数绑定、权限和 evidence，不把扩展名称当 SQL 片段。

如果 legacy mapping 必须包含 SQL，应隔离在 `physical.sourceQuery` 这类 adapter-private 字段，并设置：静态发布、schema/catalog allowlist、只读执行、参数槽而非字符串拼值、DML/DDL/网络访问拒绝、资源预算、租户条件审计和回归 fixture。它不能进入 domain pack，不能出现在 SemanticQuery，也不能成为 Jev 的候选输出。

## 迁移建议

### 阶段 A：保持现有外部契约，内部补齐 LogicalPlan

1. 保留当前 `SemanticQuery`/`FilterAtom`/`GroupByItem`/`MetricRef` 的 semantic wire 形状；在 Compiler 边界规范化成 `FieldRef`、`Predicate`、`LinkRef`、`Aggregate`、`GrainRef`。
2. 将 `RuleDef.expression`/现有 `Expr` 作为 domain-level AST，增加函数 registry、NULL/缺失和 provider lowering contract；禁止新增 SQL 文本字段。
3. 将当前 PostgreSQL `_compile` 前半段的语义校验和投影选择产出 immutable LogicalPlan；SQLAlchemy/SQLGlot 只在 PostgreSQL adapter 的后半段生成物理语句。`_assert_sql` 保留作为 defense-in-depth。
4. 在 evidence 中记录 semantic plan digest、mapping ID/version、capability decisions、parameter metadata 和 source lineage；原始 SQL 若因审计需要保存，放在受控 evidence drawer，不进入回答或模型上下文。

### 阶段 B：先做 Expr → SQL 的最小竖切

最小可交付案例应包含：

- 同一领域 pack 的两个数值 metric 通过 `add/sub/div/round` 形成一个派生 metric；
- Compiler 能检查未知引用、类型不匹配、循环、Decimal/NULL 规则和 additivity；
- Postgres adapter 将闭集 AST lower 成参数化 SQL AST，列来自 mapping，常量进入参数；
- 另一个 adapter 对不支持的函数返回 `UNSUPPORTED`，不能静默拉明细或改写业务口径；
- Jev 只能选择派生 metric 的 semantic ID，不能生成 expression；
- 生成计划可重放，SQL 中没有 domain/agent 输入的原始片段。

完成后再补 `computed field`：让 integration mapping 可声明“该 semantic expression 已由来源预计算为某列”，Compiler/Planner 比较语义等价、版本和 freshness，选择 source column 或 runtime expression。computed binding 不是第一竖切，因为它不能替代跨 provider 的语义表达式验证。

### 阶段 C：引入物理 computed field 作为优化

建议形状（仅为设计方向，不是本次实现要求）：

```yaml
# integration only
physical:
  computedFields:
    - semanticExpression: finance.review.margin
      column: margin_ratio
      valueType: DECIMAL
      freshness: source_snapshot
      validatedAgainst: finance.release.42
```

它必须指向一个已编译的 semantic expression ID，而不是接受 `sql: "..."`。Planner 只有在来源 capability 声明计算结果与当前 release、scope、grain、NULL policy 一致时才可选它；否则回到 Expr lowering 或明确拒绝。

### 兼容与废弃

- 旧 `physical.grainColumns`/`propertyColumns` 可以继续由 adapter 读取，由 `MappingCompiler` 归一化为 typed `SourceBinding`；不要求一次性重写示例。
- 若已有受信任 source query，保留 adapter-private legacy path，并在诊断中标记 provider-specific/deprecated；禁止把该字段传播到 domain 或 request schema。
- 旧 `derivedFrom` 继续表示依赖闭包；新增 expression AST 只扩展作者面，不改变 metric semantic ID。release digest 固定后不能因为 mapping 优化自动改变语义计划。
- 新增 LogicalPlan/CompiledMapping 后，更新 [ADR-0006](../adr/0006-independent-integration-layer.md)、[ADR-0011](../adr/0011-semantic-query-planner.md)、semantic contract 和 acceptance；不要让 SQL-first 例外悄悄成为新的公共契约。

## 验收建议

### 语义与安全

- domain 中出现表名、列名、SQL keyword、`${...}`、`{{...}}` 或未知 function 时，Compiler 拒绝或明确标为 provider-private，而不是接受为可执行语义。
- 任何 query 值即使包含 `' OR 1=1 --`、分号、注释或函数文本，也只能进入 typed parameter；列/表只能来自已激活 mapping。
- Jev 返回未知 metric/field/link/function、修改 operator、拼接 SQL 或越过 candidate set 时，服务端拒绝并产生可解释诊断。
- tenant/policy scope 在每一个 base scan/join 上保留；LogicalPlan 变换不能删除或移动出安全边界。

### 逻辑代数

- Filter、Join、Project、Aggregate、GroupBy、Sort/Limit 的计划快照与结果等价；过滤下推不能改变 outer join、NULL、缺失和多对多基数。
- SUM/AVG/MIN/MAX/COUNT 受 metric value type、additivity、missing policy 和 provider capability 约束；禁止隐式 DISTINCT、COALESCE missing-to-zero 或 float 金额。
- 派生 Expr 的引用闭包、结果类型、Decimal 精度、除零、NULL/UNKNOWN 语义有正例和拒绝例；同一个 semantic expression 在不同 provider 上要么等价执行，要么得到 `UNSUPPORTED`。
- 时间/自定义 grain 只引用 bundle 中已声明定义，不能直接把用户字符串传给 `DATE_TRUNC` 或其他函数。

### 映射与 adapter

- mapping validator 只允许声明的表/列/函数；static source query 若启用，必须通过 read-only/DML/allowlist/parameterization/预算检查。
- Postgres 验证 generated SQL 的表列 lineage、函数 allowlist、tenant predicate、绑定参数和 no-window/no-DML；SQLGlot 检查不能替代 typed IR 测试。
- API/非 SQL adapter 对 filter/join/aggregate/function 能力给出明确 capability；不把 API 已聚合字段或单点查询冒充成任意关系算子。
- 同一 domain pack 绑定两个不同物理 schema 能得到相同 LogicalPlan 和等价业务结果；只改 integration，不改 core/domain。

### Jev、证据和回归

- Jev 开启、关闭、超时、低分时，确定性候选校验和最终计划一致；模型只影响候选排序，不影响安全/权限/算子集合。
- Evidence 能从 semantic plan digest 追到 mapping release、capability decision、参数元数据和来源版本；回答不泄露 raw SQL、物理 schema 或内部模型分数。
- 计划含未知字段、跨来源不支持、函数不支持、表达式过深、预算超限时均返回稳定 `UNSUPPORTED`/diagnostic，不卡在“生成 SQL 后再猜”。

## 明确不应照搬

- 不把 R2RML/Ontop 的 source SQL 直接放进 domain ontology；只借鉴 mapping 与 ontology 分离、typed term map 和已声明 join。
- 不把 Cube 的 `sql`、MetricFlow 的 `expr/where_sql_template` 或 Wren 的 SQL expression 当作跨 provider 的公共语义语言；它们是 SQL-first 产品的物理耦合。
- 不把 Calcite/Substrait 的完整 AST 或 wire format 直接暴露给调用方；只吸收 logical/physical、typed expression、function registry、trait/capability 的边界。
- 不把 SQL parser/allowlist 当作唯一安全边界；首要边界必须是 semantic IDs、typed IR、mapping ownership、参数化和值域校验。
- 不让 agent/Jev 选择表、列、函数字符串、join 条件、租户条件或任意 plan patch；模型永远在候选 semantic IDs 内工作。
- 不先做物理 computed field 来掩盖缺少逻辑表达式契约；先完成 Expr 类型/语义/lowering 与拒绝路径，再把 computed field 作为可验证的 source optimization。

## 参考来源

### 规范、官方文档与官方源码

- [W3C R2RML Recommendation](https://www.w3.org/TR/r2rml/)
- [W3C SPARQL 1.1 Query — translation to algebra](https://www.w3.org/TR/sparql11-query/#sparqlAlgebra)
- [Ontop guide](https://ontop-vkg.org/guide/)、[Ontop mapping language](https://ontop-vkg.org/guide/advanced/mapping-language.html)
- [Apache Calcite algebra](https://calcite.apache.org/docs/algebra.html)、[Calcite adapters](https://calcite.apache.org/docs/adapter)、[RexNode Javadoc](https://calcite.apache.org/javadocAggregate/org/apache/calcite/rex/RexNode.html)、[RelNode Javadoc](https://calcite.apache.org/javadocAggregate/org/apache/calcite/rel/RelNode.html)
- [Substrait specification](https://substrait.io/spec/specification/)、[extensions](https://substrait.io/extensions/)、[scalar functions](https://substrait.io/expressions/scalar_functions/)
- [dbt MetricFlow repository](https://github.com/dbt-labs/metricflow)、[metric semantics](https://github.com/dbt-labs/dbt/blob/main/crates/dbt-metricflow/docs/metric-semantics.md)
- [Cube dimensions](https://docs.cube.dev/docs/data-modeling/dimensions)、[Cube calendar cubes](https://docs.cube.dev/docs/data-modeling/concepts/calendar-cubes)
- [Wren MDL](https://docs.getwren.ai/oss/reference/mdl)、[Wren cube query CLI](https://docs.getwren.ai/oss/reference/cli#query_cube)、[Wren cubes](https://docs.getwren.ai/oss/guides/cubes)

### 论文原文

- Goetz Graefe and William J. McKenna, “The Volcano Optimizer Generator: Extensibility and Efficient Search”, [ICDE 1993 PDF](https://15721.courses.cs.cmu.edu/spring2023/papers/16-optimizer1/graefe-icde1993.pdf), [IEEE DOI](https://doi.org/10.1109/ICDE.1993.344061)
- Goetz Graefe, “Volcano—An Extensible and Parallel Query Evaluation System”, [IEEE TKDE 1994 PDF](https://people.eecs.berkeley.edu/~prabal/teaching/resources/eecs582/graefe94volcano.pdf)

### SemaLoom 当前契约与实现观察

- [ADR-0006 独立接入层](../adr/0006-independent-integration-layer.md)
- [ADR-0011 语义查询规划](../adr/0011-semantic-query-planner.md)
- [ADR-0012 事实与业务词汇](../adr/0012-facts-and-business-vocabulary.md)
- [ADR-0013 测量槽可加性](../adr/0013-measure-additivity.md)
- [core model](../../src/semaloom/core/model.py)、[semantic query](../../src/semaloom/core/semantic_query.py)、[mapping compiler seam](../../src/semaloom/core/compilation.py)、[Expr IR](../../src/semaloom/core/expr.py)、[PostgreSQL analysis](../../src/semaloom/adapters/analysis.py)

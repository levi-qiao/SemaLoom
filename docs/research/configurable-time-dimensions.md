# 可配置时间维度与时间粒度研究

调研日期：2026-09-21。问题：SemaLoom 如何让“年度、月份、日期、财务期间、零售日历”等由领域包和接入绑定表达，而不是把 `year` / `month` / `day` 写死在 core、Compiler 或 Chat 中。本文只核查公开的一手文档、规范和官方仓库；没有安装第三方引擎、读取业务数据或改变运行时代码。

## 结论先行

SemaLoom 不应把 `yearProperty` 改名成另一个“固定时间字段”。应拆成三个层次：

1. **时间角色（temporal role）**：某个语义属性是否可作为时间轴、期间轴或时间筛选轴；它可以是 `DATE`/`DATETIME`，也可以是整数或字符串编码的业务期间。类型和角色不能混为一谈。
2. **时间粒度（grain）**：这次查询按什么桶分组，例如 `day`、`month`、`fiscal_quarter`、`retail_454_week`。标准粒度可由 adapter 翻译；自定义粒度必须是已发布配置中的稳定 ID，不能是调用方传入的 SQL/表达式。
3. **日历/期间实现（calendar or period implementation）**：如何把原始值映射到桶，包括时区、财务年起始月、4-5-4 零售周、期间维表或预计算键。这属于领域配置加接入能力，不应污染通用查询 IR。

推荐的稳定边界如下：

```text
领域包：field/temporal role + default grain + allowed grain IDs + business labels
        │
        ├── 日期型：声明可支持的标准粒度或已命名日历
        └── 编码型：声明 fiscal_month / accounting_cycle 等自定义期间字段和层级

接入绑定：calendar/time-spine/derived-key 的物理实现与能力
        │
        ├── SQL：date_trunc、日历维表 join、预计算期间键
        └── API：已按期间返回的点值/集合能力

查询 IR：field ID + grain ID + typed range/value
Planner：校验声明、选择候选、检查 adapter capability，再生成物理计划
```

这让 core 只理解“声明的时间维度、声明的粒度和声明的能力”，而不理解“这个业务一定有年份”。“年份”只作为采购/税务示例里的一个配置实例。

## 当前 SemaLoom 的基线与缺口

调研后的首个纵向切片已经完成：`PopulationSpec` 使用通用 `scope_properties`；Compiler 不再要求整数年度；Runtime/adapter 用 `analysis_dimension_values(metric, field)` 返回类型化候选；选择题统一为 `DIMENSION_VALUE`；统计单位唯一性和 SEMI 可加性都按全部范围属性判断。采购合同示例使用 STRING 会计期间，验证该接口不是 `yearProperty` 的改名。`TimeGrain` 在 core 中也不再是 `YEAR | MONTH` 闭集，PostgreSQL adapter 对自身支持的物理截断粒度做白名单校验。

尚未闭合的是更丰富的时间角色、日历与层级声明。当前 DATE/DATETIME 可使用 adapter 支持的标准截断，已编码期间键可直接筛选/分组；财务年、4-5-4 日历、time-spine、空桶补齐和自定义层级仍应按本文建议增加声明式 temporal/calendar capability。它们不能靠字段名推断，也不能仅因为 core 字段改成 `str` 就绕过 Compiler/adapter 校验。最终决策与当前交付边界见 [ADR-0015](../adr/0015-configured-scope-and-time.md)。

## 一手项目对照

### Cube：时间是有角色的维度，内置与自定义粒度分开

Cube 把 `timestamp`/`date`/`time` 映射成 `type: time` 的 dimension；查询时可按 year、quarter、month、week、day、hour、minute、second 分组，而不用为每个粒度复制字段。[Cube Dimensions](https://docs.cube.dev/docs/data-modeling/dimensions#time-dimensions) 明确把时间维度定义为一种维度角色，并将粒度作为查询能力。

当内置粒度不够时，Cube 允许在时间维度上声明带名字的 custom granularity，例如 `sunday_week` 或 `fiscal_year`，由 `interval` 和 `offset` 描述；这说明“业务叫法”和“实现公式”可以分离，但它仍是 Cube 自己的 SQL 模型语言。[Cube custom granularities](https://docs.cube.dev/docs/data-modeling/dimensions#custom-granularities)

对财务/零售日历，Cube 还支持 `calendar: true` 的 calendar cube：日历表提供 `start_of_week`、`start_of_month`、`start_of_year` 等键，粒度和 time shift 从日历表覆盖，而不是强行假设自然日历。[Cube calendar cubes](https://docs.cube.dev/docs/data-modeling/concepts/calendar-cubes#configuration)

**可借鉴**：时间角色、查询时选择粒度、命名的自定义粒度、独立日历表。

**不应照搬**：Cube 的 `sql`、`interval`、`offset` 是 SQL 物理模型能力；SemaLoom 的 domain pack 不应承载 SQL 片段或让调用方提交表达式。SemaLoom 应由 integration binding 声明“这个粒度可以由哪个 provider 能力实现”。

### dbt MetricFlow：默认粒度、时间维度和 time spine 分层

MetricFlow 把时间维度放在 semantic model 中，并允许配置默认粒度；查询可以请求不同的粒度。dbt 的语义层设计讨论明确说明，`time_dimension` 的 `time_granularity` 是默认值，查询方在允许范围内可以切换到更高或更低粒度。[dbt semantic layer proposal](https://github.com/dbt-labs/dbt/discussions/7456#discussioncomment-5476510)

MetricFlow 对需要时间连接/填补/累计计算的能力引入 time spine。官方文档要求在 YAML 中声明标准粒度列，也允许 `custom_granularities` 把 `fiscal_year`、`retail_month` 这样的组织期间映射到同一时间 spine 的列；它还会根据查询选择兼容的、尽量粗的 time spine 以减少成本。[MetricFlow time spine](https://github.com/dbt-labs/docs.getdbt.com/blob/current/website/docs/docs/build/metricflow-time-spine.md#configuring-time-spine-in-yaml)

文档还提醒了两类常被硬编码遗漏的边界：时间 spine 与事实时间维度的类型必须一致；时区转换不会自动替用户完成。[MetricFlow time spine considerations](https://github.com/dbt-labs/docs.getdbt.com/blob/current/website/docs/docs/build/metricflow-time-spine.md#considerations-when-choosing-which-granularities-to-create)

**可借鉴**：默认粒度与请求粒度分开；自定义期间映射到声明的列；time spine 是一种可选执行能力；类型和时区显式校验。

**不应照搬**：MetricFlow 的某些累计/offset 能力依赖全局时间 spine，不能成为 SemaLoom 所有查询的前置条件。没有可用 calendar/time-spine 的来源仍可合法地做点查或按已存期间键聚合；只有计划确实需要补齐空桶、滚动窗口或时间连接时才要求相应 capability。

### Wren AI MDL：单独的 `time_dimensions` 和结构化查询输入

Wren 的 MDL cube 显式列出 `time_dimensions`，每项有名称、表达式和类型；查询使用 `name:granularity[:start,end]` 的结构化参数，不把 `GROUP BY` 或 `DATE_TRUNC` 交给 agent。其 MDL 文档和 CLI 文档分别给出声明与查询契约：[MDL cube time_dimensions](https://docs.getwren.ai/oss/reference/mdl#cubes)、[Wren cube query](https://docs.getwren.ai/oss/reference/cli#query_cube)。

**可借鉴**：让 agent/Chat 选择“哪个语义时间维度 + 哪个粒度 + 哪个范围”，而不是猜物理列；候选集合由已编译模型提供；查询输入是结构化的。

**不应照搬**：Wren cube 的 `expression` 面向 SQL 数据源。SemaLoom 要保持 [ADR-0006](../adr/0006-independent-integration-layer.md) 的领域/接入分离，domain pack 只拥有语义字段和粒度 ID，物理表达式留在 Mapping/adapter。

### Malloy：把时间值和范围作为类型化语义

Malloy 将 `date` 与 `timestamp` 作为独立类型，支持 `second`、`minute`、`hour`、`day`、`week`、`month`、`quarter`、`year` 的截断，并把 `@2025`、`@2025-01` 等带分辨率的字面量解释为半开时间范围，而不是普通整数/字符串比较。[Malloy timestamp operations](https://docs.malloydata.dev/documentation/language/timestamp-operations)、[Malloy time ranges](https://docs.malloydata.dev/documentation/language/time-ranges)

Malloy 还把 timezone 作为时间运算上下文；官方文档展示同一个 UTC 时刻在不同 timezone 下可能属于不同的年份。[Malloy timezones](https://docs.malloydata.dev/documentation/language/timezones)

**可借鉴**：时间筛选在 IR 中应优先表示为 typed range/interval，避免把“2025”误当成业务整数；时区和边界是语义的一部分。

**不应照搬**：Malloy 的解析器有固定的时间字面量语法和内置时间单位；SemaLoom 的用户语言必须先由 ontology/Jev 识别，再由 Compiler 校验已声明的 grain 和 typed value，不能把 Malloy 的语法当成通用行业本体。

### Apache Ossie/OSI：数据类型与时间角色明确分离

Apache Ossie（原 Open Semantic Interchange，当前规范仍标为 draft）在 field 上把 `datatype` 与 `dimension.is_time` 分开：datatype 表示存储/逻辑值类型，`is_time` 表示是否承担时间维度角色。规范甚至允许 `Integer` 的 `d_year` 或 `String` 的 `d_quarter_name` 通过 `is_time: true` 成为时间维度；而 `DateTime` 的审计字段可以显式 `is_time: false`。[Ossie Core Metadata Specification §Fields](https://raw.githubusercontent.com/apache/ossie/main/core-spec/spec.md#L238-L356)

这是对 SemaLoom 最直接的启发：**不能因为一个字段不是 DATE/DATETIME，就否定它的业务时间语义；也不能因为字段名含 `year`，就自动认为它是时间轴。** 角色必须是显式、可审计的 ontology metadata。

需要注意该规范的版本声明为 `0.2.0.dev0` 且明确说明 schema 仍可能变化；可以借鉴这种 type/role 分离，但不应把它当作 SemaLoom 的运行时依赖或完整日历协议。[Ossie draft notice](https://raw.githubusercontent.com/apache/ossie/main/core-spec/spec.md#L17-L26)

## 推荐的 SemaLoom 抽象

### 1. 领域模型：时间维度是属性的语义角色

不要增加 `yearProperty`、`monthProperty`、`dayProperty` 三个平行字段。建议给可参与时间分析的属性增加一个精简的业务元数据块（名称可在实现时按现有 DSL 风格调整）：

```yaml
properties:
  - id: orderedAt
    valueType: DATETIME
    temporal:
      role: TIME
      defaultGrain: month
      allowedGrains: [day, week, month, quarter, year]
      calendar: gregorian

  - id: accountingPeriod
    valueType: STRING
    temporal:
      role: PERIOD_KEY
      defaultGrain: fiscal_month
      allowedGrains: [fiscal_month, fiscal_quarter, fiscal_year]
      calendar: cn_fiscal
```

这里的 `role` 是语义角色，不是 UI 展示开关；`defaultGrain` 解决“用户只问趋势但没说粒度”时的确定性；`allowedGrains` 防止用户或 Jev 任意下钻到不存在的粒度；`calendar` 是稳定语义 ID，不是 SQL 或 URL。

对于人口统计集合，`unitProperty` 与 `scopeProperties` 只描述完整 grain；如果某个 scope property 具备时间角色，Compiler 从属性元数据解析它，而不是从字段名或 population 中硬编码年度。一个对象可以有多个时间维度，例如 `orderedAt`、`approvedAt`、`settledAt`，每个指标/查询可以选择其中一个作为 `metric_time`；“默认时间维度”应是声明的 ID，而不是全局唯一的 `yearProperty`。

对于已经按财务期间存储的事实（例如 `FY25-P07`），不要强行转换成自然日期。把它建模为 `PERIOD_KEY`，在 ontology 中声明级别/父子关系或可查询粒度 ID；这样字符串/整数期间仍能用于筛选和分组，并保持原始业务口径。

### 2. 查询 IR：粒度是可验证的引用，不是固定 Literal

`GroupByItem` 的时间部分已从 `YEAR | MONTH` 闭集改为可验证的 grain reference；后续 temporal schema 应保持以下形态：

```text
GroupByItem(
  id = "orderedAt",
  grain = "month"              # 或 "cn_fiscal.fiscal_month"
)
```

`grain` 仍可在 canonical IR 中是字符串，但必须经过 Compiler 解析到 bundle 中已声明的 grain definition（包含时间维度、calendar、排序/边界语义和 adapter capability）。不能因为把 Python `Literal` 换成 `str` 就放弃校验。

筛选优先使用 typed range：日期型字段用 `[start, end)`；离散期间键用 `EQ`/`IN` 的 typed value。不要让所有业务都经过 `year: int` 的专用路径。Chat 的选择槽也应改成通用 `TIME_DIMENSION` / `TIME_GRAIN` / `PERIOD_VALUE`（命名可按现有 wire 兼容策略落地），展示文案从 ontology label 和粒度定义生成。

### 3. 执行能力：标准粒度与自定义日历分开

接入层建议声明类似以下能力，而不是让 core 猜 provider：

```text
time_capabilities:
  - dimension: orderedAt
    grains: [day, week, month, quarter, year]
    operation: NATIVE_TRUNCATION
  - calendar: cn_fiscal
    grains: [fiscal_month, fiscal_quarter, fiscal_year]
    operation: CALENDAR_LOOKUP
    source: declared calendar mapping
```

对 SQL adapter：`day/month/year` 等标准 grain 可由方言能力翻译；自定义财务粒度需要明确的日历维表、源列或已预计算键。对 API adapter：如果接口直接按 `fiscal_month` 返回一个点，能力是 `POINT_READ`；如果只返回日期明细，则不能伪装成已支持的聚合粒度。Planner 应在语义校验后检查 capability，不能把“不支持”写成 `if item.time_grain == "MONTH"` 这种行业特判。

时间 spine 是可选的执行优化/补齐能力：只有查询要求“没有事实的空桶也要返回”、累计窗口或跨表时间连接时才要求它。没有 spine 的常规点查、已编码期间查询和来源已聚合的 API 仍应可执行。

### 4. 默认值、候选和 Jev 的接入

建议保持“确定性语义引擎为主，Jev 为有界候选排序器”：

1. Python 从 bundle 枚举可用的时间维度、允许粒度、默认粒度和已授权期间值，形成小候选集；候选应包含稳定 ID、label、类型、范围/样例和来源能力摘要。
2. 只有在用户话语同时可能指向多个时间维度/粒度时，Jev 才对候选做分类、打分或排序；输出只能引用候选 ID，并返回 `no_semantic_match` / `needs_clarification` 等受限结果。
3. Python 重新校验 Jev 的 ID、粒度允许性、当前 metric grain、tenant scope、来源实际存在值和时间边界；不接受模型生成的 SQL、字段路径、日期范围或权限声明。
4. 若 Jev 不可用、超时或低于内部阈值，回到 deterministic path；阈值和模型置信度不直接暴露给用户。回答只展示自然业务文案，原始选择/打分放进 Evidence。

该模式既能利用 Jev 加速分类路由，也不会让模型成为时间语义的最终裁判；和 Wren 的结构化 `time-dimension` 查询、Ossie 的显式时间角色是一致方向，但保留 SemaLoom 自己的授权与证据边界。

## 兼容迁移方案

### 阶段 A：读取兼容，canonical IR 泛化

1. 解析旧 `yearProperty` 时，在编译边界生成一个临时 temporal definition：`property=<旧值>`、`role=TIME`、`valueType=INTEGER`、`defaultGrain=year`、`allowedGrains=[year]`。旧领域包不需要立即全部重写。
2. 解析旧 `GroupByItem.timeGrain` 时，将 `YEAR`/`MONTH` 映射到 canonical grain ID；保留 wire alias 只为兼容旧客户端，不再让执行器按这个字段做行业判断。
3. 旧 `ChoiceKind.YEAR` 的提交值转换为通用 `PERIOD_VALUE`，其 `field` 仍必须通过编译后的 temporal definition 校验。新回答不再写死“某年”，而使用配置的 label/粒度。
4. 在诊断中把 legacy 字段标记为 deprecation；不要在兼容层悄悄把缺失时间字段补成当前年份。旧 release 继续按旧 bundle 重放，新 release 使用新 canonical IR，因此不会混版。

### 阶段 B：领域包迁移与行为验证

1. 税务示例把 `taxYear` 迁成显式 `role: PERIOD_KEY` 的 `tax_year`，并保留 `year` 作为一个配置粒度；采购示例同时加入 `orderedAt: DATETIME` 的月度/日度分析和财务期间键，证明同一 core 可处理不同时间形态。
2. 增加至少三类配置 fixture：日期时间轴、整数/字符串编码期间、外部财务日历。每类只改 YAML 与 integration binding，不改 core 分支。
3. 当新 wire 契约覆盖所有客户端后，才移除 `YEAR` 专用槽和 `yearProperty` 的写入；读取兼容至少跨一个 release 周期。任何 breaking change 都要更新 semantic contract、schema、示例和 release digest 兼容说明。

## 验收清单（给实现任务）

- **编译**：`DATE`、`DATETIME`、整数年度、字符串 `FY25-P07` 均可通过“显式时间角色”进入不同 temporal definitions；未声明 grain、重复 grain、calendar 引用不存在、允许粒度与字段类型/接入 capability 不一致时拒绝并定位到配置路径。
- **查询**：同一查询 IR 可按 day/month/quarter/year 和自定义 fiscal grain 工作；`BETWEEN` 使用半开边界；时区/财务年边界有独立测试；多个 metric 只有在时间维度和粒度兼容时才合并。
- **候选**：候选值按具体 metric、具体时间维度、租户授权和非空观测生成；不会显示其他 metric 的年份/期间；没有可用值时是可解释的 `NEEDS_INPUT` 或空结果，而不是虚构候选。
- **Chat 连续性**：后续“换到下个月/下个财务期间”只替换对应 temporal slot，继承 metric、aggregation、其他 filters；不能残留旧期间条件或无意清除其他维度。
- **Jev**：候选排序、无匹配、超时和低分都覆盖；任何模型输出都经过 ID/粒度/权限/来源值再验证；关闭 Jev 后行为与 deterministic path 一致。
- **呈现**：用户文案使用配置中的期间名称和自然语言；原始 `TIME_GRAIN_UNSUPPORTED`、`EMPTY_POPULATION` 等只在 Evidence/诊断层，不出现在简单业务回答。
- **不变性**：新增业务只增加 ontology YAML、calendar/time-spine mapping 与 fixture；不得在 core 出现 `taxYear`、`contractYear`、`fiscalYear` 等领域字段名分支。

## 明确不采用的方案

- 不把 `yearProperty` 机械重命名为 `periodProperty` 后继续要求单一字段；这只能延后同一个问题，无法表达多个时间维度和层级。
- 不把所有日期逻辑放进 domain YAML 的 SQL 表达式；这违反领域/接入分离，也让 API 来源无法复用同一语义定义。
- 不让 Jev/LLM 直接生成日期粒度、物理字段、SQL 或权限；模型只能在已发布候选中做选择/排序。
- 不把 time spine、calendar table 或 `date_trunc` 作为所有查询的硬依赖；它们是可声明的 provider capability。
- 不把一组无限开放的字符串 grain 直接当作可执行能力；自定义 grain 必须有稳定 ID、边界/排序语义、允许范围和至少一个已验证的接入实现。
- 不照搬 Malloy 的隐式时间字面量或 Cube 的 SQL 公式到 SemaLoom 的公共语义契约；应保留 typed range、角色/粒度分离和独立物理映射这些可迁移原则。

## 主要一手来源

- [Cube Dimensions](https://docs.cube.dev/docs/data-modeling/dimensions)：time dimension、内置粒度和 custom granularities。
- [Cube Calendar cubes](https://docs.cube.dev/docs/data-modeling/concepts/calendar-cubes)：日历立方体、日历表列和自定义粒度/shift。
- [dbt/MetricFlow time spine](https://github.com/dbt-labs/docs.getdbt.com/blob/current/website/docs/docs/build/metricflow-time-spine.md)：标准/自定义粒度、time spine 选择、类型与时区约束。
- [dbt semantic layer proposal](https://github.com/dbt-labs/dbt/discussions/7456)：`time_dimension` 默认粒度与查询粒度的分离（提案，非当前稳定规范）。
- [Wren AI MDL cube reference](https://docs.getwren.ai/oss/reference/mdl#cubes) 与 [Wren cube CLI](https://docs.getwren.ai/oss/reference/cli#query_cube)：显式 `time_dimensions` 与结构化 `name:granularity` 查询。
- [Malloy timestamp operations](https://docs.malloydata.dev/documentation/language/timestamp-operations)、[time ranges](https://docs.malloydata.dev/documentation/language/time-ranges)、[timezones](https://docs.malloydata.dev/documentation/language/timezones)：时间类型、粒度截断、半开范围和时区。
- [Apache Ossie Core Metadata Specification](https://raw.githubusercontent.com/apache/ossie/main/core-spec/spec.md#fields)：`datatype` 与 `dimension.is_time` 的角色/类型分离；当前仍是 draft。
- [SemaLoom PopulationSpec](../../src/semaloom/core/model.py#L60-L66)、[Compiler population validation](../../src/semaloom/compiler/api.py#L686-L700)、[SemanticQuery TimeGrain](../../src/semaloom/core/semantic_query.py#L21-L23)、[Runtime year choice](../../src/semaloom/runtime/analysis.py#L132-L156)：当前工作区迁移与年度硬编码的直接证据。

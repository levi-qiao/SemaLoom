# 0015 — 范围属性由本体声明，时间能力由接入层实现

状态：accepted，2026-09-21。替代把年度作为统计集合固定组成部分的早期约定。调研见 [可配置时间维度与时间粒度](../research/configurable-time-dimensions.md)。

## 决策

1. **Population 不认识年份。** `Metric.population` 只声明 `unitProperty`、有序的 `scopeProperties` 与口径说明。范围属性可以是年度、账期、营业日、班次、版本、场景或未来领域定义的其他属性，值类型不受 core 特判。
2. **缺范围走同一个深模块。** Runtime 按已发布 Metric、当前租户和具体范围属性读取该指标确有非空观测的类型化候选，统一生成 `DIMENSION_VALUE`。`YEAR` ChoiceKind 与 `analysis_years` 不再是公共接口；客户端不根据槽名识别业务。
3. **Agent 选择声明，Python 验证执行。** 确定性语言适配器与 Agent/Jev 都只产生 `semantic role / semantic ID + typed value + operator/grouping` 提示；通用编排不接收 `year`、`month`、`perspective` 等命名槽。模型只在 Compiler 提供的有限语义 ID、范围属性、粒度和候选值中分类或打分；不得生成物理字段、SQL、日历表达式或权限。Compiler/Runtime 重新校验属性归属、类型、范围、授权和 adapter 能力。
4. **期间键与时间运算分离。** 已按期间存储的 INTEGER/STRING 属性直接按类型化值筛选或分组。属性可用开放、可组合的 `semanticRoles` 声明用途；当前可替换语言适配器把四位年份文本输出为 `time.year` 类型化约束，把趋势/前期比较输出为 `time.sequence` 分组提示。Core 与 Chat 编排只消费通用提示，不按字段名、位置或行业猜角色。DATE/DATETIME 的截断由 adapter 实现，且 adapter 必须对白名单粒度做能力校验。
5. **上一期间来自已授权观测序列。** `PERIOD_OVER_PERIOD` 只在唯一且声明 `time.sequence` 的范围属性上查找当前值的前一个已观测候选，不再执行“整数年份减一”。没有前序值时返回缺少上一期间，不伪造自然年含义。

## 影响

- 领域包把 `yearProperty` 迁移为 `scopeProperties`；采购示例使用 STRING 会计期间验证非年份路径。
- 固定维度由 Metric 的通用 `select` 声明；未固定且属于 grain 的属性必须进入 population scope，不能靠编译器中的命名特例跳过补充选择。
- SEMI 可加性要求所有声明范围属性被单值约束或进入分组；统计单位唯一性使用 `unitProperty + scopeProperties`。
- 回答正文只显示自然业务说明；原始原因码、物理字段和执行细节保留在 Evidence。
- `semanticRoles` 是通用语义提示，不是时间字段枚举；场景、版本、排序轴或未来领域角色可由领域包声明，使用方只能选择自己理解且类型兼容的角色。自定义财务/零售日历仍需要后续 calendar 与 integration capability。

## 不做什么

- 不把 `yearProperty` 机械扩成 `yearProperty/monthProperty/dayProperty`。
- 不把语言适配器识别到的年份结构泄漏为通用编排字段；替换语言或模型只需实现同一 typed hint/decision interface。
- 不允许 Agent 自由发明粒度、日期范围或期间值。
- 不因字段类型是日期就自动赋予业务时间角色，也不因字段名含 year/month 就推断时间。
- 不在 domain YAML 中加入 SQL、`date_trunc` 表达式或展示布局。

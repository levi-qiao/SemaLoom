# 缺槽不猜：本体字典驱动卡片 / 下拉 / 表单

调研日期：2026-09-18。问题：问答缺选项、枚举、区域下钻时，如何用本体配置推出稳定选择控件，而不是让模型自由发挥。本文只核查官方文档、经典对话论文与本仓库已落地协议。

## 结论

**取值闭集写在 Property 上；缺槽时只发服务器持有的选择题，不猜测。** 这与 Looker 的 `allowed_value`（显示名 → 存储值）、Palantir Ontology 的枚举约束 + Workshop Filter List，以及任务型对话的 slot-filling 一致：未观察的槽位保持“未填”，用表单收齐后再执行。

SemaLoom 已有 `NEEDS_INPUT` + `ChoiceKind`（含闲置的 `DIMENSION_VALUE`）。本切片把 Property `values`（id / label / aliases）当作字典，Chat 把未说出的维值、规则和主体变成卡片或下拉；客户端只提交 option id。

## 权威来源

### Looker：显示名与存储值分开

[Changing filter suggestions](https://docs.cloud.google.com/looker/docs/changing-filter-suggestions)、[`allowed_value`](https://cloud.google.com/looker/docs/reference/param-field-parameter)、[`suggestions`](https://cloud.google.com/looker/docs/reference/param-field-suggestions)：

- `allowed_value.label` 是用户看到的选项；`value` 才进入查询。
- `suggestions` 可写死建议列表，避免对大表 `SELECT DISTINCT`。
- 用户从控件点选，不把自由文本当 SQL。

本仓库对应：`Property.values[].label/aliases` → 卡片文案；`id` → `FilterAtom` 的类型化 EQ。

### Palantir：本体约束，界面是 Filter / Form

Ontology 属性可挂枚举约束；Workshop Filter List 对可排序字符串给出多选下拉，Action 表单用 multiple choice。社区文档明确：枚举是本体层，下拉是界面消费该闭集，而不是模型临时编选项。[Value type enum](https://community.palantir.com/t/use-value-type-enum-in-create-drop-down/2330)、[Filter list options](https://community.palantir.com/t/options-in-filterlist/5537)。

### Slot filling：缺槽就问，不要当已填

Williams, S. Young, *Partially Observable Markov Decision Processes for Spoken Dialog Systems*, Computer Speech & Language 21(2), 2007。任务型对话把每个槽位当成未观察变量；策略是继续询问直到槽可提交，而不是用低置信猜测填上。Rasa Forms / SGD（Schema-Guided Dialogue）同一原则：required slots 未齐则停在表单。

SemaLoom 的 `ABORT`（都不符合）对应“拒绝猜测”；`OTHER` 把补充说明并回原问题再解释，仍不把自由文本当计划补丁。见 [ADR-0011](adr/0011-semantic-query-planner.md)。

## 环比不是窗口函数

Kimball 把同比/环比当作查询时计算，不是事实表上的可加度量。Looker 的 period-over-period、Cube timeShift 都是二次聚合。ADR-0011 明确 `WINDOW_LAG` 为 `UNSUPPORTED`。年度粒度的「环比/同比」实现为 `ComparisonOp.PERIOD_OVER_PERIOD`：本期与上一年各做一次已批准聚合，再算 `(本期-上期)/|上期|`。月环比在整数年上返回 `TIME_GRAIN_UNSUPPORTED`。

## 本仓库落地

| 槽 | 本体来源 | 控件 |
| --- | --- | --- |
| 指标口径 | Metric 别名冲突 | 卡片 |
| 年度 | population 已出现的年 | 下拉 + 卡片 |
| 维值 | Property.values | 下拉 + 卡片 |
| 判断规则 | Rule.claim / aliases | 下拉 + 卡片 |
| 判断主体 | find_objects 候选 | 卡片 |
| 环比 | 查询算子，不是字典 | 无需选项 |

不把 `SELECT DISTINCT` 当字典。未配置 `values` 的属性不会弹出维值卡片。

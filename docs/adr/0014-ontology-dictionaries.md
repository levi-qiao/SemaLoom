# 0014 — 本体字典驱动选择题，环比是查询算子

状态：accepted，2026-09-18。补齐 [ADR-0011](0011-semantic-query-planner.md) 已预留但未发射的 `DIMENSION_VALUE`，以及判断题被送进模型后出现 `CHAT_FAILED` 的缺口。调研见 [缺槽不猜](../research-choice-slots.md)。

## 决策

1. **Property 可声明取值字典。** `values: [{id, label, aliases}]`，最多 30 条，仅 STRING / INTEGER / BOOLEAN。Compiler 检查 id 可解析为该类型、词条不重复。这是领域配置，不是 `SELECT DISTINCT`。Studio 在实体「属性与来源」编辑。
2. **缺槽只出服务器选择题。** 用户说到字典维但没给取值 → `DIMENSION_VALUE` 选择题；规则词匹配但对象不唯一 → `CLAIM` / `SUBJECT` 选择题。`ChoiceQuestion.control` 只根据这些稳定语义种类选择 `SELECT` 或 `CARDS`，客户端不识别 `dimension`、`claimSubject` 等槽名，也不同时重复展示两套控件；客户端只提交 option id。`ABORT` 不猜测。
3. **判断题走引擎，不送模型。** Rule 的 claim / label / aliases 命中后，`try_direct_turn` 直接 `evaluate_claim`。这同时修掉判断题 `CHAT_FAILED`（原路径因「等于/吗」跳过直接计算，模型回合未提交可核验回答）。
4. **环比是 `PERIOD_OVER_PERIOD`，不是 `WINDOW_LAG`。** 在已钉住的年度上对同一聚合再算上一年，返回百分比。月环比仍 `TIME_GRAIN_UNSUPPORTED`。比率（NONE）不做环比。

## 不做什么

- 不开放窗口 LAG/LEAD。
- 不把未配置字典的列拿去 DISTINCT 当选项。
- 不让模型自填 `decisions` 或把自由文本当 SQL。

## 影响

CONTEXT 的 Property 定义、契约选择题、Chat 直接路径、采购/仓库/财务示例包与 Studio 属性字典编辑同步本决策。

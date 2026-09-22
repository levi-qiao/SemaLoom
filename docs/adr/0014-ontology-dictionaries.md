# 0014 — 本体字典驱动选择题，环比是查询算子

状态：accepted，2026-09-18。补齐 [ADR-0011](0011-semantic-query-planner.md) 已预留但未发射的 `DIMENSION_VALUE`，以及判断题被送进模型后出现 `CHAT_FAILED` 的缺口。调研见 [缺槽不猜](../research-choice-slots.md)。

## 决策

1. **取值来源可叠加，不必在本体穷举。** 选择题的存储 id 仍由服务器给出。显示名与用户说法按顺序取：
   - 领域包可选的 `Property.values`（小闭集、别名，Studio 可编辑）；
   - 接入 Mapping 声明的字典表/同表标签列（`physical.valueLabels`，SQL 或等价只读查询）；
   - 当前授权范围内该指标映射列的观测 DISTINCT（范围属性，见 ADR-0015）。
   领域包不再为运营维值维护一份完整名单；YAML 字典只覆盖需要别名或闭集校验的词。
2. **缺槽只出服务器选择题。** 用户说到字典维但没给取值 → `DIMENSION_VALUE` 选择题；规则词匹配但对象不唯一 → `CLAIM` / `SUBJECT` 选择题。`ChoiceQuestion.control` 只根据这些稳定语义种类选择 `SELECT` 或 `CARDS`，客户端不识别 `dimension`、`claimSubject` 等槽名，也不同时重复展示两套控件；客户端只提交 option id。`ABORT` 不猜测。
3. **判断题走引擎，不送模型。** Rule 的 claim / label / aliases 命中后，`try_direct_turn` 直接 `evaluate_claim`。这同时修掉判断题 `CHAT_FAILED`（原路径因「等于/吗」跳过直接计算，模型回合未提交可核验回答）。
4. **上一期是观测序列上的取值，不是窗口，也不是请求枚举。** `previousObserved` 把已等值约束的范围属性改绑到已授权观测的前一个值，结果是该期聚合。月环比在这条序列上同样成立，不能在进入本体之前判成 `TIME_GRAIN_UNSUPPORTED`。比率（NONE）仍不可做这种跨期合计。修订见 [ADR-0017](0017-compositional-analysis.md)。

## 不做什么

- 不开放窗口 LAG/LEAD。
- 不把未声明为范围属性或字典来源的任意列拿去 DISTINCT 当选项。
- 不让模型自填 `decisions`、选项 id 或把自由文本当 SQL。
- 模型可以把服务器给出的对象属性、口径和选项做成更自然的说明，但不能增删选项 id。

## 影响

CONTEXT 的 Property 定义、契约选择题、Chat 直接路径、采购/仓库/财务示例包与 Studio 属性字典编辑同步本决策。

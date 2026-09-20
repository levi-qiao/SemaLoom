# 0013 — 测量槽声明可加性，查询算子留在 SemanticQuery

状态：accepted，2026-09-18。在不引入 Calcite/Cube/MetricFlow 服务的前提下，补齐 [ADR-0012](0012-facts-and-business-vocabulary.md) 未写明的 Kimball 可加性，并删除已无调用者的 `analyze_population` 兼容层。权威分层与取舍见 [指标分层调研](../research-metric-layering.md)。

## 决策

1. **本体只声明测量是什么、沿哪些维可加。** 带单位的 Property（及继承它的 Metric 词条）可选 `additivity: FULL | SEMI | NONE`，默认 `FULL`。FULL 沿各维可 SUM；SEMI（库存、余额）只在单一年度 EQ 或按年度分组时允许 SUM；NONE（比率）禁止 SUM/AVG。Compiler 从测量槽继承到查询面 Metric。Studio 在属性行配置，不另开指标页。
2. **SUM/AVG/MIN/MAX/COUNT 是 SemanticQuery 算子，不是本体类。** 请求只传语义 Metric ID 与算子名。adapter 把 AVG 编成 Gray/Chaudhuri 的 `(SUM, COUNT)` 再相除，禁止把明细拉进 Python 求均值。非法组合返回 `ADDITIVITY_VIOLATION` / `UNSUPPORTED`，不静默改写。
3. **少量配置覆盖多种问答。** 同一测量槽在 Chat 中可问合计、平均、最值、计数、占比与同行比较；年/算子未说明时由服务端按可加性给出默认并标注置信度，或出选择题。不在 YAML 为每种问法复制 Metric。
4. **集合分析只有一条链。** Chat `prepare_semantic_query` 与 HTTP `POST /v0.1/semantic/prepare` + `/execute`。删除 `runtime/population.py`、`PopulationRequest` 和 `POST /v0.1/analyze`。不把 Mapping `PUSH_AGGREGATE` / 跨源中间量协议纳入本切片；PostgreSQL 已下推，OpenAPI 集合 AVG 仍是后续能力。

## 不做什么

- 不把 AVG/SUM 写进领域 YAML 或 Mapping SQL。
- 不引入 Cube、MetricFlow、Calcite 服务或第二套统计引擎。
- 不把跨源 `(sum, count)` 合并或 API 已聚合 GET 写成当前发行能力。

## 影响

CONTEXT、契约第 2/集合统计节、architecture 有界集合分析、DESIGN 属性行、示例包（库存与资产负债为 SEMI）与 Studio 同步本决策。查询与比较协议仍见 [语义契约](../spec/semantic-contract-v0.1.md) 与 [ADR-0011](0011-semantic-query-planner.md)。

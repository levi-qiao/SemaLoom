# 0011 — 同源 PostgreSQL 通用语义查询的规划与澄清契约

状态：accepted，2026-09-14。Q0 在隔离合成 PostgreSQL 上实测 Wren Python SDK 与 SQLAlchemy/SQLGlot 后选定。本决策修正 [ADR-0007](0007-in-process-source-composition.md) 中“首版不引入通用关系代数优化器”的范围：同源 PostgreSQL 现在允许**一份**受约束的语义分析计划并下推 SQL；跨来源仍是有界键查找，不引入第二套查询后端，也不开放调用方 SQL。

## 决策

1. **公共契约**是 `SemanticQuery` / `prepare` / `execute` / 选择题提交，类型在 `semaloom.core.semantic_query`。请求只含语义 ID 与类型值。不引入公共 semantic SQL 或 raw SQL 工具。
2. **主实现**（Q1）用现有 SQLAlchemy Core 生成**参数化** PostgreSQL，用 SQLGlot 做 AST allowlist、表列限定和血缘摘要。金额保持 `decimal.Decimal`。租户/授权范围应用到每个基础关系。
3. **Wren**（`wrenai` 0.14.0 / `wren-core-py` 0.8.0，Apache-2.0）作为第一候选已嵌入运行：`dry_plan` 与 `cube_query_to_sql` 能展开分组聚合。它不适配本契约的执行引擎，原因见下。不把 Wren 或 MetricFlow/Cube 服务纳入发行物。
4. **交互**：继续使用已安装的 `@earendil-works/pi-agent-core` / `pi-ai` 0.85.1 的 `beforeToolCall` / `afterToolCall` / `shouldStopAfterTurn`。网页选择题是 Python 持久化的 `NEEDS_INPUT` 协议；`terminate: true` 释放本轮 Node。不安装 coding-agent，不使用 `ctx.ui.select`。
5. 本体仍是唯一真源。不为 Wren 维护第二份 MDL。旧 `analyze_population` 在 Q1 中翻译到同一 `SemanticQuery` 链。

## Wren 实测后不适配的原因

隔离库 `127.0.0.1:55432/q0_synth`（非共享 5432、非 `semaloom_samples`）上：

| 检查 | 结果 |
|---|---|
| 财务模型分组 SUM、AND/OR、Top N | `dry_plan` + `query` 可运行；Arrow `decimal128` 对本例 `350.2800` 与 NUMERIC oracle 一致 |
| CubeQuery | 生成带字面量的 SQL；年份被写成 `'2024'` 字符串 |
| 参数化 | 失败：输出内嵌 `'tenant-a'`，无绑定参数 |
| `strict_mode=True` 拒绝物理表 | 失败：`SELECT ... FROM q0.tax_return` 仍被规划 |
| 信任范围落到每个基表扫描 | 失败：CTE 为 `FROM q0.tax_return AS __source`，租户谓词只在外层 |
| 主体 vs 总体 | 引擎无此作用域；`WHERE company_id=` 会缩小分母 |
| 声明的 MANY_TO_ONE 关系 | `dry_plan` 未注入 JOIN，仍引用未扫描的 `proc_org` |
| 窗口算子能力拒绝 | 失败：`SUM() OVER (PARTITION BY ...)` 被规划 |
| 依赖面 | `wrenai[postgres]` 拉入 DuckDB、PyArrow、pandas、boto3、OpenDAL |

因此不把 Wren 当作规划或执行真源。SQLGlot 30.18.0（MIT）+ SQLAlchemy 2.0 在同一库上生成 `%(tenant)s` 参数、Decimal 合计、主体/总体分母分离与带租户的 JOIN。

未同时引入 Cube 服务或 MetricFlow/dbt。SQLGlot 不是业务 planner。

## 首版能力与拒绝

同源 PostgreSQL 支持：EQ/NE/LT/LE/GT/GE/IN/BETWEEN 与 AND/OR/NOT；YEAR/MONTH 与业务维度分组；SUM/MIN/MAX/COUNT/AVG（AVG 遵守缺失政策）；ORDER/LIMIT；Top N；SHARE_OF_TOTAL、RELATIVE_TO_MEAN、STRICT_PEER；已声明且基数合法的同源 Link。50 只限制证据分页。

明确 `UNSUPPORTED`：窗口 LAG/LEAD/NTILE/自定义 frame、递归 CTE、跨源 SQL、raw SQL、UDF、用 DISTINCT 金额去重、把 NULL/缺失 COALESCE 成 0、float 金额、无界多对多。`SOURCE_ERROR` 可重试，不等于用户选择题。

迁移：下一方言在本计划稳定后经 SQLGlot transpile 另开任务；跨源不改走有界 Link。公共 SQL 入口需要替代本 ADR 与完整验证，Q0 不开启。

## 交互契约

`prepare` 返回 READY / NEEDS_INPUT / UNSUPPORTED / SOURCE_ERROR。选择题含 option id、业务标签、说明、服务器持有的类型化 `SemanticChoice`。提交含 `questionId`、`revision`、`optionIds`；`OTHER` 另带 `otherText`，由服务端并入原问题再 prepare，不把自由文本当 SQL 或计划补丁。过期、伪造、重复、串会话、版本变化由 `ChoiceError` 区分。ABORT（都不符合/暂不清楚）不产生猜测答案。Chat 在唯一指标已识别时可按最新年度与可加性合计作答并附置信度，这不是用户已提交的选择。会话恢复字段见 `QuerySessionState`。样例：[直接计算](../spec/samples/semantic-query-direct.json)、[两轮选择](../spec/samples/semantic-query-two-round.json)。

pi agent-core 没有网页选择插件；coding-agent 的 `ctx.ui.select` 不适配当前 headless Node。选择题由 Studio 自己的卡片实现。

## 影响

Q1 实现 prepare/execute 与 SQL 下推；Q2 将 Chat/harness 接到同一契约；Q3 渲染选择题与证据表；Q4 独立验收。本 ADR 不声称产品迁移已完成。

## 主责复验修订（2026-09-14）

上文“首版能力”是 Q0 冻结目标，不能当作全部已实现。实际可用集合能力限同源同事实表；跨表 Link JOIN、跨源、窗口和多指标联合排序/比较尚未关闭，返回明确不支持。实际执行使用受限结构生成参数化 SQLAlchemy statement、SQLGlot 检查；不是已经引入通用关系优化器。

物理 SQL、字段/来源检查和事务由 PostgreSQL 接入层拥有，runtime 不导入接入实现或 SQL 库。运行时只拥有语义准备、选择与执行调度。一次执行的全部指标、分母、明细共用只读 REPEATABLE READ；返回一致性范围为单来源。计划引用绑定完整请求、租户和 release，不能只凭相同 SQL 形状跨值/版本使用。

迁移删除旧 Chat 集合工具和重复说明/意图执行分支；旧 HTTP analyze 只作为请求翻译保留。选择协议新增 AGGREGATION、COMPARISON、FILTER（服务器持有类型化谓词），模型不得自填 decisions。完成回答和清除 pending 原子保存。已保存的旧 PlanRef 不能在新摘要算法下执行，应重新 prepare；原始 semantic release 定义不自动修改或重新激活。验收与限界见 [主责收口](../semantic-query-closure.md)。

# 0016 — 语义表达式经受限 IR 下推，SQL 不进入领域本体

状态：accepted，2026-09-21。调研见 [通用语义模型到关系代数/SQL 的安全规划](../research/semantic-to-relational-planning.md)。

## 决策

1. Domain ontology 只保存 semantic ID、类型、粒度、Link、可加性和闭集 typed `Expr`。不接受 SQL、`${...}`/`{{...}}` 占位符、物理表列、join/filter 文本或任意函数名。
2. 请求只提交 `SemanticQuery` 的 typed filter/group/aggregate/link。Jev 只能在服务端给出的语义候选集合内分类、排序或打分，不能选择表、列、函数、join 或生成物理计划。
3. Integration Mapping 拥有物理关系与字段绑定。PostgreSQL mapping 在编译期验证标识符及字段形状；结构值不会再被强转为字符串，SQL 片段不能冒充列名。
4. 派生指标先使用已经过 Compiler 引用和类型检查的 `Expr`，再由 adapter 从闭集 AST 构造私有 SQL AST。当前 PostgreSQL 数值下推支持引用、Decimal 字面量、加减乘除和 `ROUND_HALF_UP`；未知操作或无法保持语义的来源布局明确拒绝。
5. EAV 指标若由不同固定筛选选中不同行，不能把相同 `valueColumn` 当成同一行的多个输入。没有显式 pivot/关系计划时返回 `LINK_ANALYSIS_UNSUPPORTED`，不能生成看似成功但口径错误的 SQL。
6. 后续按 `SemanticQuery → LogicalPlan → CapabilityPlanner → adapter PhysicalPlan` 演进。物理 computed field 只能作为已发布 semantic expression 的可验证优化绑定，不能替代业务公式或引入 `computedSql` 公共接口。

## 依据与影响

R2RML/Ontop 将 ontology target 与受信任 source mapping 分开；SPARQL、Calcite、Substrait 和 Volcano 共同表明逻辑算子、typed scalar expression、能力选择及物理实现应分层。SQL-first 项目的表达式字段可以作为物理层参照，但不成为跨 provider 的领域契约。

本决策补齐的是安全且可重放的最小竖切，不声称已完成通用成本优化器、多源关系代数或任意 computed field。SQLGlot 的生成后检查继续作为纵深防御，不代替 typed IR、mapping ownership、租户谓词和值参数化。

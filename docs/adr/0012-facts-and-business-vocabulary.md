# 0012 — 事实在表，业务层只补充语言

状态：accepted，2026-09-15。修正领域包把每个来源数字写成独立 Metric 文档、并为其各写一条 Mapping 的做法。不改变 Query/Claim/Action 的执行不变量，也不把表名、列名或 SQL 开放给调用方。

## 决策

1. **事实层是表，接入层一次绑定。** 一张事实表对应一条 ObjectType Mapping：宽表用 `propertyColumns` 列出列；EAV/科目表用同一 Mapping 的粒度列（含科目码）加金额列。不为每个科目、每列金额复制 Mapping。
2. **业务层是补充语言，不是目录穷举。** Domain pack 维护 ObjectType、身份、Link、需要判断的 Rule/Claim/Policy，以及少量 Metric **词条**（稳定 ID、中文名、别名、口径、可选 `select`）。词条指向对象上已映射的数值槽，不重复声明 grain/unit/表列。表里有、但业务从未命名的码，不必写进本体。
3. **Metric 是查询面一级公民，作者面是编译 IR / 可选词条。** 作者写紧凑词条（或依赖默认 `{objectType}.{property}`）；Compiler 从对象属性/Mapping 继承 `valueType`、`unit`、`grain`、`population`，并合成 Runtime 已认识的 Metric Mapping。`fetch_metric`、SemanticQuery、Rule 输入、Chat 发现**必须**继续使用稳定 Metric ID——这与 LookML measure / MetricFlow metric 的查询入口同级，不是「取消指标」。禁止把「非物理种类」误读成「Agent 不要用 Metric」。
4. **公式不进目录。** 来源已算好的数只映射。只有 SemaLoom 必须计算、并作为业务结论使用的，才写 Rule；`outputMetric` 仍是派生词条，不写物理 Mapping。
5. **带单位的属性是测量槽。** `Property.unit` 标记计量字段。对象点查默认不读取这些槽，避免把 EAV 多行误当成实体 1:1 属性。宽表上的金额就是对象属性；Compiler 自动生成查询用 Metric IR。Studio 不为指标提供独立配置页；可选词条在实体属性语境维护。
6. **合计不是本体。** SUM/AVG 等是 SemanticQuery 的算子，adapter 编译成参数化 SQL 函数。Agent 和 UI 只传语义 Metric/属性 ID 与运算名，不传 SQL。

## 作者形状

```yaml
# 对象：业务概念 + 测量槽
properties:
  - id: amount
    valueType: DECIMAL
    unit: CNY
# 词条：业务语言
kind: Metric
id: tax.operatingRevenue
objectType: tax.Taxpayer
property: amount
select: { measureCode: operatingRevenue }
label: 营业收入
# 接入：一表一条
kind: Mapping
target: tax.Taxpayer
physical:
  table: tax_metric
  grainColumns: { taxpayerId: taxpayer_id, taxYear: tax_year, perspective: perspective, measureCode: metric }
  propertyColumns: { amount: amount }
```

Compiler 将词条展开为带 grain/unit 的 MetricDef，并生成 `tax.operatingRevenue.pg` 这类 Mapping，供现有 Provider 使用。

## 不做什么

- 不让请求携带表名/列名/SQL。
- 不按 INFORMATION_SCHEMA 自动生成 Metric 文档。
- 不把 grain、单位、可否沿时间求和只写在 SQL 类型里。
- 不删除 Metric 作为稳定语义 ID 的查询入口。

## 影响

CONTEXT、契约第 2/3 节、architecture 配置边界、DESIGN 实体页、示例包与 Studio 指标表单同步本决策。替换 [ADR-0006](0006-independent-integration-layer.md) 中“领域包拥有指标定义”的理解：领域包拥有**业务词条**，不拥有来源科目清单。执行接口仍见 [语义契约](../spec/semantic-contract-v0.1.md)。

## 修订（2026-09-18）

测量槽增加 Kimball 可加性；SUM/AVG 仍是查询算子。删除 `analyze_population` 兼容入口。见 [ADR-0013](0013-measure-additivity.md)。

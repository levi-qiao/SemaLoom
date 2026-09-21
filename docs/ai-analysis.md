# AI 业务分析使用与验收范围

后续已新增 [内置 Chat Harness](chat-harness.md)，可直接在页面用 pi + 百炼测试；本页保留通用业务工具和分析语义说明。

当前交付聚焦一条能运行、能对数的路径：业务定义 → 实例定位 → 语义取数 → 确定性计算 → 带来源的解释。领域定义由项目维护者编写，AI 无需自行猜表、拼 SQL 或计算财务结论。新增同协议业务主要增加 domain 定义与 integration 绑定；本轮以申报和审计分析验证这条路径。

## 当前可用

`examples/financial-review` 包含 6 个对象、8 个关系、14 个指标、5 个规则（3 个判断和 2 个派生计算）。其中 `finance.ReviewCase` 固定到一份选定报告及其配对申报，含企业、年度、实际期间、配对策略、是否唯一候选、来源复核状态和抽取状态。SQL 视图属于独立 integration，核心没有财税表名或因子枚举。

| 问题 | 语义定义 | 结果含义 |
| --- | --- | --- |
| 申报利润与报告利润差多少？ | `finance.review.profitDifference` | 申报减审计，单位 CNY；缺任何输入则无差额 |
| 两份利润一致吗？ | `finance.review.profitMatches` | 绝对差额 ≤ 0.01 元 |
| 资产等于负债加权益吗？ | `finance.review.balanceBalances` | 绝对差额 ≤ 1 元 |
| 净利润等于利润总额减所得税费用吗？ | `finance.review.netProfitBalances` | 绝对差额 ≤ 1 元 |
| 资产相对负债的比率？ | `finance.review.debtRatio` | 负债/资产，无量纲；不能合计或平均 |

容差是本包的演示分析配置，不是法律、税务或审计标准。政策覆盖 2024/2025；其他期间没有适用政策。金额单位的依据是上游抽取归一化、最终值及投影写入的代码契约，尚未逐份核对报告原文。`unreviewed` 不能解释为已审定；mock 流转状态与真实复核无关。多候选使用最新样本的事实明确保留，不冒充唯一正式版本。

业务定义、映射和确定性结果可以由我们编写并自行验证。仅凭这些，不能证明未知企业私有口径或原始抽取结果正确。能从已有数据、代码与定义确认的内容直接落实；无法确认的内容保留依据和限制，不让 AI 编造。

## 接入 AI

应用启动后 `GET /v0.1/agent/tools` 返回五个工具的输入 JSON Schema、HTTP method/path 和使用说明。工具数量不随行业包增加。支持现有 demo Bearer；Studio 会话也可读，POST 需 Origin/CSRF。外部 MCP host 可连接 `/mcp/` 的官方 Streamable HTTP transport，使用同一 Bearer 身份执行语义查询、规则评估与定义解释。

已有能运行终端命令的 AI 可直接使用仓库脚本：

```sh
uv run python ops/ai/call_tool.py list
printf '%s' '{"q":"利润"}' | uv run python ops/ai/call_tool.py search_semantics
printf '%s' '{"semanticId":"finance.ReviewCase"}' | uv run python ops/ai/call_tool.py describe_semantic
printf '%s' '{"objectType":"finance.ReviewCase","filters":{"taxYear":2024},"properties":["companyName","periodStart","periodTo","uniquePair","sourceReviewStatus"],"limit":20}' | uv run python ops/ai/call_tool.py find_objects
```

默认地址 `http://127.0.0.1:8000`、demo token `tenant-a-analyst`，可用 `SEMALOOM_URL` / `SEMALOOM_TOKEN` 覆盖。脚本不保存返回数据。其他 AI host 按目录 Schema 注册 function tools，再由 host 调用对应 HTTP 路由；模型参数不能指定 SQL、来源 URL 或权限。

可把下面的指令交给问答 agent：

```text
使用 SemaLoom 的只读业务工具回答问题。先运行 ops/ai/call_tool.py list，读取工具目录。
用 search_semantics 和 describe_semantic 确认对象、指标、口径、单位、粒度和规则含义。
用 find_objects 按企业和年度定位实际实例；不能猜 ID。搜索是精确属性过滤，hasMore 代表结果不完整。
多候选且用户没有指定选择依据时，列候选并澄清；不擅自挑一条，不把样本列表说成企业全量。
从选定实例读取 periodStart/periodTo、uniquePair、pairingPolicy、unitBasis、sourceReviewStatus 和抽取状态。
用 semantic_query 读取指标或派生差额，用 evaluate_claim 执行规则；金额计算以引擎返回为准。
查询期间按对象实际半开期间填写，例如 2024-01-01 到 2025-01-01。
同一回答核对各结果 releaseDigest；若版本不同，重新获取一致版本的数据，不能混用。
回答说明选定企业/年度/样本、口径、单位、数值、规则结果、缺失或失败原因与来源证据。
NULL/MISSING 不是零，UNAVAILABLE 是运行失败，UNKNOWN 不是 FALSE。
TRUE 只代表所述数值规则成立；不能因此宣称审计通过、申报合规或抽取准确。
上游金额使用归一化 CNY 契约；来源 unreviewed 和非唯一版本必须说明。mock 状态不作真实证据。
遇到本包没有定义的指标或业务口径，明确未支持，不自行拼 SQL 或发明定义。
```

确定性业务分析不依赖模型；可选 Chat 需要接入方配置模型并独立评测。离线测试和合成示例不代表通用自然语言准确率，验证方法见 [分析质量](analysis-quality.md)。

## 已验证与后续

公开回归覆盖 typed Rule、非布尔 Claim 拒绝、身份存在性、非法/非有限数、搜索候选与租户边界、完整粒度、错误期间和证据引用。数值期望应从基础表独立计算，不调用被测规则生成答案；企业来源数据的真实性仍须由接入方复核。

公开 quickstart 只使用合成数据。实际业务配置与私有样本不得进入 Git 或发行物；local-dev 的运行结果不能被称为已批准生产 release。

当前已覆盖 JWT 签名、issuer、audience、expiry 和必需身份 claims，但不包含外部 IAM 撤销目录、细粒度字段授权、MCP Action、Action 业务写入恢复、Rule 可视化编辑器或大图扩容。这些仍保留为后续能力，不能把未实现项说成完成。所有公开使用与生产要求仍见 SECURITY 和原验收文档。

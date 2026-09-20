# 独立测试 agent 提示词

本轮只验“业务定义 → 实例 → 取数 → 判断 → 解释”的可用性与准确性。主实现说明见 [AI 分析](ai-analysis.md)，旧 G1–G5 和广义生产收口清单不再作为本轮新增开发任务。

可以同时派 4 个 agent。它们只写各自测试、复现与报告，不修改产品实现或互相修改测试。收到报告后交回主 agent 统一修复、复验。

## 所有 agent 共用前缀

```text
项目为当前 SemaLoom 仓库。遵守 AGENTS.md，先读 CONTEXT、architecture、PLAN、semantic-contract、acceptance、SECURITY、docs/ai-analysis.md，再执行本任务。
你的职责是独立验收，不重写架构、不增加产品功能。检查当前 diff，保留其他人的工作。
不要假定主实现的测试通过就代表你的结论。自己构造期望值、反例和完整请求，记录实际响应与依据。
测试代码只写 tests/independent/<你的任务名>/，私有证据和报告写 .agents/analysis-tests/<你的任务名>/handoff.md。
需要数据库写入时启动自己的临时 PostgreSQL 集群和独立端口；数据库名用 semaloom_g4_tax/orders/suppliers/meta，兼容既有 G4 隔离检查，但服务器不得使用本机 5432。每个 agent 独占集群、应用端口和浏览器存储。
禁止在现有 semaloom_samples、semaloom_sample_meta 或 remote-dev 加载 fixture、重置或运行写入型测试。远端不需要再访问。
若检查已有真实样本，仅使用 .agents/local-data/runtime.env 的只读账号及 localhost:8000 只读 API；不要打印连接密码、保存完整财务结果或把真实行写进测试/源码/报告。
可自主管理自己的临时服务；只清理自己创建的文件/进程。所有 pytest --basetemp、浏览器输出指向本任务临时目录。
每条检查标注 PASS/FAIL/NOT_RUN，失败给最小复现、期望与实际、影响和疑似责任模块。基础设施不可用不能冒充失败业务或通过。
验收重点是准确、通用、能使用。JWT/细粒度授权、Action 写恢复、实际 MCP transport、Rule 可视化编辑及大图压力不在本轮关闭范围；记录已有未完成事实即可，不扩展开发。
最终报告包含结论、检查清单、执行命令、测试文件、缺口与清理记录。不提交、不发布、不调用付费模型或联系他人。
```

## Agent A：独立业务对数

```text
任务名 business-values。
目标：以独立期望验证 financial-review 的配对、金额、状态和三条规则，避免“测实现等于实现”。
阅读 importer、integration/review-view.sql 和 domain 定义。用合成基础表建立 TRUE/FALSE/UNKNOWN 案例，真实执行视图、PostgreSQL provider 与 HTTP。
至少覆盖：利润差额正负与 0.01 边界；资产/负债/权益与净利润等式的 1 元边界；零、负数、大金额、小数；缺字段、SQL NULL、not_disclosed、extraction_failed、非数字、同因子多行；多个申报/报告候选；跨年和跨租户。审计非 observed 不得得到可用金额，多行不能隐藏选第一条。
期望由基础记录与独立 Decimal 算式得出，不调用 evaluate_rule/evaluate_derived_metric 生成期望。
只读复核本机 10 样本：ops/data/verify_analysis.py 是入口参考，不是你的独立验收答案。核查 normalized CNY 契约、sourceReviewStatus、uniquePair 和 mock 界限，不能把真实原文准确率标成已验证。
报告哪些业务问题可以回答、哪些必须 UNKNOWN/澄清；不要求用户重新编写已有数据可确认的本体定义。
```

## Agent B：通用语义与错误边界

```text
任务名 semantic-boundaries。
目标：确保核心能力不是为财税样例写死，错误不会悄悄变成数字或 TRUE。
用一个最小第三业务包（例如库存质量检查）验证 STRING/BOOLEAN/DATE/DATETIME 与 Decimal Rule、派生 Metric、属性读取、稳定标量身份及搜索，不修改 core/compiler/provider。
覆盖：非布尔 Claim 编译拒绝与运行防线；不存在属性、混合类型、重复输出、重复输入、规则依赖环、表达式深度/节点/数值限制；可选输入三值逻辑；除零/NaN/Infinity；整数非整数返回；身份单独查询不存在对象；复合身份必须传完整键集，禁止截取第一键。
验证完整粒度、未知/冲突绑定、旧别名与标准身份冲突、口径歧义、业务期间非法/跨年/与样本不符。原 GQ07 缺年度现在应在读库前 INVALID_BINDINGS；另造完整粒度真实重复行验证 CARDINALITY_VIOLATION。
验证 query/claim sourceActivities、observedAt、ruleId/evidenceRefs 与 releaseDigest 可对应；租户切换不串值。有限只读 API 不支持实例列表时应明确 SEARCH_NOT_SUPPORTED。
测试误差和遗漏写报告，不擅自放宽契约或修产品代码。
```

## Agent C：真实 AI 工具使用

```text
任务名 ai-questions。
目标：你作为问答 agent 使用五个只读工具，验证从自然语言到可追溯答案是否顺畅。
先遵守 docs/ai-analysis.md 的 AI 指令。使用 ops/ai/call_tool.py 或目录所列 HTTP，不通过 SQL/读测试答案代替问答工具。
先搜索并列出现有企业年度样本，自行选择一个用于验收且在问题中明确样本。问：申报和报告利润各是多少、差多少；两者是否一致；资产等式是否成立；哪些数据缺失；来源是否人工复核；换年度是否误读；“收入”未说明口径时怎么处理；不存在指标/企业怎么办。
每个问题记录工具调用顺序、选择依据、结果概述、单位/期间/口径/来源限制。私有数值不进入源码或可公开报告。
用合成数据或只读接口反例验证：多候选、hasMore、UNKNOWN、来源不可用、版本切换、无支持业务口径。不能仅做关键词断言或固定自然语言到 JSON 的字典映射就称模型评测。
不要使用外部付费模型。报告你这个 agent 的实际问答轨迹及失败，不推断所有模型都能达到同样准确率。
```

## Agent D：Studio 与可重建性

```text
任务名 studio-flow。
目标：用户能在页面理解模型、配置映射并定位问题，且新分析定义不会破坏既有操作。
额外读 DESIGN 和 ADR-0008，需要浏览器时使用 ego-browser skill。优先在自己的合成库/应用端口测试，禁止改动用户真实样本工作区。
执行现有前端类型检查与 Playwright；用最新 financial-review 合成模型检查 6 对象、8 关系、13 指标和 4 规则显示。规则当前只读允许；不要把缺 Rule 编辑器定为本轮阻塞。
测试实体、属性、Metric、数据库/API Mapping 的编辑保存、刷新、校验错误定位、取消、脏状态、版本冲突；ObjectType.period 新字段必须导出/导入/编辑往返保留。
在隔离环境完成一条配置→验证→不同测试身份审核→激活→查询链；确认草稿与当前运行版本区分。核查不支持的 Metric/Rule/period 配置不会被界面静默丢掉或错误保存。
用日常宽度和小屏检查中文标签、控件状态、错误恢复、主操作是否协调；不扩展成新视觉系统或压力工程。
检查构建产物能启动、静态资源与后端一致，公共合成 quickstart 不依赖私有样本或 TI 路径。真实业务数据/secret 不进入发行物。
报告影响跑通的 P0/P1 与可后置体验问题，附可复现证据。
```

# Semantic Contract v0.1

状态：架构语义基线，非完整已实现标准。MUST 表示实现验收要求，SHOULD 表示有记录的理由时可偏离。本文固定语义、安全和一致性不变量；具体字段、状态命名、接口签名、错误映射和预算数值是供执行 agent 完善的草案，不是冻结的 wire protocol。

T01 负责正式 DSL/API 结构，T02–T06 完善运行行为，T09 完善 Studio 管理契约；JSON Schema 管结构，Compiler 和 Runtime 管语义及跨字段约束。只维护一份可执行类型定义并导出 schema，用测试防止导出格式和规范偏离；不让 Pydantic 类型强制转换意外扩大接受范围。

## 1. 标识、类型与发布

- Semantic ID 使用稳定的带命名空间标识，例如 `tax.operatingRevenue`；展示名称和 alias 可变，ID 不跟随翻译变化。
- 外部定义共享 `apiVersion`、`kind`、`id`、`version`。Property 可嵌入 ObjectType，Evidence 是运行结果，不强行为每个概念建立独立顶层文件。
- 同一 bundle 中 `(kind, id)` 唯一，所有引用解析成精确版本。原始 YAML 由安全解析器读取，拒绝重复键、任意类型标签、过深结构和超额 alias 展开。
- 受审核 Git commit 或 Studio 草稿 revision + 可信发布者身份构成审核证据；两种编辑入口通过同一 Compiler 与发布协议。DSL 内自行填写的 `approvedBy` 或 `status: APPROVED` 不能授予发布权限。
- bundle payload MUST 含格式版本、所有定义及精确依赖的摘要、Compiler 版本、来源 commit（若使用 Git）。离线编译可生成 payload 及内容摘要。发布审核和目标环境验证证明位于独立 envelope，绑定 payload digest 与环境绑定版本；T04 激活时要求可信证明齐备。环境重新验证不改变语义 payload 摘要，也不让离线编译结果自动获得激活权限。
- 请求绑定一个不可变 release digest，同时记录 runtime build、执行 profile 和环境绑定版本。部署指针是可变索引，更新带 expectedRevision；回滚只改变后续请求。不可变发布物和审计保留规则按环境配置；完整绑定规则见第 11 节。
- 领域定义与 Integration Binding 分离：前者声明业务语义，后者承载 Mapping、Action 到物理 operation 的绑定及 adapter profile。两者分别版本化，其精确依赖、接入产物和摘要一起纳入 release payload；环境连接和秘密引用由第 11 节管理。领域包不含物理表列、URL 或厂商类型。
- Domain Pack 声明包 ID/version、支持的契约版本、拥有的 semantic ID 命名空间及精确依赖版本/摘要。T01 用本地声明文件解析依赖并封装进 bundle；缺失依赖、循环包依赖、重复命名空间归属或冲突定义均拒绝，不按加载顺序覆盖。跨包引用必须来自声明的依赖。T07 验证税务与采购包组合加载。
- v0.1 拒绝未知核心字段。扩展只在声明过 schema 和语义的命名空间内引入；不以随意 `extensions` 绕过 Compiler。

## 2. Object、Metric 与 Link

ObjectIdentity = trusted tenant + ObjectType ID + 声明顺序/规范化后的 identity keys。PK 是来源定位，不能自动替代跨系统业务身份。跨系统身份对应必须显式 Mapping。

Metric MUST 声明 valueType、维度、grain、unit 和聚合行为。Property/Metric 的区别是业务含义，不是字段多寡；不能为减少建模工作把每一个抽取字段都改叫指标。

V0.1 指标查询先支持精确 grain 点查，所有必需维度必须绑定。聚合默认 `NONE`，明确声明支持的维度聚合以后才开放；收入可能按月份求和，资产余额通常不能沿时间求和，比率不能直接求平均。表达式、分组和任意 ad-hoc JOIN 不进入 v0.1 Query。

金额通过十进制字符串传输，在 Python 中以 `decimal.Decimal` 运算。显式设置计算 context 的 precision、rounding 和 traps，不依赖默认 28 位精度；拒绝 NaN、Infinity 和隐式 float 构造。单位、币种、scale 和舍入位置来自 Metric/Rule；禁止隐式汇率、单位转换或二进制浮点中转。需要转换时引用有版本的显式转换定义及来源。

Perspective 是 grain 的一部分。只有实际业务等价才批准 alias；“营业收入”“销售收入”“主营业务收入”不能仅凭相似度配置成同义词。口径含义发生变化时引入新 ID 或兼容性声明，不能保证任何政策变化都只改 Mapping。

Link MUST 声明方向、源/目标类型、身份绑定、基数（ONE/MANY）、支持的遍历和安全范围。反向遍历不是自动获得的能力。路径长度和 fan-out 受第 7 节预算控制，超限则终止，不能截断后继续声称完整。

## 3. Mapping 与来源选择

一个 ObjectType 可有多个 Mapping：不同属性/指标可分别来自不同数据库或 API，同一目标也可有多个候选。ObjectType 不携带唯一 datasource/table 字段。每条 Mapping 必须绑定可信租户及完整业务身份、对应属性/指标、类型、grain 和适用上下文；候选选择遵循下述规则，不能按表列名或来源返回顺序合并对象。

Mapping 属于接入声明，引用领域定义；公共 Compiler 校验目标、类型与引用，协议专属字段由接入 adapter 校验并编译。Core 使用中立的能力与计划引用，不解析 SQL AST 或 OpenAPI schema。Mapping 至少描述：目标、Provider、物理字段绑定、固定维度、有效业务范围、来源修订选择、预期基数、单位转换（若有）、sourceRef 提取和零行完整性契约。

先按语义等价、口径、业务时间、身份范围、来源修订和能力过滤候选，再按确定的显式优先级/成本选择。成本不能替代口径；“权威”不是无条件优先级。仍有多个非等价候选时返回 `AMBIGUOUS_MAPPING`，不随机取第一条。备用来源只有被声明等价并获批准时才可使用。

零个候选是 `NO_MAPPING`；已存在 Link 却无法形成合法路径是 `NO_PATH`。它们是模型/能力诊断，不是业务 FALSE。多个来源返回同一 grain 的冲突值是 `CONFLICT`，单一来源超出声明基数是 `CARDINALITY_VIOLATION`；都不能静默任选一行。

Compiler 分两类验证：

1. 离线：结构、类型、引用、依赖循环、维度覆盖、Rule 输入、权限引用、Policy 区间重叠及声明覆盖范围。
2. 联机契约：针对具体环境读取受限元数据/样例，验证表列、类型、唯一性假设、凭证权限、API 行为和完整性。记录目录快照摘要与检查时间；发布证明不保证之后不会 schema drift。

缺少数据源时可以离线 compile，不能伪造“联机验证通过”。生产激活要求目标环境契约验证；Runtime 遇到 schema drift 应明确失败。

## 4. Query 与执行上下文

以下是精确指标点查的接口示意；T01 将其与类型模型、正反例和 JSON Schema 一起定稿。v0.1 先开放这个有限能力，不提前增加通用查询语言。

```json
{
  "apiVersion": "semaloom/v0.1",
  "select": [
    {
      "metric": "tax.operatingRevenue",
      "bindings": {
        "taxpayer": "TAXPAYER-A",
        "taxYear": 2024,
        "perspective": "TAX_RETURN"
      }
    },
    {
      "metric": "tax.operatingRevenue",
      "bindings": {
        "taxpayer": "TAXPAYER-A",
        "taxYear": 2024,
        "perspective": "AUDIT_REPORT"
      }
    }
  ],
  "context": {
    "businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"},
    "scope": {"jurisdiction": "CN"}
  }
}
```

服务端注入 `requestId`、trace、tenant、actor、delegation（若有）、环境、releaseDigest、authorizationRevision、deadline。调用方提供的业务维度只是过滤请求，不授予这些对象的访问权限。凭证或 tenant 不能从 LLM 生成的 JSON 获得信任。

Schema 通过之后，Runtime MUST 检查 Metric 存在、所有维度名和类型、日期合法且 from < to、时间与维度一致、单位匹配、选择项重复、预算及权限。以 `taxYear` 推导期间是税务领域适配的声明，不写入 core，也不默认全球企业都使用公历财年。

任意表名、列名、SQL、URL、Rule 表达式和授权决策均不能作为业务查询字段。`search_semantics` 返回有权限的候选标识及其含义；`semantic_query` 只执行已确定的 ID。

V0.1 Query 还必须覆盖通过 ObjectRef（ObjectType + identity keys）按批准属性点查对象；这是 Action 前提读取的公共语义能力。Metric 点查与 Object 属性点查可以是同一接口的两个类型化选择分支，不新增行业专用 endpoint。可选根 ObjectRef 供 Planner 通过批准 Link 解析必需身份绑定；调用方不提供物理 JOIN 或路径表达式。目标需要 ONE 却解析为 MANY 时返回基数错误；首版不开放无限列表遍历或隐式聚合。

批准发布的 `Rule.claim` 声明可搜索的命题 ID、输入/对象范围及 Policy 绑定；`evaluate_claim` 接受此定义 ID 与业务上下文，返回单独的 evaluation ID。存在性判断是显式命题类型，执行第 5 节的完备性规则；不是将所有点查结果自动转换成布尔。这样无需另造通用“意图程序”，也不会让 Agent 猜测哪个运行结果 ID 是可执行定义。

语义发现支持按精确 ID 查看有权限的定义摘要、必需参数及指定期间的政策绑定，供“2024 与 2025 是否同一规则”使用；不展示未授权原始表达式或物理字段。历史选择只能指定可访问的 release，不能指定任意文件/URL/连接；未指定则使用当前环境激活版本。MCP/REST 如何组合发现与描述操作由 T06 细化，以上能力不能遗漏。

## 5. Observation、Claim 与诊断

T01 定义 Observation/Fact、Claim 与诊断的结构化类型，T02/T03 证明运行语义。不同状态使用可区分的类型分支，避免 `value: null` 同时代表未查询、查无数据、权限拒绝和空值。

| Observation | 含义 | 数值规则必需输入处理 |
| --- | --- | --- |
| PRESENT | 得到唯一且类型有效的值 | 正常计算，数值零仍为 PRESENT |
| MISSING | 成功完成指定查询范围但没有匹配观测 | UNKNOWN / MISSING_INPUT |
| NULL | 找到记录但该字段明确为空 | UNKNOWN / NULL_INPUT |
| UNAVAILABLE | 来源故障、超时或不完整，不能确认值 | UNKNOWN 并带运行诊断；整体响应为 PARTIAL 或 FAILED |

权限拒绝在读取前产生 `FORBIDDEN`，不能包装成 MISSING；按防枚举策略可对外统一不披露资源存在性。错误信息、sources、discovery 和 explain 均需同样授权。被遮蔽数值不能给规则当作原值计算；若需允许敏感值派生的结果，必须有单独经过审查的派生权限策略，V0.1 默认拒绝。

`exists(X, scope)` 的 TRUE/FALSE 与任意 Rule 的 Claim 不同。只有全部满足下列条件，零行才证明存在性 Claim 为 FALSE：

- Mapping 对该命题、业务时间与范围有已审核的完备性承诺。
- 查询成功，分页耗尽，无超时、截断或隐式遗漏。
- 授权后的可见范围与命题范围完全一致；受限可见结果不证明全局不存在。
- 来源修订/批次覆盖该范围；Source 的“权威”标签本身不证明抽取完成。

缺少任一条件则 UNKNOWN。有一行空金额可以证明记录存在，但不能证明金额为零或收入相等。

Claim = `claimId + predicateVersion + context + truth + reasonCodes + evidenceRefs`。truth 仅 TRUE/FALSE/UNKNOWN；错误以独立 diagnostics 返回，不增加第四个真值。

对数值 Rule，先检查所有声明的 required inputs；缺少即 UNKNOWN，不让表达式短路掩盖缺失。业务明确允许默认值时必须在经审核 Rule 中声明，Evidence 记录替代行为。除零、溢出、非法单位是 `RULE_EVALUATION_ERROR`，单个 Claim 可为 UNKNOWN，但请求不能标记完全成功。

Claim 之间显式组合采用强 Kleene 三值逻辑；这不同于数值规则的输入预检：

| A | B | A AND B | A OR B |
| --- | --- | --- | --- |
| TRUE | TRUE | TRUE | TRUE |
| TRUE | FALSE | FALSE | TRUE |
| TRUE | UNKNOWN | UNKNOWN | TRUE |
| FALSE | FALSE | FALSE | FALSE |
| FALSE | UNKNOWN | FALSE | UNKNOWN |
| UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

AND/OR 交换成立；NOT UNKNOWN = UNKNOWN。V0.1 无需开放任意 Claim 组合语言，但测试采用此表，防止未来自创不一致逻辑。

执行状态与真值正交：`SUCCEEDED` 表示请求完整执行（允许因真实数据缺失得到 UNKNOWN）；`PARTIAL` 表示显式允许的分析请求中某些依赖运行失败；`FAILED` 表示无法完成请求。纯指标查询默认严格失败，不默默忽略失败选择项。分析模式的部分失败策略必须在其操作契约中声明。

## 6. Rule 与 Policy

Rule 声明输入、输出类型、确定性表达式和资源预算。执行环境无网络、文件、随机数、隐式当前时间和动态代码装载。输入先归一化为精确类型；表达式发布时解析及类型检查，运行时复用编译产物。

首版采用我们拥有的受限 typed expression IR：字面量、命名输入引用、算术、比较与必要布尔组合；精确算术使用 Decimal。表达式没有循环、递归函数、任意属性访问、import、Python `eval/exec` 或任意 callable 注册。按案例只增加必要操作，T01/T03 定稿具体序列化格式及运算表，不另写通用文本语言 parser。

T03 必须证明精度、舍入、静态错误检测、除零、超额数值位数和节点/深度预算。计量单位与 required inputs 在编译/执行前检验。

Policy 定义类型化的适用范围和生效区间；Rule 定义计算。适用维度及允许值由领域包声明，core 统一进行精确匹配。`jurisdiction` 是税务示例维度，不是所有领域的必填字段；采购可使用组织等维度。缺少必需维度或维度未声明时拒绝，不隐式扩展为全局适用。V0.1 只支持声明的精确范围，不引入任意条件或隐式范围优先级。统一使用半开区间 `[effectiveFrom, effectiveTo)`，结束空值代表无上界，禁止混用包含末日的示例。

V0.1 对一个完整 businessPeriod 选择一个覆盖它的 Policy version。同一适用范围内重叠是编译错误；覆盖范围内缺口是编译错误，声明覆盖范围外是运行时 `NO_APPLICABLE_POLICY`。跨越版本的期间返回 `POLICY_PERIOD_SPLIT_REQUIRED`，不暗选第一天或最后一天。

`2024` 只表示业务年，不证明使用“2024 年发布”的法规。规则可能追溯修订。当前环境 release 对历史业务重新评估，与固定历史 release 查看当时结论，是两个显式操作；Evidence 记录 businessPeriod、policyVersion、ruleVersion、releaseDigest、evaluatedAt。首版用不可变 release 支持这一区分，不先实现完整双时态数据库。

所有税务数值规则及名称在合成示例中标明“演示，非有效税法”。真实 Policy 参数、适用条件及日期由业务专家审核，未获得审核只运行合成 fixture。

## 7. Provider、Planner 与缓存

接入层实现 ReadProvider 与独立 ActionExecutor，其公开输入输出使用 core 定义的中立类型。增加协议实现通过 app 注册，不改公共 Compiler/core。adapter 必须遵守授权 scope、预算、完整性与错误语义，不能把业务规则放入协议转换。ReadProvider 的能力声明至少覆盖支持的目标类型、过滤、投影、批量、快照和完整性；Planner 只能生成 adapter 声明支持的操作。SQL 必须由受限结构生成，值参数化，标识符仅从已验证 Mapping 白名单选择。初版不开放任意 raw SQL Mapping。

规划顺序：语义绑定 → 业务政策选择 → 依赖展开 → 授权范围 → 合法 Mapping/Link → 有界路径 → 合规候选成本 → DAG。没有路径或存在歧义应失败，LLM 不参与补路径。Object Link 循环可以存在，但一次遍历有预算；Rule/派生指标依赖环必须拒绝。

跨来源读取在同一 Python 应用进程内编排。来源连接池按逻辑 source ID、环境绑定版本及凭证/角色隔离，adapter 负责获取、复用和释放连接；连接配置来自受控环境，不能从请求传入。各池和应用整体均设置连接/并发上限，来源数量增长不能绕过总预算。

V0.1 组合支持独立指标观测以及声明 Link 上的等值键查找：先读取根对象或已绑定指标，按 Link 的显式身份绑定提取、规范化并去重目标业务键，再分批调用目标来源，按键关联规范化观测。身份键包含可信租户、目标对象类型与完整业务键；不按返回行序、物理主键碰巧相等或隐式字符串转换匹配。SQL/API 专属批量参数由 adapter 构造，core 只接收规范化键和观测。

每个来源均独立验证权限并下推过滤/投影；将来源 A 的键发送至来源 B 必须在批准 Mapping/Link 和授权允许的数据流范围内。B 中额外返回、未请求或越权的对象不得参与组合或暴露。ONE 目标出现重复键返回 `CARDINALITY_VIOLATION`；MANY 必须由声明的消费能力处理，点查不能偷取一个值。未匹配的目标保留 MISSING/NULL，来源故障或读取未完成保留 UNAVAILABLE 及诊断；不通过 inner-join 丢行掩盖缺失，也不将外部连接补空误认为来源 NULL。严格 Query 按第 5 节失败，Rule 按输入状态处理。

组合执行限制中间键数、单批键数、批次数、返回行数和缓冲字节数；计入整个请求的调用、内存及 deadline 预算，在分配/累积超限前停止，单行和单响应也需体积限制。禁止无过滤全表拉取、无界逐键调用或多对多展开。取消时清理所有参与来源。两来源各自的观测时间、版本与 Link 组合活动进入 Evidence；没有共同快照证明时拒绝严格跨来源一致性请求。此能力不提供跨库事务。

预算必须覆盖 select、DAG 节点、Link 深度、单次及总行数、来源调用数、并发、表达式深度及总 deadline。实验起点可用 50 个 select、100 个节点、3 跳、单次 1,000 行、总计 10,000 行、16 次调用、4 个并发和 10 秒 deadline；T02 根据明确 fixture 负载验证并调整，在配置中维护最终值。预算是保护上限，不是性能承诺。超限返回 `BUDGET_EXCEEDED`，不得以截断结果证明不存在。

Request cache 键含 releaseDigest、semantic ID、全部规范化维度、业务期间、单位、Mapping/source revision、授权 scope digest；缓存只在一个已认证请求内存活。相同依赖合并为一个 DAG 节点；不同口径或权限范围不共享。跨请求缓存暂不实现。

在来源版本尚未取得时，DAG 先按已固定的 Mapping、完整语义维度和授权范围合并 fetch；来源返回后将具体版本记入 Observation/Evidence，不能为了生成 cache key 额外重复读取来源。计划的同成本候选、节点排序和结果汇总必须有稳定的语义键排序；Python 字典/集合迭代和并发完成顺序不构成业务优先级。

deadline 必须下推到连接、语句或 HTTP 调用，取消时停止调度新节点，并在 adapter 层取消/隔离未完成工作、回滚和释放连接。停止等待一个协程不等于远程查询已停止；无法及时取消时记录未完成活动，不能复用状态不明的连接。对已发出的 Action 写入适用结果核对规则，不因客户端断开就撤销执行记录。

OpenAPI 是接口描述，不是完整业务接入协议。首版必须公布支持 profile：固定已注册服务、批准 operationId、JSON body、所需 path/query 参数、凭证引用、响应抽取、超时和错误映射。只读 API Provider 必须声明无业务写副作用的 operation、业务键绑定、响应字段抽取、类型、缺失与完整性规则；HTTP 404 仅在该 profile 明确且有权限证明时表示缺失，否则属于诊断。API 值在 adapter 中规范化，不通过 JSON 浮点解析损失金额精度；响应中的对象键必须与请求绑定相符。只读 API Provider 和 ActionExecutor 独立，不能把写 operation 用作数据预览。Action 明确指定幂等与核对能力。未支持的分页、签名、重定向、回调及异步任务必须在 import/compile 时报告，不隐式假装支持。

## 8. Evidence 与 Audit

EvidenceEnvelope 至少包含 requestId、releaseDigest、可信执行上下文引用、业务上下文、observations、claims、source activities、rule activities、authorizationDecisionRefs、diagnostics 和一致性/可重放等级。

每个 PRESENT Fact 指向 source activity；该 activity 指向 Mapping version、source ref、查询摘要、观测时间、来源版本（若有）及授权决策。Claim 指向精确输入及 Rule/Policy activity。派生关系共享引用，不重复生成不同“原始事实”。零行判断也需要 query scope、完整性证明及授权范围的证据。

`explain` 默认只展示调用者当前有权看到的语义解释与已脱敏引用。物理表列、原始主键和查询文本由额外诊断权限控制，Agent 默认不获得物理 schema。审计记录避免保存 secrets、原始 token 或无必要的敏感值。

| retentionMode | 持久化内容 | 可作出的承诺 |
| --- | --- | --- |
| REFERENCES | 最小来源引用、版本标识、摘要和执行关系 | 可追踪；来源变更后可能无法重算 |
| SOURCE_HISTORY | 引用可访问、不可变的来源历史版本 | 在来源仍保留且可授权访问时重放 |
| MINIMAL_SNAPSHOT | 加密保存规则实际使用的最小输入及类型/单位 | 在执行器与 release 仍可用时离线重算 |

哈希证明匹配关系，不证明来源真实，不凭空恢复历史值；敏感低熵值不能仅做裸哈希当作脱敏。Evidence 最小快照是明确的数据处理配置，有访问控制、保留期和删除策略；不把它误称为“平台完全不存业务数据”。

Query 的必要证据记录失败时返回失败。Action 执行意图和必要审计不能持久化时不发出写请求；若外部写后本地记录失败，进入恢复/核对流程，不能声称没有副作用。

## 9. Action

Action Definition 定义业务参数、目标、前提和预期效果；独立 Action Binding 声明下游 operation、参数映射、条件写、幂等及核对协议。二者版本及摘要均参与发布与审批绑定。

`plan_action` 解析 Action Definition，验证类型及领域约束，读取前提与目标版本，检查当前权限，生成无写副作用的具体 Action Plan。Dry Run 能证明可验证的前提与预期请求，不承诺下游一定成功。

计划摘要覆盖 action ID/version、tenant、actor、target identity、全部规范化参数、releaseDigest、环境绑定和执行 profile、下游 operation/version、前提版本、失效时间及随机 planId。Approval 由可信服务端身份通道写入，绑定该摘要、approver、decision、时间及期限。LLM 传来的 `approved: true` 不具有效力。

MCP v0.1 不提供自我审批工具。执行时重新检查当前权限（含撤销）、审批身份资格和隔离职责、计划有效期、参数摘要、release 可用性、目标前提及乐观锁版本；变化则 `STALE_PLAN` 或 `EXPIRED`，重新计划审批。旧审批不能批准新参数，也不能默认批准整批新子操作。

前提复查与写入之间仍存在竞态。对影响操作合法性的可变目标前提，下游必须将版本/条件校验与业务写入原子地执行，例如条件请求或其事务内检查。Runtime 的本地锁不保护远程系统；只有“先 GET 再 POST”不能满足此保证。依赖其他系统且无法原子约束的前提不能宣称持续成立；该 Action 不进入首版自动执行 profile，保留计划/人工处理能力。

状态表是持久化协议；每个状态转换使用条件更新，禁止两个 worker 同时取得同一执行权：

| 当前状态 | 事件 | 后继状态 |
| --- | --- | --- |
| PLANNED | 校验及鉴权已通过，提交审批 | APPROVAL_PENDING |
| APPROVAL_PENDING | 合格审批人批准/拒绝 | APPROVED / REJECTED |
| PLANNED / APPROVAL_PENDING / APPROVED | 超期或有效取消 | EXPIRED / CANCELLED |
| APPROVED | 再校验通过并持久化执行意图 | EXECUTING |
| APPROVED | 权限撤销或前提变化 | DENIED / STALE_PLAN |
| EXECUTING | 收到明确已接受写入结果 | SUCCEEDED |
| EXECUTING | 可证明未发生副作用的失败 | FAILED |
| EXECUTING | 超时、连接中断、进程崩溃或含糊 5xx | OUTCOME_UNKNOWN |
| SUCCEEDED | 核验读取结果与预期一致 | VERIFIED |
| SUCCEEDED | 暂不可见或核验调用失败 | VERIFICATION_PENDING |
| VERIFICATION_PENDING | 在核验预算内恢复可见 | VERIFIED |
| SUCCEEDED / VERIFICATION_PENDING | 明确内容不符或核验期限耗尽 | VERIFICATION_FAILED |
| OUTCOME_UNKNOWN | 根据稳定幂等键/业务引用核对 | SUCCEEDED / FAILED / 保持 OUTCOME_UNKNOWN |

计划之前的校验/授权失败返回诊断并记必要审计，不伪造成功的 plan。已在 EXECUTING 的动作不可宣称可取消；只能核对最终效果。VERIFICATION_FAILED 表示可能已经写入，不能自动重新执行或补偿。

幂等键属于业务执行，不属于网络 requestId：`tenant + actionPlanId` 对应持久化唯一 execution ID 和 payload digest。相同键不同 payload 返回冲突。客户端重复请求复用该 execution；故意发起另一笔相同金额业务仍需新 plan 与审批。

下游 MUST 提供幂等键处理或原子唯一业务引用，且支持按此引用核对。单靠 Runtime 本地表无法解决“外部写成功、本地尚未提交就崩溃”的窗口。若目标不满足，自动执行 profile 不予接入；可以保留 plan/export 能力供人处理。

Action 必须提供按 execution ID 查询当前状态和受控证据的只读入口。执行 worker 指应用进程内的后台任务，由同一个启动入口管理；应用重启时恢复扫描。其抢占、失联与重启通过持久化状态及有界租约/同等机制处理；接管未决执行首先核对，不能直接重发。最终一致读中的 NOT_FOUND 不证明未写入；只有下游契约能证明终止且未生效时才可转 FAILED，否则保持 OUTCOME_UNKNOWN 并进入人工核对。

下游幂等键有效期和去重记录保留期必须覆盖自动重试/恢复窗口。超过有效期、记录被清理或恢复点不完整时，不以新键继续旧操作；拒绝自动重发并标记需核对。重启后的恢复扫描及只读状态查询是 T05 的交付，不留成未分配的“后续运维”。

V0.1 一次计划一个草稿 Action，批量由多个独立计划组成，不承诺跨系统事务。示例 UI/Agent 可以展示三个计划的列表，但每笔都保留独立摘要、审批与结果。

## 10. 错误编码与响应映射

| 类别 | 示例 | 外部处理 |
| --- | --- | --- |
| 请求无效 | INVALID_REQUEST、INVALID_BINDINGS | REST 400；MCP 结构化错误 |
| 身份/权限 | UNAUTHENTICATED、FORBIDDEN | REST 401/403，按策略防枚举 |
| 模型/能力 | NO_MAPPING、NO_PATH、AMBIGUOUS_MAPPING、NO_APPLICABLE_POLICY | REST 422 + 稳定诊断 |
| 冲突 | IDEMPOTENCY_CONFLICT、STALE_PLAN、CARDINALITY_VIOLATION | REST 409 + 稳定诊断 |
| 依赖运行故障 | PROVIDER_TIMEOUT、PROVIDER_ERROR、RULE_EVALUATION_ERROR | 503/504/500 或明确 PARTIAL 分析响应 |
| 预算 | BUDGET_EXCEEDED | REST 422（结构预算）或 429（运行配额），不得静默截断 |

T01 确定响应类别，T02/T05/T06 完善操作差异与传输映射；上表是起点，不冻结每一个状态码。HTTP 状态与诊断码共同表达语义，不把业务 UNKNOWN 当作 HTTP 500。重试策略按操作及错误分类，写入不适用通用读重试。

## 11. 发布、环境与执行身份

这一节固定跨模块关系；具体字段序列化由对应任务决定。

| 受控对象 | 最小职责 | 负责方 |
| --- | --- | --- |
| Semantic Release | 不可变领域定义、类型化规则 IR、精确引用、Compiler 和 IR 版本 | T01，T04 激活 |
| Datasource Registration | 逻辑 source ID、物理来源身份、允许的 schema/operation、只读/写角色、secret reference | T02，T04 持久化；T05 扩展写 profile |
| Environment Binding | 将逻辑来源绑定到目标环境，固定非秘密连接身份、API spec/profile 摘要、契约验证结果及版本 | T04 |
| Execution Profile | Runtime build、adapter/normalizer/evaluator 版本、数值策略和会改变语义的配置摘要 | T00 建立构建身份，T02/T03 实现，T04 记录 |
| Authorization Decision | 当前 actor/tenant、策略 revision、能力与数据 scope；不是历史 release 中的过期权限 | T02，T06 对接可信身份 |

源码可以只写逻辑 datasource ID；环境连接配置不进入领域包中的密码字段。来源注册/改绑和发布是控制面操作，使用独立管理权限；Agent 查询不创建连接或提交任意 schema introspection。T02 提供受限 metadata 导入/检查，T04 建立 `register → inspect → validate → activate` 的可重复 CLI/管理流程。Studio 在 T09 提供可视化编辑，复用上述管理流程；AI 推荐 Mapping 不作为激活证明。

调用固定 release + environment binding + execution profile，再执行当前授权。来源身份变化、API operation 变化、normalizer/evaluator 语义变化不能借用旧的激活证明和 Action 审批；凭证无语义变化的轮换可按管理策略进行，秘密本身不进入摘要或 Evidence。

bundle 内容 hash 只证明内容完整性。激活还必须核验由受信任发布主体生成的批准/验证记录；普通查询身份不得写这张记录或激活指针。外部分发 bundle 的真实性需要可验证的发布证明，不能接受一个自填 APPROVED 文件。首版可在受限控制面内验证，不强制提前建设独立签名服务。

Runtime 声明支持的 bundle/IR/API profile 版本，加载时做兼容检查；不兼容时拒绝。持久化审计必须能找到 runtime build 和数值/归一化策略，否则相同来源值与同一业务 Rule 也不足以证明可复算。旧 release 的重放使用其兼容执行 profile；只能使用新执行器重新评估时，明确返回新的评估身份。

历史业务政策不意味着历史访问权限。查询、发现、重放和 Evidence 始终使用当前有效权限；release 回滚不能恢复已撤销角色。请求授权 scope 在 DAG 内不扩大，每次来源调用及返回敏感结果前检查权限仍有效；失效则停止并拒绝释放结果。生产使用的权限 revision/有效期机制由 T02/T06 实现并验证，不能只在入口信任永久缓存。

这些约束在一个 Python 应用进程内实现，接入与恢复任务共享应用生命周期。PostgreSQL metadata 可复用已有实例中的独立 database/role；来源数据库及必要持久化仍是应用访问的外部资源。

## 12. Studio 草稿与管理接口

Studio 草稿保存、来源注册与模型发布属于控制面写入，按管理权限、并发控制和审核协议执行，不要求生成业务 Action Plan。业务系统状态变更仍使用第 9 节的 Action 生命周期。

Studio 使用独立管理权限读取模型、来源元数据和草稿；样本数据另行鉴权。图谱节点、关系、搜索计数和影响分析均先按当前权限过滤。静态页面可见不表示其管理接口可用；服务端会话、CSRF/Origin 检查及凭证保密由 T09C 验证。

草稿校验只经控制面执行受限编译和授权的来源契约检查，不能将草稿临时激活为生产 release。规则草稿的合成输入预览与已发布 Runtime 执行明确区分；真实业务执行固定已批准的 release，预览不授予写入权限。

草稿在 PostgreSQL 中按 revision 保存，更新携带 expectedRevision，冲突不覆盖。校验记录及批准绑定精确候选摘要和环境绑定版本；修改草稿使旧验证/批准失效。发布版本只读，环境激活使用条件更新。UI、文件导入和导出复用同一规范化模型，不静默丢弃编辑器未呈现的字段；图坐标等视图偏好独立存储。

图谱默认表示模型定义及候选来源；实际执行来源必须来自带请求/评估身份的授权 Evidence。字段类型和来源映射变更须校验依赖并显示影响；模型发布批准与业务 Action 批准保持独立。详细交互以 [DESIGN](../DESIGN.md) 为准。

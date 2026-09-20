# Jev / TypeSafe AI 评估

日期：2026-09-20
范围：确认用户所说的「jev」与“把本体、用户问题、上下文摘要交给一个快速决策模型，再通过 hook 驱动通用流程”的匹配度，并给出 SemaLoom 的接入边界。本文只保存公开官方资料；用户消息中的 API key 未被使用、复制或写入仓库。

## 判断与不确定性

最可能的对象是 **TypeSafe AI 的 Jev**。官方把 Jev 定义为第一个 System One 模型：输入 `state` 与带类型的问题，返回 `Choice`、`Score`、`Noul` 等结构化判断，供代码路由、排序和分支使用，而不是生成回答文本。[官方介绍](https://docs.typesafe.ai/introduction) [官方 API](https://docs.typesafe.ai/api) 这与本项目需要的“由本体候选项和当前上下文决定下一步”的形态一致。

搜索结果中也有若干名为 `jev` 的社区 CLI、守护进程和 guard 项目，但它们不是 TypeSafe 的官方模型或 SDK。本评估不把这些社区包装作为依赖，也不把“最近流行”当作成熟度证明；若用户指的是另一个同名项目，需要再提供其官方地址才能确认。

## 官方能力边界

Jev 的请求由三部分组成：结构化或文本 `state`、模型 ID、带 `instructions` 和 `criteria` 的 typed questions。`Choice` 从调用方提供的有限候选中选一项，`Score` 在调用方提供的有序等级上评分，`Noul` 判断一个明确的真/假命题。[问题原语](https://docs.typesafe.ai/primitives) [API 请求与答案](https://docs.typesafe.ai/api)

`state` 可以是对象或数组，因此可以装入本体摘要、用户问题、对话摘要和本轮已核验的结果。官方建议给结构化状态使用命名字段，并明确指出每个问题独立评估；如果第二个问题依赖第一个问题的答案，应由代码构造第二次请求，而不是假设同一请求中的问题能互相看见。[State](https://docs.typesafe.ai/concepts/state) [依赖问题](https://docs.typesafe.ai/primitives#when-one-question-depends-on-another)

官方的层级分类 cookbook 与 SemaLoom 的逐步下钻很接近：把分类树或本体层级作为候选菜单，从根向叶逐层选择；对早期歧义可以保留多个 beam，再继续比较。[Hierarchical classification](https://docs.typesafe.ai/cookbooks/hierarchical_classification) 这可以借鉴为“先选对象/关系，再选语境/时间，再选指标/字段，最后选展示能力”的通用流程，候选项由当前 ontology release 生成。

Jev 适合做小而明确的判断，官方明确建议把复杂判断拆成原子问题并在代码中组合；`Choice` 最多 255 个选项，问题和选项的完整语义要写进请求，而不是依赖问题 ID 的含义。[问题设计](https://docs.typesafe.ai/primitives) [API 的 Choice 限制](https://docs.typesafe.ai/api#choice)

## 对多语言和数据治理的限制

官方模型页说明：Jev 接受文本、JSON 对象或数组，但英文是主要训练语言，CJK 文本目前准确率不等同于英文，非英文业务必须用自己的数据测试后再依赖它。[Models](https://docs.typesafe.ai/models) 因此 SemaLoom 不能把 Jev 的内部概率直接变成中文界面的“置信率”，也不能把一次中文判断当作业务事实。应让 Jev 只返回语言无关的候选 ID、等级或布尔信号，最终业务事实仍由 Runtime 和 Evidence 产生。

本项目的多语言设计应保持以下分层：

- ontology 使用稳定的语义 ID，展示标签、问题模板、候选说明和错误文案使用 locale map；代码不能按中文词语分支。
- 发给 Jev 的状态同时包含 `locale`、用户原问题、对话摘要和本体的语义切片。候选 key 使用稳定 ID，候选描述使用当前 locale 的业务说明；需要时提供语言中性的语义 gloss，但不要把物理字段名或业务编号作为自然语言答案。
- 以每种目标语言建立路由、下钻、字段选择和展示选择的评测集。未验证的语言走现有 deterministic/主模型降级路径，不能因为 Jev 返回了高概率就跳过授权、缺失观察或版本核对。
- `jev-latest` 是可移动别名；官方建议对经过阈值调优的流程 pin 到版本 ID，并记录响应里的实际模型版本。[Models](https://docs.typesafe.ai/models)

状态最多 64k tokens，单个 `state` 加最长问题最多 32k；这是发送 ontology **摘要/切片** 和上下文摘要的理由，不是把完整发布包、全量业务记录或原始证据送给 Jev。[Models](https://docs.typesafe.ai/models) 证据、金额、身份和权限边界仍留在 SemaLoom 服务端；传给决策层只需要候选能力、计数、grain、缺失项和已脱敏摘要。

## 推荐的通用架构

建议增加一个可替换的 `DecisionProvider`/`DecisionPort` 概念，默认实现可以是本地 faux provider，生产实现再通过官方 Python SDK 调用 Jev。SDK 与官方 skill 均为 MIT；Python SDK 的官方包是 `typesafe-sdk`，公开仓库和 PyPI 都标为 MIT。[官方 Python SDK](https://github.com/typesafe-ai/typesafe-sdk-python) [PyPI 发布包](https://pypi.org/project/typesafe-sdk/) [官方 Agent skill](https://github.com/typesafe-ai/skills)

公开官方交付面是托管 API、SDK 和 agent skill，没有公开模型权重或本地推理运行时，因此应把 Jev 当作可选的外部服务依赖，配置在服务端，不能把 key 放进前端、对话历史、工具参数或 source control。[Models](https://docs.typesafe.ai/models) [Legal / data handling](https://docs.typesafe.ai/legal)

状态由 SemaLoom 根据当前 release 生成，而不是在代码中穷举行业：

```text
Ontology release + locale
        + user request
        + compact conversation summary
        + current semantic capabilities / result shape
        ↓
DecisionProvider (Choice / Score / Noul; Jev or offline fallback)
        ↓
generic DecisionPolicy (typed output → bounded route / next slot / view)
        ↓
Pi hook + Python semantic gateway
        ↓
authorized query / clarification card / server-owned presentation
```

建议一次请求中组合一组互相独立的判断，例如：

```json
{
  "state": {
    "locale": "<current-locale>",
    "request": "<user-question>",
    "conversation_summary": "<bounded-summary>",
    "ontology": {
      "objects": "<semantic candidates>",
      "metrics": "<semantic candidates>",
      "links": "<declared relationship candidates>",
      "context_dimensions": "<declared filter dimensions>",
      "presentation_capabilities": "<capabilities derived from result grain>"
    },
    "current_result": "<count, grain, missingness and capability summary>"
  },
  "questions": {
    "intent": "one of the ontology-independent request families",
    "next_step": "which supplied semantic candidate should be explored next",
    "needs_context": "whether another user input is required before execution",
    "view": "which supplied result capability best fits the returned shape"
  }
}
```

这里的 JSON 只是接口形状示例，不应成为新的固定业务协议。`objects`、`metrics`、`links`、`context_dimensions` 和 `presentation_capabilities` 必须由发布后的本体、授权范围和 Runtime 结果能力生成。展示选择的候选应是服务端允许的通用能力（例如 scalar、table、trend、distribution、relationship），而不是把某个行业的树图或某个页面组件硬编码到 Jev 问题里。Runtime 仍负责生成精确事实和 Evidence；Jev 只能在允许的候选中选择。

## 如何使用 Pi hooks

当前项目已经把官方 Pi hook 接口放在受控的 semantic plugin 中。Pi 的 `beforeToolCall` 在参数校验后、工具执行前运行，可以阻止调用；`afterToolCall` 可以检查并替换工具结果；`transformContext` 适合注入或压缩上下文；`shouldStopAfterTurn` 可以在当前轮完成后停止下一次模型调用。[Pi 官方 hook 类型](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts#L1220-L1646) SemaLoom 自己的约束和选型见 [Chat Harness](chat-harness.md) 与 [ADR-0010](adr/0010-pi-chat-harness.md)。

适合的 hook 分工是：

1. `beforeToolCall` 只在需要语义路由或下钻判断时调用 DecisionProvider。候选工具名、对象 ID、物理查询、权限声明仍由 Python gateway 校验；Jev 不拥有执行权。高频且已明确的请求应由确定性检查直接通过，避免每次工具调用都增加一次网络判断。
2. `afterToolCall` 对结果做**摘要化**，只把结果计数、grain、可用字段类别、缺失项和下一步候选交给 DecisionProvider，判断“继续补充哪个 slot、是否已经具备回答条件、可用哪些通用展示能力”。原始证据、业务编号和金额不应进入 Jev 的决策状态或人类可见自然语言。
3. 如果 `needs_context` 或 `next_step` 表示还缺信息，Python gateway 创建现有的服务器拥有的 ChoiceQuestion/补充卡片，Pi 通过 `shouldStopAfterTurn` 结束本轮。下一次用户输入到达后，重新构建 ontology slice + 新摘要并发起依赖请求；这符合官方关于“依赖问题需要第二次请求”的规则。
4. `transformContext` 继续使用 Pi 原生 compaction 生命周期，只保留可复现的用户目标、已确认条件、已拒绝条件、证据引用摘要和当前 release digest。DecisionProvider 不应自行拼接第二套历史；它消费由 Python/ Pi 生成的有界摘要。
5. Jev 超时、限流、不可用或语言评测未通过时，退回 ontology 能力驱动的 deterministic policy 和当前主模型。对于缺条件的宽泛对象查询，降级也必须保持“先补充再执行”的安全边界；对于展示类型，降级到最简单的服务端 view。

这让 hook 成为一个决策扩展点，而不是第二套 Agent loop。决策输出只能是已签发候选集合中的 ID，随后仍要经过 release、tenant、actor、授权和 typed request 校验。Jev 的 confidence/probabilities 只能用于内部路由或人工复核策略，不向用户展示，也不能替代事实验证、权限或业务规则。

## 下钻流程的通用化规则

“年度申报表”只是一个例子，不能在核心代码里写 `year/company/field` 的行业分支。通用流程应由本体元数据驱动：

1. 从用户问题识别可能的 ontology candidate（对象、指标、关系或规则），并保留 `none/other`。
2. 从该 candidate 的声明能力中生成可选 context slots：身份键、时间/期间、粒度、属性过滤、关系端点和结果字段。哪些 slot 可用由 ontology 和 release 说明决定。
3. 如果缺少执行所需的 slot，或者候选结果过宽，由 DecisionProvider 在这些**实际存在的 slots** 中选择下一项；服务端生成补充卡片，用户填写后再执行。
4. 查询返回后，根据声明的 grain、additivity、time grain、关系形状和字段类型生成展示 capability。Jev 可以选择 capability，不能创造数据、重算金额或改变 Evidence；没有合适 capability 就用文本摘要。
5. 下一轮只携带确认过的条件和压缩后的结果摘要。所有完整记录和技术追溯信息仍由证据抽屉按需展开，默认关闭。

这与官方的层级分类和“先检索候选、再对候选做判断”的路线一致，但业务规则、候选集合和最终执行仍属于 SemaLoom；Jev 不是本体存储、查询引擎或通用 BI 组件。[层级分类](https://docs.typesafe.ai/cookbooks/hierarchical_classification) [意图路由](https://docs.typesafe.ai/patterns/intent-routing) [官方 skill 对职责边界的说明](https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md)

## 成熟度、风险和接入建议

截至 2026-09-20，官方 Python SDK 的公开版本为 0.6.0，支持同步和异步客户端；官方 JS SDK 也为 0.6.0。SDK、文档和模型版本都在快速迭代，官方模型页明确提示速率限制可能动态调整，`jev-latest` 会随发布移动。[Python SDK / PyPI](https://pypi.org/project/typesafe-sdk/0.6.0/) [JavaScript SDK / npm](https://www.npmjs.com/package/@typesafe-ai/sdk) [Models](https://docs.typesafe.ai/models)

因此推荐分阶段：

- **第一阶段：接口和 shadow mode。** 先实现 `DecisionProvider` 协议、offline faux provider、问题/候选快照和可重放日志；让 Jev 与现有 deterministic 路由并行运行，只比较选择，不改变用户结果。
- **第二阶段：只接入低风险路由。** 先让它选择 ontology candidate、下一下钻 slot 和 result capability；不让它授权、执行写操作、填写业务 ID、提供事实金额或生成最终证据。
- **第三阶段：语言和领域评测。** 对每个 domain pack 与 locale 覆盖宽泛问题、歧义问题、缺失信息、跨来源关系、无匹配和错误/UNKNOWN；记录 Jev 版本、候选集合、问题文本、答案和最终业务结果。中文未通过评测前，保留当前主模型/确定性降级。
- **第四阶段：有限生产启用。** 配置 server-side key、超时/限流/重试和模型版本；对不确定结果走补充卡或人工路径。升级模型时重跑阈值和回归集，不能只更新 alias。

最终建议是：**借鉴 Jev 的 typed decision + ontology-generated candidate + Pi hook 边界，推荐以可选 DecisionProvider 接入；不建议把 Jev 变成新的核心编译器、查询执行器、自然语言生成器或按行业穷举的判断函数。** 这既能让本体持续扩展时自动产生新的候选和下钻路径，也能保持 SemaLoom 的核心、授权、证据和多语言展示拥有明确所有权。

# 0010 — 可选 pi 对话 Harness 与受控业务插件

状态：accepted，2026-09-14。用户明确要求内置 Chat、pi core/plugin、百炼联通；这是对 T06“不包含聊天产品”及 ADR-0008“Node 只用于构建”的限定增补。

Python 继续独占业务定义、身份、发布、取数、规则和证据。可选 Node 子进程仅运行官方 pi Agent 循环与模型协议，由 Python 请求生命周期管理，通过父子进程 JSONL 传输工具调用和进度；无新监听端口、数据库凭证或通用 shell 工具。未配置时原应用正常运行。

使用官方 @earendil-works/pi-agent-core / pi-ai。SemaLoom plugin 从既有业务工具 Schema 创建工具，复用 core 原生 beforeToolCall/afterToolCall/shouldStopAfterTurn hook。插件只承担预算、结果版本检查和回答提交约束，业务 Rule 仍在 Python 解释器运行。内置通路不使用 MCP 网络往返；未来外部 MCP adapter 可复用相同业务派发器，不另写业务逻辑。不开启第三方插件自动安装或 coding-agent 的文件/终端工具。

对话归属来自 Studio 身份，历史与当前请求不能携带用户自报角色；一个分析回合固定 release，版本切换后明确重新开始。流式推送进度，最终答复引用服务器保留的工具证据，事实卡的金额、单位、TRUE/FALSE/UNKNOWN 直接取引擎。自然语言解读不冒充确定性验证。取消和断线终止子进程；调用数、输出、时间与历史长度有界。

provider 是服务端配置，密钥不送前端或工具参数。固定使用用户指定 Token Plan 端点，不自动切按量计费。模型可配置；首选从已鉴权 /models 返回的文本模型中选择，真实联通测试有界。

迁移：现有业务 pack/表与公共工具兼容；新增可选 harness 依赖和聊天 metadata。Python-only 部署仍不依赖 Node；启用聊天的部署需 Node >=22.19 及已安装的项目内 harness。对已有 broad production gates 不作关闭声明。

## 2026-09-20 增补：本体驱动的可替换决策钩子

Harness 增加可选的 typed decision provider。当前适配 TypeSafe Jev 官方 SDK，输入仅为当前用户问题、Pi 压缩后的有界对话、当前授权发布的本体目录投影、locale 与实时工具目录；候选来自发布内容和工具 Schema，不在核心中按行业穷举。输出只可调整工具候选顺序并判断是否需要继续补充范围，不拥有查询、授权、规则计算、事实生成或最终展示数据。

默认 `shadow` 模式只把判断作为模型上下文与工具排序；`enforce` 模式也只允许 `beforeToolCall` 对首个不一致调用做一次可恢复拦截。超时、低内部阈值或服务不可用时放行到原 Pi 流程，Python typed gateway 始终是执行边界。Jev 的概率只供内部阈值使用，不能进入用户回答、证据或置信率 UI。

这是 ADR 原有 hook 边界内的扩展，不改变 Python 对业务语义的所有权。TypeSafe 凭证只从服务端环境读取，经私有子进程 stdin 传递；启用意味着把上述有界、脱敏后的决策状态发送给额外的外部 provider，部署方须按数据治理要求显式配置。多语言使用稳定语义 ID 与 locale，不按中文关键词分支；模型版本或语言启用范围变更前应重放领域与语言评测集。

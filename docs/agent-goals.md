# 后续 agent 的 goal 提示词

状态更新：G1–G5 已交回，继续工作前先读 [统一收口清单](maturity-closure.md)。本文件保留原派发范围，不应重新执行已经验过的切片；公共发现、对象映射与 Studio 会话查询的部分后端缺口已由主 agent 修复。

主 agent 负责数据准备、公共模型及 Compiler/Provider/Runtime 架构；用户派发下面任务，完成后交回主 agent 集成验收。先读 [设计评审](design-review-2026-09-14.md) 与 [样本说明](local-business-samples.md)。本文件细分 [PLAN](PLAN.md)，不替代验收矩阵。

## 主 agent 保留的工作

| 顺序 | 工作 | 对应任务 |
| --- | --- | --- |
| M0 已交付 | 授权样本导入、只读账号、语义包、mock、查询/Claim/已发布视图版本路由 | T02/T04/T05 局部，R01 查询部分 |
| M1 下一轮 | 复合身份；typed property/rule 输入与 Claim 输出检查；物理 Mapping 编译归 adapter，公共 Compiler 不识别列/JSON pointer | T01–T03，R02–R04 |
| M2 | 查询预算/一致性、Evidence 持久化与重放、授权撤销、release/profile 迁移；消除生产启动 fallback | T02/T04/T06 |
| M3 | Action 固定批准版本、受控 mock executor、原子前提/幂等/故障恢复；可信身份与真实 MCP transport | T05/T06，R01 Action 部分 |
| M4 | 审核 agent 交接，联合回归；确认审计单位/口径后扩展对账 | T07/T09/T08 |

M1–M3 是后续主责，不宣称本次已实现。T08B 的部署、专家审查、保留/SLO 和生产身份仍需对应条件；远端读取授权不等于修改远端或生产部署授权。

## 派发顺序

第一波可同时派 **G1（页面交互）** 和 **G4（独立验收）**，使用不同 checkout/worktree。G2 在 G1 集成后执行，G3 在 G2 后执行，避免同时改 App、共享类型和样式。G2 的规则编辑依赖 M1；可先做已有稳定契约的 Metric 编辑。G5 可先审计构建，最终关闭须等待其他验收结果。

所有 agent 先检查当前 diff，保留已有工作；使用项目环境，不连接 remote-dev，不复制私有样本目录或财务数值。测试使用隔离合成数据库，禁止对用户样本库或原开发库运行会清空 fixture 的测试。

## G1 — 工作台交互与来源映射

复制以下内容作为 goal：

```text
目标：完成 SemaLoom 现有工作台交互修复，使业务人员能稳定创建实体、维护属性/关系、配置 PostgreSQL/OpenAPI 来源并保存重载。

先读 AGENTS.md 指向的 Studio 文档及 docs/design-review-2026-09-14.md。职责为 T09A/T09B 现有页面，拥有本轮 frontend/src 交互组件、App、样式及对应浏览器测试。禁止改 core/compiler/provider 公共语义；后端缺口以最小复现交回主 agent。与其他 UI agent 串行。

逐项实现：中文显示名称与稳定英文语义 ID 分开；新实体有可用身份键和类型；修改属性 ID 不丢焦点；URL 实体、图谱选中与检查器一致；关系 ONE 表达为源到目标至多一个，不能擅自标 1:1；切换、删除和冲突处理不丢未保存内容。

来源表单按协议显示，OpenAPI 不要求 table/column；只提供有授权 endpoint 的操作。连接验证返回不能覆盖期间的编辑，保存冲突/验证失效明确可恢复。连接信息不进入业务模型，数据库/API 失败可区分，一个页面一个主要操作。

浏览器验证：中文实体创建→标识/属性配置→保存→重载；编辑期间验证完成不覆盖草稿；API Mapping 保存/试读/失败恢复；深链接打开正确实体。隔离合成库运行安全与浏览器回归，不能仅截图或断言按钮存在。

交付代码、必要 DESIGN 修订和 .agents/G1/handoff.md，列出修改文件、A64/A65/A69 相关用例、实际命令结果、未解决项与共享文件影响。遵守 docs/agent-goals.md 的数据与环境边界，不自行派 agent，不改远端或发布。主 agent 复核后才关闭联合 gate。
```

## G2 — 业务定义编辑闭环

```text
目标：让实体页能维护业务 Metric 和 Rule，不只是数据库字段。依赖 G1 集成；typed Rule/property 输入部分依赖主 agent 的 M1 契约交接，未就绪时推进独立 Metric 编辑。

阅读项目 Studio 规范、CONTEXT、semantic-contract、PLAN T09B/T03 和 canonical Python 模型。范围为前端实体详情、业务编辑器、校验定位与浏览器测试，本轮独占 App/共享类型/样式。禁止另造前端表达式执行器或扩大 IR。后端缺口交主 agent，不能伪造成功接口。

完成有服务支持的 Metric 新增/修改/删除：业务含义、objectType、grain、valueType、unit、perspective 等遵循契约，显示引用影响，阻止不合法删除。M1 就绪后实现受限结构化 Rule 编辑：typed inputs、运算符、Claim 或派生指标输出；Compiler 诊断定位到可编辑字段。保存使用 canonical documents 和 expectedRevision，重载保留，草稿预览与已发布执行明确区分。

业务表单不要求 SQL/table/JSON pointer；这些属于 Mapping。不用 float 表示金额、不把缺失当零、不把数字表达式当 TRUE。以 tax/procurement 两领域验证通用性。

完成新增定义→保存→重载→已有协议 Mapping→查询/规则结果与 Evidence 的纵向路径；覆盖引用失效、并发冲突、错误恢复和键盘操作。使用隔离合成测试库，不能靠前端状态验收。

交付 .agents/G2/handoff.md、实际 checks 和 A65/A66 对应结果、必要 DESIGN 修订。禁止改 core/compiler/runtime；公共语义由主 agent 集成。遵守 docs/agent-goals.md 的环境与交接边界，不自行派 agent，不发布。
```

## G3 — 审核与发布页面

```text
目标：完成可理解的模型发布闭环，让用户区分“草稿保存”和“版本生效”。依赖 G1/G2 UI 集成，使用已有 Studio release endpoints。

阅读项目 Studio/security/release 契约及设计评审。拥有本轮前端 App、发布组件、权限/状态展示和 e2e；禁止修改公共发布安全语义或自创批准 API。

实现候选差异、编译/来源验证、独立审核批准、环境激活、当前版本和历史。操作对应明确权限及一个主要按钮，解释 candidateDigest/revision 与失败原因。保存不能显示已发布；草稿或来源变化使旧验证/审批失效；作者不能自批，viewer 无管理控件；服务端仍为权限最终校验者。

浏览器证明：编辑→保存→验证→不同本地 persona 审核→publisher 激活→已发布视图/公共查询使用该 digest→刷新有效。覆盖自批拒绝、过期 revision、来源变更后重验证、失效会话、无权限与失败恢复。不绕过 CSRF/Origin，不存浏览器凭证或真实样本；仅在隔离合成环境执行。

后端缺口以最小请求、预期/实际及所属 gate 交回主 agent，不以本地状态伪装。交付 .agents/G3/handoff.md、用例与 A66–A68 实际结果、必要 DESIGN 修订。遵守 docs/agent-goals.md，不自行派 agent、不发布，不声称生产身份或 pilot 完成。
```

## G4 — 跨领域与 AI 使用契约的独立验收

```text
目标：建立可重复的跨领域、面向 AI 使用的验收证据，独立验证其他 agent 交付。第一轮可与 UI 并行；只拥有新测试文件、验收脚本和本任务测试说明，不改产品实现或已有共享测试文件。

阅读 CONTEXT、architecture、semantic-contract、acceptance、PLAN T06/T07 和设计评审。记录现有接口及缺失能力；/mcp/tools 清单不是真实 MCP transport，不得声称已经接入 AI。

以合成 tax/procurement 建立业务金问题和确定性语义请求：描述实体/指标、对象/指标读取、口径歧义、缺失 UNKNOWN、来源不可用、Evidence、租户/角色拒绝、版本切换、Action 批准/核对。无需 LLM key；自然语言意图到 typed request 的映射与 Runtime 执行断言分开。未交付的真实 MCP 用例标记依赖 M3，不能用假 transport 获得绿色结果。

验证同一接口支持两领域，同协议新增业务只加声明/测试；物理 URL/SQL 与调用者权限不能由工具参数进入。返回须区分“不知道”“业务不成立”“系统无法读取”，描述/单位/口径不足时识别歧义，不猜结论。

隔离合成数据库，不访问 remote-dev 或私有财务值。失败归类为模型缺口、adapter 能力、Runtime 或 UI bug，给最小复现和验收 ID，不修改断言迁就错误。主 agent 修复后重跑对应项。

交付 .agents/G4/handoff.md、金问题/预期请求和可执行测试，按通过、失败、依赖未就绪分列 A40–A46/A58/A60/A63 及相关安全场景。遵守 docs/agent-goals.md，不自行派 agent、不调用付费模型、不关闭未执行的 gate。
```

## G5 — 可重建交付与使用说明

```text
目标：完成 T08A 的可重建准备，新贡献者只用合成数据即可安装、启动并理解能力边界。可先审计构建，最终关闭依赖 T07/T09 的真实验收结果。

阅读 AGENTS、CONTRIBUTING、PLAN T08A、quickstart、capabilities 和打包测试。拥有使用说明、发行说明、必要打包/CI 修改及独立测试；不改 core/compiler/runtime 或前端行为。共享文档修改在 handoff 协调。

独立 checkout 与隔离环境按锁重建，构建 wheel/sdist，检查最新 Studio 静态资源、许可证、必要公共合成示例；单 Python 进程启动、深链接有效，不依赖独立前端生产服务。公共 quickstart 不依赖私有 remote-dev、样本库、商业服务或模型 key。检查发行物不含 .agents、凭证或真实业务行。

以证据修正生产身份、MCP、复合身份、规则类型、Action 恢复与 Studio 完成度的过度承诺。提供五类可运行示例和预期；性能/生产未验收项保留。依赖/许可证清单跟随实际构建，不伪造 SBOM 或签名。

交付 .agents/G5/handoff.md、构建/安装摘要、内容检查和 A49 实际状态。产物放任务临时目录或约定输出目录；不 push、发布包、部署或修改全局环境。遵守 docs/agent-goals.md，不自行派 agent。A47/A48 不在本任务，主 agent 最后决定是否满足 T08A gate。
```

## 交回验收

handoff 包含起始基线/diff、文件、实际命令与结果、不可验证项及接口影响。主 agent 先审公共模型/边界，再在隔离合成环境跑检查；UI 须有浏览器保存—重载—执行证据。样本库只运行只读 smoke。未验证项保持待办，不把局部测试通过等同产品完成。

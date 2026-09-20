# Security baseline

当前为设计基线，尚无生产安全保证。以下规则适用于所有实现任务；行为细节以 [semantic contract](docs/spec/semantic-contract-v0.1.md) 为准。

## Trust boundaries

LLM 输出、检索文本、来源业务字段和 OpenAPI 描述都是数据，不是执行指令。服务端校验认证凭证并产生身份上下文，租户与角色不能由请求 body 自行声明。解析出来的 Semantic Request 仍是不可信输入。

业务权限采用默认拒绝。检查覆盖 discovery、对象与指标、依赖、来源数据、Rule 的派生结果、Action、Evidence、日志及缓存。来源端必须应用不可被用户过滤覆盖的行范围；列限制在读取前生效。服务账号不拥有业务无关表或写权限。授权引擎不可用时拒绝放行。

V0.1 可以只部署一个租户，但测试必须至少构造两个租户/主体，证明同一对象业务键不会跨租户泄露。作用域不足以证明全局不存在时，系统不得给出全局 FALSE。

## Data and execution controls

- SQL 值参数化，物理标识符来自已批准且已验证 Mapping；限制数据库角色、只读事务、查询时限和行数。
- OpenAPI server 与 operation 使用注册白名单；限制出站地址，禁止请求提供 URL、任意重定向、从不可信 `$ref` 自动访问内网及读取本地文件。
- 凭证通过 secret reference 注入，分别管理查询与写入权限；不把密码、token 或秘密放进 DSL、Evidence、trace 或提示词。
- 查询及 Link fan-out 受预算限制。Expression evaluator 使用允许列表和资源预算，不开放网络、反射、任意函数执行或动态代码上传。
- 源系统被修改时，source reference 与哈希不能替代历史快照。证据的访问范围、加密、保留与删除策略由部署方明确设置。
- 审批绑定精确计划；执行前再次鉴权和校验目标版本。含糊结果必须核对，未通过核验的外部写入仍视为可能已经发生。
- 对可变业务前提，目标系统在同一原子写入中验证版本/条件；仅有 Runtime 的“先读后写”检查不足。恢复时 NOT_FOUND 不自动证明未执行，幂等记录过期不触发旧写入重发。
- 发布、来源注册和环境改绑使用控制面权限。bundle 摘要不等于发布者身份；旧 release 不能恢复已撤销的访问权。query/audit 记录执行器与非秘密环境绑定版本。
- 请求、计划与执行审计使用关联 ID；日志中不默认保存原始数据值和完整请求体。必要证据/执行意图无法可靠记录时按契约停止或进入核对状态。

## Local and production profiles

真实业务样本的导入需要数据所有者明确授权；企业专属导入脚本与操作记录不属于公开仓库。远端只读，源标识替换，凭证、HMAC key、导入记录和业务行留在未提交的私有目录/本地数据库；标识替换不使真实金额成为公开合成数据。运行时使用只读样本账号，mock 仅返回合成工作流状态。公共 fixture、CI 与发行物不得依赖或包含该数据集，页面不能无条件声称“未连接真实业务数据”。

本地 fixture 身份仅允许显式 demo profile，不能作为生产认证 fallback；生产 profile 未配置可信身份验证、授权、来源最小权限和必要持久化时启动失败。测试数据库和模拟 API 默认绑定本机，不包含真实税务记录。

T06 对 REST/MCP 统一接入受信任身份验证，至少检查 issuer、audience、有效期及签名，主体/租户来自验证后的凭证或受信任服务端目录；使用维护中的认证库，不自研密码学。若有代理主体，显式绑定调用服务与最终用户，不将未经验证的转发 header 当作身份。外部传输通过安全连接或受信任 TLS 终止，demo token/明文部署不能成为生产 profile 的自动降级。

授权在来源调用及敏感响应释放前仍须有效；权限失效时停止并不释放结果。异步取消需清理远程查询与连接状态，不能仅停止等待。真实身份接口由 T06 承担，T08 做部署验证，不能让生产认证落入无人实现的 pilot 待办。

Pilot 前验证身份 issuer/audience/expiry、权限撤销、跨租户查询、证据脱敏、审批重放、进程崩溃恢复及备份恢复。真实数据接入、Retention、SLO 和审计存储策略需要项目方与部署方确认。

## Studio management

模型查看、草稿编辑、来源管理、样本读取和发布激活分别鉴权。图谱节点、边、搜索计数和影响分析在服务端过滤；浏览器从未收到的资源才能保证不被前端绕过显示。来源连接/试调用由受控 adapter 执行，来源管理员输入目标不等同于普通业务查询可接受 URL。

Studio 同源会话使用安全 cookie 与 CSRF/Origin 检查，退出和撤销使敏感界面缓存失效；秘密不回显、不写浏览器持久存储。草稿保存带 expectedRevision，发布批准绑定精确候选及环境；更改使旧证明失效。草稿校验可读取授权样本，但不能执行业务 Action。T09C 完成浏览器端到端安全验收。

## Reporting

请使用 GitHub Security Advisories 的
[私密漏洞报告](https://github.com/levi-qiao/SemaLoom/security/advisories/new)。不要在公开 issue
中上传秘密、真实业务数据或私有 schema。当前 pre-alpha 版本没有安全修复 SLA；维护者会在确认
影响后通过受支持分支发布修复说明。

## Optional embedded Chat

配置 SEMALOOM_CHAT_CONFIG 后，Chat 模块可把用户问题和已授权的语义结果发送给服务端配置的模型 provider。密钥只经父子进程私有 stdin 传给 pi；不注入浏览器、模型上下文或业务工具。Pi 不获得业务数据库凭证，不自动加载用户目录的 coding-agent 插件、shell 或文件工具。

Chat 历史保存在现有 metadata PostgreSQL，按 tenant + actor 隔离，生产 retention 尚未实现。切换主体/退出/版本变化后禁止继续释放旧运行结果；取消终止 task-owned Node。事实卡直接来自服务器引擎，不以模型文本作为审计证据。原有生产 profile 限制仍有效。

Chat 浏览器 lineage 遵循既有 modeler/model-viewer/source-admin 模型元数据可见权限，并同时要求业务分析权限；普通 analyst 不返回表列，历史响应重新过滤。lineage 只保存实际引用 Mapping 的受限摘要，不含连接设置，不发送给模型。集合分析在租户范围内完整枚举，拒绝截断、重复单位及操作错误；不通过自由 SQL 绕开权限。

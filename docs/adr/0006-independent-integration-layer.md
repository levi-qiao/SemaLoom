# 0006 — 通用业务核心与独立接入层

状态：accepted。细化 ADR-0001 的领域分离，并替代将物理 Mapping 作为领域定义自身职责的表述。

## 决策

SemaLoom 是通用企业业务语义层。税务、采购及其他业务通过声明式领域包接入，不构成 core 的行业类型或分支。领域包拥有对象、业务身份、指标、关系、规则、政策与 Action 的业务输入/效果定义。

接入层独立拥有 Mapping、Action Binding 和协议 adapter：将语义定义绑定到物理表列、API operation、来源认证、分页、错误、幂等与核对协议。相同领域包可绑定不同企业系统，同一 adapter 可服务多个领域。接入配置按版本审核，与领域包组合成不可变 release；秘密与部署连接留在受控环境配置。

Core 定义协议中立的 ReadProvider/ActionExecutor 接口及其输入/输出类型；Compiler 负责公共语义检查，adapter 侧负责物理 Mapping/profile 校验与物理计划编译。app 显式装配实现。core 和公共 Compiler 不导入 adapter、厂商 SDK 或领域实现，不解析 SQL/OpenAPI 专属字段；版本化的接入产物由对应 adapter 解释。

授权 scope、类型、预算、观测完整性、Evidence 和 Action 生命周期仍由 core 统一约束。adapter 无法满足接口语义时必须拒绝能力，不得用协议成功冒充业务成功。接入代码是部署方审核的可信扩展，不是运行上传脚本的沙箱。

## 影响与验证

源码将 `domain/` 业务定义与 `integration/` 接入声明分开；可以放在同一示例目录中交付，无需多个 Python distribution、插件发现或新服务。单应用部署与跨来源执行进一步由 [ADR-0007](0007-in-process-source-composition.md) 明确。现有术语和 Compiler 接口草案同步调整；当前没有运行代码、已发布 bundle 或数据迁移。

T00/T01 验证 import 方向与分离类型，T02 以同一业务包绑定两个不同物理 schema 证明接入可替换，T05 验证 Action Binding，T07 回归同 adapter 跨领域复用。新增协议只改接入实现与注册；若真实需求超出公共契约表达能力，应单独提出通用能力变更及 ADR，不能以行业或厂商特判扩展 core。

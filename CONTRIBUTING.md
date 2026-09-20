# Contributing

从 issue 或 [PLAN](docs/PLAN.md) 选择一个依赖已满足的任务，阅读 [AGENTS.md](AGENTS.md) 指向的规范。当前仓库是 pre-alpha；提交应区分已验证行为、设计目标和未知项，不把合成原型报告为生产 gate 已通过。

公开文档不要把 local-dev demo token 写成生产身份、把 `GET /v0.1/mcp/tools` 写成 MCP SDK、把复合身份写成已覆盖跨源集合分析 JOIN、把 typed Rule 扩展写成任意代码执行，或把 in-process `DraftStore` 写成企业写入恢复。点查/Link/Action 已支持完整结构化身份；集合分析的复合 Link 仍明确拒绝。Studio 的结构化 Rule 编辑器和 A64–A69 联合 gate 尚未关闭。能力边界见 [capabilities](docs/capabilities.md)。

## Implementation conventions

嵌入式消费者和 app 使用 `semaloom.sdk` 的编译装配入口；低层 `semaloom.compiler` 必须显式注入 `MappingCompiler`，不能反向导入 SDK/接入实现。新增协议在 adapter 实现，不在通用 Compiler 写协议分支。接口与迁移见 [Python SDK](docs/python-sdk.md)。

- 后端使用 Python + FastAPI，单个 `pyproject.toml`、`src/semaloom/` 包与 `uv.lock`。已验证组合：Python 3.13（`.python-version` 与 `requires-python = ">=3.13"`）、Ruff、mypy、pytest。IDE 的 Pyright/basedpyright 通过 `[tool.pyright]` 对齐同一套源码与 `.venv`，不是第二套 CI 类型检查器。
- 公开 JSON 使用 camelCase：Pydantic 模型用 `wire_config()` / `alias_generator=to_camel`。Python 构造函数只写字段名（`result_id=`）。禁止 `Field(alias=...)`，否则 Pyright 会把 JSON 名当成唯一构造参数。线名不是 `to_camel(field)` 时用 `validation_alias` + `serialization_alias`。
- 依赖通过 uv 锁定，在仓库根 `.venv` 中运行：已有锁文件时使用 `uv sync --frozen`；命令通过 `uv run` 或 `.venv/bin/python` 执行。禁止 Conda、系统 pip、`pip --user` 或修改其他项目环境。
- 业务定义放领域包；物理 Mapping、Action Binding 与协议代码放独立接入层。新增业务/协议提交需附 core 与公共 Compiler 无特判改动的证据；同一业务换来源通过接入契约测试。
- Core 通过显式参数注入依赖；纯模型可用标准库数据类，输入校验使用 Pydantic。公开契约不暴露 FastAPI、SQLAlchemy 或厂商 SDK 对象；不为隔离 Pydantic 机械复制整套 DTO。
- 金额使用 `decimal.Decimal`，显式数值 context、精度和舍入策略；从字符串构造，拒绝非有限值和隐式 float。规则使用有界 typed expression IR 的受限解释器，禁止 `eval/exec`。
- JSON Schema 使用 draft 2020-12，YAML 使用 1.2 语义与安全解析。诊断码、字段名和语义 ID 使用英文，业务标签和文档允许中文。
- 测试围绕外部接口和可观察行为。数据库语义使用 PostgreSQL 集成测试，不以 SQLite 替代验收；OpenAPI 使用可控制失败与重放的模拟服务。
- 自动化检查：`uv sync --frozen` 后执行 `uv run pytest`。pytest 会话开始时运行 Ruff、mypy、禁止 `Field(alias=)`，并在 `frontend/node_modules` 存在时运行 `pnpm check`（`tsc --noEmit`）。跳过静态检查：`uv run pytest --no-static` 或 `SEMALOOM_NO_STATIC=1`。覆盖契约正反例、包 import 方向及集成行为；CI 见 `.github/workflows/ci.yml`。前端 job 仍单独跑 `pnpm check` 与打包产物核对。
- 接入 adapter 与 Action 恢复任务随同一个应用进程启动和停止，部署入口统一；不要求额外 worker、队列或查询服务。依赖放在项目环境，遵循实际 manifest/lockfile，禁止 home-level 项目依赖目录。
- 本地 PostgreSQL 使用 Compose（`docker compose up -d --wait`）或等价的 Homebrew `postgresql@16`（`127.0.0.1:5432`，角色 `semaloom`，库 `semaloom_{tax,orders,suppliers,meta}`）。禁止对 `semaloom_samples` / `semaloom_sample_meta` 或远端库运行会清空 fixture 的测试。公共 quickstart 只使用合成数据。

## Studio frontend

T09 按 [DESIGN](docs/DESIGN.md) 创建 `frontend/`，采用 React/TypeScript/Vite 与 pnpm；固定经过验证的 Node/包管理器版本和 lockfile。基础组件按需引入，记录来源许可，视觉 token 集中维护。生成契约类型，界面不复制 Python 规则执行语义。

前端构建产物打包进 Python wheel（`src/semaloom/app/static/`），由同一 FastAPI 应用提供；未启用 Chat 的已构建发行物安装和运行无需 Node。验证 SPA 深链接与 API 路由。本地可信会话和合成 OpenAPI 只证明控制面与适配器闭环；生产身份、真实企业 API 和容量仍单独标注，不以合成界面代替验收。

## Review and completion

隔离浏览器回归使用 `SEMALOOM_E2E_ISOLATED=1 corepack pnpm --dir frontend e2e`。
PostgreSQL 的 `initdb` / `pg_ctl` 须在 PATH，或设置 `SEMALOOM_E2E_PG_BINDIR`
（Homebrew 示例：`/opt/homebrew/opt/postgresql@16/bin`）。测试使用临时数据库，拒绝复用已占用的端口；
可用 `SEMALOOM_E2E_HTTP_PORT` / `SEMALOOM_E2E_PG_PORT` 调整端口，
`SEMALOOM_E2E_SCRATCH` 指向已存在的临时目录。退出时停止任务数据库并清理其子目录。
隔离 Chat 使用确定性 faux worker，浏览器通过不代表真实模型问答准确率。

变更描述说明业务触发条件、结果、对应验收 ID、验证结果和已知限制。语义变更同时更新规范、Schema、fixture 和兼容性说明。文档 Schema 校验通过不等于 Runtime 验收通过。

发布物由经审查的源码构建，生成内容摘要和可追踪依赖。发行名是 `semaloom`，语义契约 `v0.1`，`apiVersion` 为 `semaloom/v0.1`。V0.x 允许经过记录的破坏性变更，仍须显式升级 apiVersion/迁移策略，不静默重解释历史 release。本仓库当前 **不授权** 推送、PyPI 发布、签名或部署；发布身份与渠道由维护者另行提供。

依赖与许可跟随实际构建，不伪造 SBOM 或签名：

- 项目许可 [Apache-2.0](LICENSE)；Studio 打包的 React 资产见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
- 运行时依赖以 `pyproject.toml` 声明、`uv.lock` 锁定为准。重建后检查：`uv export --frozen --no-dev --no-hashes`，以及 wheel 内 `*.dist-info/METADATA` 的 `Requires-Dist`。
- 包元数据和发行物必须包含 LICENSE。sdist 不含 `.agents/`、`runtime.env` 或私有样本说明；公共合成示例在 `examples/tax` 与 `examples/procurement`。
- 目前没有签名 SBOM、SLSA 证明或包签名。不要把 lockfile 当作发布证明。

项目目前不要求 CLA 或 DCO。维护者见 [.github/CODEOWNERS](.github/CODEOWNERS)。社区规范见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

本地入口和 PostgreSQL fixture 见 [quickstart](docs/quickstart.md)。安全问题使用 [私密报告流程](SECURITY.md)，普通支持范围见 [SUPPORT.md](SUPPORT.md)。

## Optional pi harness

[Chat Harness](docs/chat-harness.md) 使用项目内 harness/package.json 与 pnpm-lock.yaml，Node >=22.19。运行 corepack pnpm --dir harness install --frozen-lockfile --ignore-scripts，然后 corepack pnpm --dir harness test。仅模型循环运行在可选子进程，禁止在插件复制业务规则或把真实 API key 加入测试。

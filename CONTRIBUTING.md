# Contributing

从 issue 或 [PLAN](docs/PLAN.md) 选择一个依赖已满足的任务，阅读 [AGENTS.md](AGENTS.md) 指向的规范。当前仓库是 pre-alpha；提交应区分已验证行为、设计目标和未知项，不把合成原型报告为生产 gate 已通过。

## Implementation conventions

- 后端使用 Python + FastAPI，单个 `pyproject.toml`、`src/semaloom/` 包与 `uv.lock`。已验证组合：Python 3.13（`.python-version` 与 `requires-python = ">=3.13"`）、Ruff、mypy、pytest。不并行维护第二套类型检查器。
- 依赖通过 uv 锁定，在仓库根 `.venv` 中运行：已有锁文件时使用 `uv sync --frozen`；命令通过 `uv run` 或 `.venv/bin/python` 执行。禁止 Conda、系统 pip、`pip --user` 或修改其他项目环境。
- 业务定义放领域包；物理 Mapping、Action Binding 与协议代码放独立接入层。新增业务/协议提交需附 core 与公共 Compiler 无特判改动的证据；同一业务换来源通过接入契约测试。
- Core 通过显式参数注入依赖；纯模型可用标准库数据类，输入校验使用 Pydantic。公开契约不暴露 FastAPI、SQLAlchemy 或厂商 SDK 对象；不为隔离 Pydantic 机械复制整套 DTO。
- 金额使用 `decimal.Decimal`，显式数值 context、精度和舍入策略；从字符串构造，拒绝非有限值和隐式 float。规则使用有界 typed expression IR 的受限解释器，禁止 `eval/exec`。
- JSON Schema 使用 draft 2020-12，YAML 使用 1.2 语义与安全解析。诊断码、字段名和语义 ID 使用英文，业务标签和文档允许中文。
- 测试围绕外部接口和可观察行为。数据库语义使用 PostgreSQL 集成测试，不以 SQLite 替代验收；OpenAPI 使用可控制失败与重放的模拟服务。
- 自动化检查：`uv sync --frozen` 后执行 `uv run ruff format --check .`、`uv run ruff check .`、`uv run mypy`、`uv run pytest`。覆盖契约正反例、包 import 方向及集成行为；CI 见 `.github/workflows/ci.yml`。
- 接入 adapter 与 Action 恢复任务随同一个应用进程启动和停止，部署入口统一；不要求额外 worker、队列或查询服务。依赖放在项目环境，遵循实际 manifest/lockfile，禁止 home-level 项目依赖目录。

## Studio frontend

T09 按 [DESIGN](docs/DESIGN.md) 创建 `frontend/`，采用 React/TypeScript/Vite 与 pnpm；固定经过验证的 Node/包管理器版本和 lockfile。基础组件按需引入，记录来源许可，视觉 token 集中维护。生成契约类型，界面不复制 Python 规则执行语义。

前端构建产物打包进 Python wheel，由同一 FastAPI 应用提供；已构建发行物安装和运行无需 Node。验证 SPA 深链接与 API 路由、键盘/对比度、草稿并发、权限及发布流程。生产身份和真实 API 未接通时明确标注未完成，不以合成界面代替验收。

## Review and completion

变更描述说明业务触发条件、结果、对应验收 ID、验证结果和已知限制。语义变更同时更新规范、Schema、fixture 和兼容性说明。文档 Schema 校验通过不等于 Runtime 验收通过。

发布物由经审查的源码构建，生成内容摘要和可追踪依赖。V0.x 允许经过记录的破坏性变更，仍须显式升级 apiVersion/迁移策略，不静默重解释历史 release。

项目采用 [Apache-2.0](LICENSE)。包元数据和发行物必须包含 LICENSE；第三方代码保留原始许可及必要声明。项目目前不要求 CLA 或 DCO。

本地入口和 PostgreSQL fixture 见 [quickstart](docs/quickstart.md)。安全问题使用 [私密报告流程](SECURITY.md)，普通支持范围见 [SUPPORT.md](SUPPORT.md)。

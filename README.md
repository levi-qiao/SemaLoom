# SemaLoom

通用企业业务语义层：让 AI Agent 和应用通过统一的业务对象、指标、规则与受控操作，使用企业已有数据和系统。

当前为 **架构与执行基线 v0.1** 加 T00 Python 工程。尚无业务查询/规则 Runtime。业务通过领域包定义，企业系统通过独立接入层适配；core 保持行业与协议中立。税务和采购是合成验证示例。主体采用 Python 3.13、FastAPI 和 PostgreSQL，所有模块在同一个 Python 应用进程内运行，各数据源独立配置连接，跨库结果在进程内组合。

## 从这里开始

- 实体工作台布局、组件与前端方案：[DESIGN](docs/DESIGN.md)。
- 项目方向、模块职责与取舍：[架构](docs/architecture.md)。
- 实施顺序、任务依赖与完成条件：[执行计划](docs/PLAN.md)。
- 统一业务语言：[CONTEXT.md](CONTEXT.md)。
- Agent 工作入口：[AGENTS.md](AGENTS.md)。
- 契约不变量与接口草案：[契约 v0.1](docs/spec/semantic-contract-v0.1.md)。
- 行为验收和失败案例：[验收矩阵](docs/acceptance.md)。
- 架构审查与修订：[审查记录](docs/review-2026-09-11.md)。
- 技术判断依据：[技术参考](docs/references.md)。

首个目标：用采购和税务合成案例验证多来源查询、确定性规则、授权证据和受控操作；通过内置工作台查看实体关系、编辑业务模型并配置数据库/API 映射。具体实施顺序以执行计划为准。

文档定义架构边界、术语、关键语义与验收目标。接口字段、DSL 完整 Schema 和业务 Runtime 由后续任务完善；文档中的接口与目录草案不代表已经实现。

## 本地开发

需要 Python 3.13 与 [uv](https://docs.astral.sh/uv/)。在仓库根：

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv run semaloom
```

`uv run semaloom` 打印 runtime build identity，不需要真实业务系统凭证。HTTP 组合根是 `semaloom.app.create_app`（`uv run semaloom serve`）。后续任务的本地 PostgreSQL fixture：`docker compose up -d`。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)，SPDX 标识为 `Apache-2.0`。仓库尚未公开发布；发布前清单见 [CONTRIBUTING.md](CONTRIBUTING.md)。

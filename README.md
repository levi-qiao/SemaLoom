# SemaLoom

通用企业业务语义层：让 AI Agent 和应用通过统一的业务对象、指标、规则与受控操作，使用企业已有数据和系统。

当前为 **合成 PoC v0.1**：T00–T07 与 T09 已在本地 PostgreSQL fixture 上实现；T08A 为开源准备（未发布）；T08B 真实 pilot 未关闭。业务通过领域包定义，企业系统通过独立接入层适配；core 保持行业与协议中立。税务和采购是合成验证示例。主体采用 Python 3.13、FastAPI 和 PostgreSQL，所有模块在同一个 Python 应用进程内运行。

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

合成 quickstart、能力边界与未授权 pilot 计划见 [quickstart](docs/quickstart.md)、[capabilities](docs/capabilities.md)、[pilot-plan](docs/pilot-plan.md)。

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

`uv run semaloom` 打印 runtime build identity。查询合成数据：先创建 `semaloom_*` 数据库并 `uv run semaloom load-fixtures`，再 `uv run semaloom query --metric tax.reportedIncome`。HTTP：`uv run semaloom serve`；Studio：`/studio/`。本地 demo token：`Bearer tenant-a-analyst`。不得当作生产认证。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)，SPDX 标识为 `Apache-2.0`。仓库尚未公开发布；发布前清单见 [CONTRIBUTING.md](CONTRIBUTING.md)。

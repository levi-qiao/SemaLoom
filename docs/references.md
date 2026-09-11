# 技术参考

以下保留当前架构所用的官方参考入口。本次文档审查未重新进行外部能力核实；具体版本、兼容性与性能由实现任务验证并锁定。

| 参考 | 使用位置 |
| --- | --- |
| [Python decimal](https://docs.python.org/3/library/decimal.html) | T03 精度、舍入与异常策略 |
| [SQLAlchemy Core](https://docs.sqlalchemy.org/en/20/core/) | T02 受限关系计划的物理 SQL 构造 |
| [psycopg 参数绑定](https://www.psycopg.org/psycopg3/docs/basic/params.html) | T02 参数化执行与注入防护 |
| [Python graphlib](https://docs.python.org/3/library/graphlib.html) | T02 依赖拓扑排序与环检测 |
| [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/) | T01 类型与 Schema 导出 |
| [OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html) | T05 受控接口 profile 的规范参考 |

架构理由见 [ADR](architecture.md#架构决策)，具体行为要求见 [语义契约](spec/semantic-contract-v0.1.md)。官方库能力不替代本项目的语义、授权、证据及接入契约验收。

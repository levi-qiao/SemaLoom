# 本地申报与审计样本

本数据集来自用户授权读取的 TI remote-dev，供本地建模、查询和页面试用。标识已替换，仍保留真实数值，不是可公开的合成 fixture。远端只读，API 状态完全在本地模拟。

## 数据与模型

2026-09-14 导入：10 个企业、10 份年度申报表、260 条收入明细、10 份审计报告、100 条审计观测、10 条模拟复核状态，覆盖 2024/2025。每年最多选择 6 个有申报与报告匹配的企业，实际受可匹配记录数限制；按源标识确定排序，不是统计抽样。

| 业务对象 | 本地表 | 语义 ID |
| --- | --- | --- |
| 企业 | sample_taxpayer | finance.Company |
| 年度申报表 | sample_declaration | finance.TaxReturn |
| 申报收入明细行 | sample_declaration_line | finance.ReturnLine |
| 审计报告 | sample_audit_report | finance.AuditReport |
| 审计抽取观测 | sample_audit_factor | finance.AuditFactor |
| 年度财务分析样本 | sample_financial_review（接入层视图） | finance.ReviewCase |
| 模拟复核状态 | sample_mock_review | AuditReport.reviewStatus 属性 |

业务定义在 `examples/financial-review/domain/`，表、列和 API 路径在 `integration/`。新增业务没有修改 core 或公共 Compiler。应用装配层可用 `SEMALOOM_PACK_PATHS` 指定领域包目录（系统路径分隔符，可组合多个包）。

申报表与报告按源企业标识和年度匹配；多份记录选择最近更新者，以 ID 决定同时间顺序。候选数写入私有 manifest。这只是演示配对，不证明业务最终版。收入明细同时匹配申报文件、企业和期间。审计只选择明确列出的 10 类数值因子，保留 observed / not_disclosed / extraction_failed 等源状态。只有 observed 且合法的十进制数才写入 numeric_current；缺失、抽取失败与零保持不同。

已追溯上游 monetary normalization → final_value → value_current → 审计结果投影链路，金额契约为人民币元；单位冲突时的抽取逻辑仍不保证原文正确。新增 6 个审计指标、1 个选定申报利润指标及 1 个派生利润差额、3 条保守数值校验。详见 [AI 分析定义](ai-analysis.md)。全部 10 个样本真实来源状态为 unreviewed；9 个企业年度配对候选唯一、7 个利润总额和 6 个资产总计可用。没有逐份核对原始报告，不能称正式审计结论。

## 本机使用

独立数据库为 `semaloom_samples` 和 `semaloom_sample_meta`，原开发库保留。`.agents/local-data/runtime.env` 权限为 0600，样本查询账号仅获 SELECT 权限。由仓库根运行：

```sh
source .agents/local-data/runtime.env
uv run semaloom serve --host 127.0.0.1 --port 8000
```

另一个终端注册、验证并检查真实读取链路：

```sh
source .agents/local-data/runtime.env
uv run python ops/data/setup_local.py
uv run python ops/data/verify_local.py
uv run python ops/data/verify_analysis.py
```

打开 `http://127.0.0.1:8000/studio/`。默认草稿有 6 个实体、8 个关系、14 个指标、5 个规则；审计报告由 PostgreSQL 与 mock API 两个 Mapping 提供。setup 仅在来源/默认草稿不存在时新增，不覆盖编辑、不自动批准或激活。未激活时沿用 local-dev 启动模型；这是演示 fallback，不是生产发布保证。

`/mock/audit-review?reportId=<样本报告 ID>&tenant=tenant-a` 返回稳定的 PENDING / READY / ON_HOLD 及 `mocked: true`，不存在或另一租户返回 404。它只模拟工作流，不提供真实财务值或真实复核结论。仅在 local-dev 配置本地样本库时启用；运行命令绑定 loopback，不应向外部暴露此 demo 环境。

完整对象/指标请求可 POST `/v0.1/query`，兼容原单指标简写。本地请求沿用 `tenant-a-analyst` demo bearer token。`verify_local.py` 自动选取关联样本 ID，不打印数值或完整结果，覆盖数据库/API 组合与来源 Evidence。

本机 `.agents/local-data/sample-requests.json` 有三个可直接试用的 HTTP 请求（仅样本 ID，不含金额），不进入发行物。G1 已修复 API 试读按钮错误依赖数据库 table 的问题；独立页面复核使用 [测试提示词](analysis-test-goals.md)。

## 再次导入

`ops/data/import_remote_dev.py` 使用只读、可重复读事务，只读取申报主表、收入明细、审计文件格式和允许的审计因子。不读取文件内容/路径、企业名称、联系方式或评审文本。沿用 TI 私有 remote.env，不复制到仓库。

导入连接与运行时只读连接分开。在子 shell 指定已有本地库的写入账号（下例 `$USER` 仅适用于本机同名 PostgreSQL owner）：

```sh
(
  set -a
  source "${SEMALOOM_PRIVATE_SOURCE_ENV:?set the absolute path to the authorized private env file}"
  set +a
  export SEMALOOM_SAMPLE_DATABASE_URL="postgresql://$USER@127.0.0.1:5432/semaloom_samples"
  uv run python ops/data/import_remote_dev.py --per-year 6 --private-dir "$PWD/.agents/local-data"
)
```

脚本拒绝非 loopback、其他目标库及 service/hostaddr 间接目标。相同私有 HMAC key 产生稳定对象 ID；重复导入 UPSERT 已选记录并新增批次 manifest，不清空旧样本。不要删除 key 后再导入，否则同源记录会产生新 ID。这不是生产同步器，源删除或抽样范围变化不会清理以前的样本。

新机器先建立两个隔离本地数据库、仅可读样本的运行账号，以及未提交的上述环境变量，再导入、启动和 setup。公共 quickstart 与测试仍完全使用合成数据，不依赖这个私有流程。

## 验证与限制

已通过：PostgreSQL + HTTP mock 组合查询、十进制值一致、来源 Evidence、另租户不返回样本、无凭证 401、mock 缺失/另租户 404、运行账号无业务写权限。旧页面回归已覆盖审计报告的两个 Mapping；最新分析链路通过 80 次指标核对、30 次规则对数和 10 次错误期间拒绝。

公共查询、Claim、Studio 已发布视图及 CLI 查询按租户激活版本读取；回归覆盖真实映射变化、旧请求固定版本和另一租户不切换。typed rules 与完整结构化身份（点查/Link；集合分析复合 Link 仍拒绝）已补齐；Action 恢复及生产授权按用户范围后置。当前派发仅为 [独立测试](analysis-test-goals.md)。本次数据与测试不关闭 T08B，也不证明全部 Studio 编辑流程完善。

# json-render 集成评估

日期：2026-09-20  
评估对象：[vercel-labs/json-render](https://github.com/vercel-labs/json-render)，核对提交 `3ad381881194e7011ad3ccd6d668033495a06c29`（v0.21.0）。

## 结论

建议做受限纵向 PoC，但不建议用 json-render 全量替换 SemaLoom 的卡片体系，也不建议把上游全部组件直接暴露给模型。

合适的定位是 **Chat 结果区的受控组合渲染器**：SemaLoom Runtime 继续拥有查询、精确数值、授权、规则结论、Evidence 和 Action 生命周期；服务端把已授权的确定性结果投影成一个版本化 presentation spec，json-render 只负责用经批准的 KPI、表格、图表、分组、下拉和选择卡进行组合。`EvidenceCard` 保持 SemaLoom 领域组件，可被新 renderer 引用或包裹，而不是被通用 `Card` 取代。

## 能力与边界

- 官方把 json-render 定义为 Generative UI framework：用 catalog 限制可用组件和 action，并支持 JSON spec、流式 patch、状态、条件显示、repeat、动态 props 与 action binding。[README](https://github.com/vercel-labs/json-render/blob/main/README.md)
- React 集成与当前 Vite/React 架构兼容；核心包为 `@json-render/core` 和 `@json-render/react`。v0.21.0 的 React renderer peer dependency 是 React `^19.2.3`，本仓库锁文件当前解析到 React 19.3.0，版本线上可兼容。[React package](https://github.com/vercel-labs/json-render/blob/main/packages/react/package.json)
- `@json-render/shadcn` 提供 36 个布局、导航、弹层、内容、反馈和输入组件，包括 Table、Select、DropdownMenu、Tabs、Dialog、Drawer、Accordion、Pagination 等。[shadcn README](https://github.com/vercel-labs/json-render/blob/main/packages/shadcn/README.md)
- 这 36 个组件**不包含图表**。官方 dashboard 示例的 BarChart/LineChart 是项目自定义 catalog component，并另行依赖 Recharts；因此“各种报表”需要 SemaLoom 自己定义语义化图表 catalog，json-render 负责组合而非提供 BI 能力。[dashboard catalog](https://github.com/vercel-labs/json-render/blob/main/examples/dashboard/lib/render/catalog.ts)、[dashboard registry](https://github.com/vercel-labs/json-render/blob/main/examples/dashboard/lib/render/registry.tsx)
- Web、PDF、Email 等 renderer 都存在，但 catalog/组件实现不同；不能假设同一 Web spec 无改造即可生成正式报表 PDF。[Packages](https://github.com/vercel-labs/json-render/blob/main/README.md#packages)
- Apache-2.0 与 SemaLoom 一致。[LICENSE](https://github.com/vercel-labs/json-render/blob/main/LICENSE)

## 为什么不能直接“全部利用上”

1. **与现有设计所有权冲突**：`docs/DESIGN.md` 要求只有一套基础组件、统一 `Modal`，并明确不建设通用低代码页面引擎。直接引入整套 shadcn 会形成普通 CSS/项目组件与 Tailwind/Radix 组件的双轨实现。
2. **事实与证据不能由模型排版逻辑拥有**：SemaLoom 要求事实卡来自服务器引擎，Evidence 重新按当前权限过滤，AI 文本不是审计证据。模型生成 spec 不能添加、删减、重算或隐藏事实与证据。
3. **上游 catalog 是约束机制，不是完整安全边界**：官方提供 catalog schema 和结构校验，但 renderer 本身接受 `Spec`，未知组件默认跳过；多组件 props 校验也不应替代本项目的服务端 discriminated validation。SemaLoom 必须在保存/下发前按组件类型逐项校验 props、节点数、深度、数据量和 action。[schema source](https://github.com/vercel-labs/json-render/blob/main/packages/core/src/schema.ts)、[spec validator](https://github.com/vercel-labs/json-render/blob/main/packages/core/src/spec-validator.ts)、[React renderer](https://github.com/vercel-labs/json-render/blob/main/packages/react/src/renderer.tsx)
4. **不应开放所有通用能力**：上游 `Image`/`Avatar` 可接收 `src`，`Link` 可接收 `href`；直接开放会违背当前 Chat 禁止外部图片自动加载和请求不接受 destination URL 的约束。[shadcn components](https://github.com/vercel-labs/json-render/blob/main/packages/shadcn/src/components.tsx)
5. **Action 名称相同但语义不同**：json-render action 是 UI 事件机制；SemaLoom Action 是带计划、批准、执行和核验的业务生命周期。两者必须分层命名，UI action 不能直接代表业务写入。
6. **成熟度需要隔离**：项目仍标为 Vercel Labs，v0.20.0 包含 renderer bridge breaking change，v0.21.0 又增加实验性组合能力。应精确锁版本并通过适配层和契约测试隔离上游变化。[CHANGELOG](https://github.com/vercel-labs/json-render/blob/main/CHANGELOG.md)

## 推荐组件目录

首个 catalog 只开放真实需要且能验收的组件：

| 类别 | 建议组件 | 数据/行为所有者 |
| --- | --- | --- |
| 布局 | `ResultStack`、`ResultGrid`、`Section`、`Tabs`、`Disclosure` | renderer |
| 业务结果 | `MetricValue`、`ClaimResult`、`ComparisonSummary`、`StatusNotice` | 服务端确定性结果 |
| 报表 | `DataTable`、`BarChart`、`LineChart`、后续 `ShareChart` | 服务端给定 series、标签、单位和精确显示值；浏览器不重算金额 |
| 选择 | `ChoiceCards`、`ChoiceSelect`、`PeriodSelect` | 只提交服务端签发的 option id/revision |
| 审计 | `EvidenceRef`、现有 `EvidenceCard`、现有 `Modal` | SemaLoom Evidence/权限层 |
| 局部状态 | 展开、tab、排序展示、图表/表格切换 | 客户端 UI state |

首版不开放任意 `Link`、外部 `Image`、通用网络请求、任意 navigation、computed function、模型声明的 action 名或业务 Action 执行。

## 推荐数据流

```text
SemanticQuery / Claim
  -> Runtime 生成确定性结果与 Evidence
  -> 服务端授权过滤
  -> Presentation adapter 生成并校验 versioned spec
  -> json-render React renderer
  -> SemaLoom 自有业务组件 registry
```

AI 可以在后续阶段从服务器给出的**候选布局**中选择，但不得生成数值、Evidence、option id、URL 或业务 action 参数。即使允许 AI 组合，服务端也应把 spec 当不可信输入重新校验，并保证所有证据强制展示入口不受 spec 控制。

## 分阶段建议与 go/no-go

1. **PoC**：只引入精确锁定的 `@json-render/core`、`@json-render/react`、Zod；沿用普通 CSS、现有 `Modal` 和 EvidenceCard，不引入 `@json-render/shadcn`/Tailwind。覆盖一个真实纵向场景：分组指标结果同时展示 KPI、表格、柱状图、年度下拉和证据入口。
2. **交互接入**：ChoiceSelect 继续调用现有 `/v0.1/chat/choices`，只提交 option id/question revision；失败保留 pending 状态。
3. **受控生成**：PoC 稳定后再评估让模型选择布局；先保留服务端确定性模板作为降级路径。
4. **报表扩展**：按语义需要添加图表，不以“上游有组件”为理由开放。PDF/导出单独定义 catalog 与一致性验收。

Go 条件：构建体积和交互性能可接受；键盘/200% 缩放/窄屏通过；断网无外部资源请求；跨租户和字段权限无泄露；图表标签与表格精确值一致；无组件/坏 spec 明确降级而非空白；升级被适配层测试约束。

No-go 条件：必须迁移到第二套设计系统才能使用；事实或 Evidence 必须交给模型生成；无法对 spec/action/data volume 做服务端强校验；或引入后仍需长期维护旧、新两套等价结果卡。

## 最终判断

- 用作受控结果组合层：**推荐**。
- 替换所有 `EvidenceCard`：**不推荐**。
- 全量启用 36 个 shadcn 组件：**不推荐**；按需选取或用 SemaLoom wrapper 实现。
- 下拉、Tabs、弹层、复杂选择：**适合**，但提交协议仍用现有签名 option。
- 多种报表/图表：**可以**，需要自定义语义图表组件和独立 chart library；json-render 本身不是报表计算或 BI 引擎。

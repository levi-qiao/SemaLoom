# 0009 — Studio 依赖按交互复杂度引入

状态：accepted。替代 ADR-0008 中“图谱直接采用 React Flow”的无条件选择；单应用交付、PostgreSQL 元数据和语义投影决策保持不变。

## 决策

Studio 保持 React、TypeScript、Vite 和 CSS variables。当前只读实体图规模小，使用原生 SVG 与语义化 HTML，避免为了少量节点引入图谱、组件、表格和状态管理框架。模型数据、选择状态和 URL 状态不使用 SVG 坐标或第三方节点对象作为公共契约。

结构化图编辑、平移缩放、自动布局、虚拟化或复杂表格出现并通过对应验收时，再分别评估 React Flow、ELK.js、TanStack Table/Query、Radix 或同类库。每个依赖必须消除已经存在的实现负担，并记录许可证、锁定版本和替换边界；不得同时维护自研和第三方两套等价实现。

## 影响与验收

当前发行物只有 React 运行依赖，构建结果仍嵌入 Python wheel，由同一个 FastAPI 进程提供。T09B/C 已使用项目组件完成结构化表单、缩放和浏览器回归，没有出现引入另一套前端基础设施的必要；后续引入时仍须补充键盘、密集图和浏览器回归证据。

这项决策降低 pre-alpha 的供应链和维护成本，但原生 SVG 不代表已经满足大图编辑能力。超过当前只读投影范围时，必须先完成性能和可访问性交互验证，不能用“零依赖”作为拒绝成熟基础设施的理由。

## 修订（图谱连线编辑）

产品要求 ProcessOn 式拖点、锚点拉线、边随节点移动且不重排。该交互已超出原生 SVG 手写图的合理范围。Studio 图谱改用 MIT 许可的 `@xyflow/react`（React Flow）作为画布实现：节点位置与连线状态留在前端视图，语义契约仍只使用 ObjectType/Link 标识。删除自研力导向布局，避免两套画布并存。

## 修订（统一直角布局，2026-09-15）

六实体八关系的实际模型已经出现曲线穿过实体、标签远离关系且互相遮挡。采用 `elkjs 0.12.0` 的 layered / ORTHOGONAL 布局，统一输出节点矩形、边折点和标签占位；React Flow 继续负责渲染、选择、拖动和连线。参考 [ELK 官方实现](https://github.com/kieler/elkjs) 与 [React Flow 官方 ELK 示例](https://reactflow.dev/examples/layout/elkjs)。按 EPL-2.0 使用未修改的库，锁定依赖并随发行物附许可证；仅进入图谱时加载布局模块。

删除原 degree/grid 布局、二次曲线、独立标签扫描和虚线引导，避免维护两套自动布局。实体改为名称内嵌的矩形卡片，布局尺寸覆盖全部文字。手动拖动使用 React Flow 的直角连线预览，不主动重排其他实体；需要重新避让时点击“自动整理”。不承诺任意非平面图无边交叉，也不把手动重叠当成已自动消解。布局失败显示重试，旧布局请求不能覆盖更新的拓扑。无语义数据迁移，坐标仍不写入本体定义。

布局方向随画布有效宽度选择：宽画布横向分层，较窄画布纵向分层；字体与标签占位尺寸一起维护。视图方向仍是通用展示规则，不属于领域配置或语义数据。

## 修订（受限结果组合，2026-09-20）

Chat 已出现同一次确定性结果需要 KPI、表格、柱状图、趋势图及后续选择控件共享一组数据的实际负担。采用 Apache-2.0 的 `@json-render/core` / `@json-render/react 0.21.0` 作为结果组合实现，采用 MIT 的 `recharts 3.10.1` 绘图；两者只在出现结构化结果时延迟加载。依赖版本由 pnpm lockfile 固定，完整许可随前端构建生成。

外部 seam 为 Chat 应用层的 `project_browser_answer(answer, bundle)`：它在执行与授权之后，从确定性查询结果生成版本化、通用且有界的 presentation projection；前端 `ResultPresentation(presentation)` 只验证和渲染该投影。KPI 使用标量 `values`，趋势、分布和表格使用已聚合且带 grain 的 `values`；逐条 `EvidenceTable` 只属于审计层，不得代替聚合结果绘图。查询的 `timeGrain` 决定趋势默认视图，其他单维分组默认分布，多维结果默认表格。EvidenceColumn 的 `role / valueType / unit` 是数据语义而非布局配置，adapter 负责填写，浏览器不根据中文/英文标签、领域命名空间或数值外形猜测类别与度量。json-render Spec、catalog、renderer 类型仍不进入 Python core/runtime 或传输契约。本体 YAML 不增加图表、组件或布局字段。

首版不接受模型或调用方提供 projection/spec，不开放 URL、Image、任意 action、computed function 或网络请求。业务金额、统计、Claim、权限与 Evidence 继续由 SemaLoom 引擎拥有；projection 同时携带原始精确值和人类显示值，图表只绘制坐标。旧会话没有 projection 时继续显示正文与 Evidence，不在前端恢复启发式推断。

保留现有 `EvidenceCard` 与 `Modal` 为审计层，不另引入 shadcn/Tailwind 基础组件，避免两套设计系统。删除该前后端模块时，证据角色解释、KPI、视图切换、行列限额、tooltip、无动画偏好和降级行为会重新散落到 adapter 与 Chat 调用方，因此该模块形成有实际深度的 seam，而不是透传 wrapper。

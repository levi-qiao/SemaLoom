import { useEffect, useMemo, useState, type ReactNode } from "react";
import { defineCatalog, validateSpec, type Spec } from "@json-render/core";
import { defineRegistry, JSONUIProvider, Renderer } from "@json-render/react";
import { schema } from "@json-render/react/schema";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { z } from "zod";
type Tone = "neutral" | "positive" | "warning" | "danger";
type Column = { key: string; label: string };
type Series = { key: string; label: string; unit?: string };
type ReportRow = Record<string, string>;

const MAX_NODES = 48;
const MAX_ROWS = 50;
const palette = ["#1f6f5f", "#2563eb", "#d97706", "#7c3aed", "#0891b2"];

export function formatExactNumber(raw: unknown): string {
  const str = naturalNumber(raw);
  if (!/^-?\d+(?:\.\d+)?$/.test(str)) return str;
  const [intPart, decPart] = str.split(".");
  if (Math.abs(Number(intPart)) < 10000) {
    return decPart !== undefined ? `${intPart}.${decPart}` : intPart;
  }
  const formattedInt = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decPart !== undefined ? `${formattedInt}.${decPart}` : formattedInt;
}

function formatYAxisTick(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "0";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e8) {
    const v = (abs / 1e8).toFixed(2).replace(/\.?0+$/, "");
    return `${sign}${v} 亿`;
  }
  if (abs >= 1e4) {
    const v = (abs / 1e4).toFixed(2).replace(/\.?0+$/, "");
    return `${sign}${v} 万`;
  }
  return `${sign}${abs.toLocaleString()}`;
}

const presentationSchema = z.object({
  version: z.literal("semaloom/presentation-v0.1"),
  metrics: z.array(z.object({
    id: z.string(), label: z.string(), value: z.string(), displayValue: z.string(),
    unit: z.string(), meta: z.string(), tone: z.enum(["neutral", "positive", "warning", "danger"]),
  })).max(8),
  reports: z.array(z.object({
    id: z.string(), title: z.string(), description: z.string(),
    columns: z.array(z.object({
      key: z.string(), semanticId: z.string(), label: z.string(),
      role: z.enum(["CATEGORY", "DIMENSION", "MEASURE"]).nullable(),
      valueType: z.string().nullable(), unit: z.string().nullable(),
    })).max(12),
    rows: z.array(z.record(z.string(), z.string())).max(MAX_ROWS),
    categoryKey: z.string(),
    series: z.array(z.object({key: z.string(), label: z.string(), unit: z.string().optional()})).max(4),
    preferredView: z.enum(["table", "bar", "line"]).default("bar"),
    truncated: z.boolean(), rowCount: z.number().int().nonnegative(),
  })).max(4),
});

const resultCatalog = defineCatalog(schema, {
  components: {
    ResultStack: {
      props: z.object({ label: z.string() }),
      slots: ["default"],
      description: "A bounded stack of deterministic business result views.",
    },
    ResultIntro: {
      props: z.object({ kicker: z.string(), title: z.string(), description: z.string() }),
      description: "A compact introduction for engine-generated result visuals.",
    },
    MetricGrid: {
      props: z.object({ label: z.string() }),
      slots: ["default"],
      description: "A responsive grid of exact engine values.",
    },
    MetricValue: {
      props: z.object({
        label: z.string(),
        value: z.string(),
        unit: z.string(),
        meta: z.string(),
        tone: z.enum(["neutral", "positive", "warning", "danger"]),
      }),
      description: "An exact value supplied by the SemaLoom engine.",
    },
    ReportExplorer: {
      props: z.object({
        title: z.string(),
        description: z.string(),
        columns: z.array(z.object({ key: z.string(), label: z.string() })).max(12),
        rows: z.array(z.record(z.string(), z.string())).max(MAX_ROWS),
        categoryKey: z.string(),
        series: z.array(z.object({ key: z.string(), label: z.string(), unit: z.string().optional() })).max(4),
        preferredView: z.enum(["table", "bar", "line"]),
      }),
      description: "A table with optional bar and line views over the same authorized rows.",
    },
  },
  actions: {},
});

function ResultStack({ children }: { children?: ReactNode }) {
  return <section className="result-presentation" aria-label="业务结果概览">{children}</section>;
}

function ResultIntro({ props }: { props: { kicker: string; title: string; description: string } }) {
  return <header className="result-intro">
    <span>{props.kicker}</span>
    <div>
      <h3>{props.title}</h3>
      <p>{props.description}</p>
    </div>
  </header>;
}

function MetricGrid({ children, props }: { children?: ReactNode; props: { label: string } }) {
  return <div className="result-metric-grid" aria-label={props.label}>{children}</div>;
}

function MetricValue({ props }: { props: { label: string; value: string; unit: string; meta: string; tone: Tone } }) {
  const formatted = formatExactNumber(props.value);
  return (
    <article className="result-metric" data-tone={props.tone}>
      <div className="result-metric-head">
        <span className="result-metric-label">{props.label}</span>
        {props.tone !== "neutral" && (
          <span className={`result-metric-badge tone-${props.tone}`}>
            {props.tone === "positive" ? "正常" : props.tone === "warning" ? "关注" : "异常"}
          </span>
        )}
      </div>
      <strong className="result-metric-num">
        <span className="result-metric-value">{formatted}</span>
        {props.unit ? <small className="result-metric-unit">{props.unit}</small> : null}
      </strong>
      {props.meta ? <p className="result-metric-meta">{props.meta}</p> : null}
    </article>
  );
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}

function ExactTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ dataKey?: string | number; name?: string; payload?: ReportRow; color?: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="result-chart-tooltip">
      <strong className="tooltip-title">{label}</strong>
      <div className="tooltip-items">
        {payload.map((item, index) => {
          const key = String(item.dataKey ?? "");
          return (
            <div key={`${key}-${index}`} className="tooltip-row">
              <span className="tooltip-dot" style={{ backgroundColor: item.color }} />
              <span className="tooltip-label">{item.name}：</span>
              <span className="tooltip-val">{item.payload?.[`${key}Exact`] ?? "—"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ReportTable({ columns, rows, seriesKeys }: { columns: Column[]; rows: ReportRow[]; seriesKeys: Set<string> }) {
  return (
    <div className="result-table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map(column => (
              <th key={column.key} scope="col" className={seriesKeys.has(column.key) ? "is-numeric" : ""}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map(column => {
                const isNumeric = seriesKeys.has(column.key);
                const rawVal = row[column.key];
                return (
                  <td key={column.key} className={isNumeric ? "is-numeric" : ""}>
                    {isNumeric ? formatExactNumber(rawVal) : (rawVal || "—")}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportExplorer({ props }: { props: { title: string; description: string; columns: Column[]; rows: ReportRow[]; categoryKey: string; series: Series[]; preferredView: "table" | "bar" | "line" } }) {
  const canChart = props.rows.length > 1 && props.series.length > 0;
  const [view, setView] = useState<"table" | "bar" | "line">(canChart ? props.preferredView : "table");
  const [seriesKey, setSeriesKey] = useState("all");
  const reducedMotion = useReducedMotion();
  const seriesKeys = useMemo(() => new Set(props.series.map(s => s.key)), [props.series]);
  const visibleSeries = seriesKey === "all" ? props.series : props.series.filter(item => item.key === seriesKey);
  const chartRows = useMemo(() => props.rows.map(row => {
    const converted: Record<string, string | number> = { ...row };
    for (const item of props.series) {
      const value = Number(row[item.key]);
      converted[item.key] = Number.isFinite(value) ? value : 0;
      converted[`${item.key}Exact`] = `${formatExactNumber(row[item.key])}${item.unit ? ` ${item.unit}` : ""}`;
    }
    return converted;
  }), [props.rows, props.series]);
  const categoryLabel = props.columns.find(column => column.key === props.categoryKey)?.label ?? "类别";
  const chartLabel = `${props.title}。横轴为${categoryLabel}，包含 ${props.rows.length} 项。`;

  return <section className="result-explorer">
    <div className="result-explorer-head">
      <div><h4>{props.title}</h4><p>{props.description}</p></div>
      {canChart ? <div className="result-explorer-controls">
        {props.series.length > 1 ? <label className="result-series-select">图表指标
          <select value={seriesKey} onChange={event => setSeriesKey(event.target.value)}>
            <option value="all">全部指标</option>
            {props.series.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}
          </select>
        </label> : null}
        <div className="result-view-tabs" role="tablist" aria-label={`${props.title}展示方式`}>
          {(["bar", "line", "table"] as const).map(option => <button
            type="button"
            role="tab"
            aria-selected={view === option}
            key={option}
            onClick={() => setView(option)}
          >{option === "bar" ? "柱状" : option === "line" ? "趋势" : "表格"}</button>)}
        </div>
      </div> : null}
    </div>
    <div className="result-view" role="tabpanel">
      {view === "table" || !canChart ? <ReportTable columns={props.columns} rows={props.rows} seriesKeys={seriesKeys} /> : <div className="result-chart" role="img" aria-label={chartLabel}>
        <ResponsiveContainer width="100%" height="100%">
          {view === "bar" ? <BarChart data={chartRows} margin={{ top: 16, right: 16, bottom: 8, left: 6 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.06)" />
            <XAxis dataKey={props.categoryKey} tickLine={false} axisLine={false} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
            <YAxis tickLine={false} axisLine={false} width={64} tickFormatter={formatYAxisTick} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
            <Tooltip content={<ExactTooltip />} cursor={{ fill: "rgba(31, 111, 95, 0.05)" }} />
            {visibleSeries.map((item, index) => <Bar key={item.key} dataKey={item.key} name={item.label} fill={palette[index % palette.length]} radius={[6, 6, 0, 0]} maxBarSize={48} isAnimationActive={!reducedMotion} />)}
          </BarChart> : <LineChart data={chartRows} margin={{ top: 16, right: 20, bottom: 8, left: 6 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.06)" />
            <XAxis dataKey={props.categoryKey} tickLine={false} axisLine={false} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
            <YAxis tickLine={false} axisLine={false} width={64} tickFormatter={formatYAxisTick} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
            <Tooltip content={<ExactTooltip />} />
            {visibleSeries.map((item, index) => <Line key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={palette[index % palette.length]} strokeWidth={2.5} dot={{ r: 3.5, strokeWidth: 1.5, fill: "#ffffff", stroke: palette[index % palette.length] }} activeDot={{ r: 6, stroke: "#ffffff", strokeWidth: 2, fill: palette[index % palette.length] }} isAnimationActive={!reducedMotion} />)}
          </LineChart>}
        </ResponsiveContainer>
      </div>}
    </div>
  </section>;
}

const { registry } = defineRegistry(resultCatalog, {
  components: { ResultStack, ResultIntro, MetricGrid, MetricValue, ReportExplorer },
});

function naturalNumber(value: unknown): string {
  const raw = String(value ?? "—");
  if (!/^-?\d+(?:\.\d+)?$/.test(raw)) return raw;
  if (!raw.includes(".")) return raw;
  const compact = raw.replace(/(\.\d*?[1-9])0+$/, "$1").replace(/\.0+$/, "");
  return compact === "-0" ? "0" : compact;
}

function buildPresentation(input: unknown): Spec | null {
  const parsed = presentationSchema.safeParse(input);
  if (!parsed.success) return null;
  const presentation = parsed.data;
  const elements: Spec["elements"] = {};
  const metricKeys: string[] = [];
  const reportKeys: string[] = [];
  let nodeCount = 3;

  for (const metric of presentation.metrics) {
    if (nodeCount >= MAX_NODES) break;
    const key = `metric-${metricKeys.length}`;
    elements[key] = { type: "MetricValue", props: {
      label: metric.label, value: metric.displayValue, unit: metric.unit,
      meta: metric.meta, tone: metric.tone,
    }, children: [] };
    metricKeys.push(key); nodeCount += 1;
  }
  for (const report of presentation.reports) {
    if (nodeCount >= MAX_NODES) break;
    const key = `report-${reportKeys.length}`;
    elements[key] = { type: "ReportExplorer", props: {
      title: report.title, description: report.description,
      columns: report.columns.map(column => ({key: column.key, label: column.label})),
      rows: report.rows, categoryKey: report.categoryKey, series: report.series,
      preferredView: report.preferredView,
    }, children: [] };
    reportKeys.push(key); nodeCount += 1;
  }

  if (!metricKeys.length && !reportKeys.length) return null;
  const children = ["intro"];
  elements.intro = { type: "ResultIntro", props: {
    kicker: "确定性结果", title: "业务结果概览",
    description: "数值与判断来自同一次引擎执行；完整口径和来源保留在下方核验区。",
  }, children: [] };
  if (metricKeys.length) {
    elements.metrics = { type: "MetricGrid", props: { label: "关键结果" }, children: metricKeys };
    children.push("metrics");
  }
  children.push(...reportKeys);
  elements.root = { type: "ResultStack", props: { label: "业务结果概览" }, children };
  const spec: Spec = { root: "root", elements };
  if (Object.keys(elements).length > MAX_NODES) return null;
  const catalogResult = resultCatalog.validate(spec);
  if (!catalogResult.success || !validateSpec(spec).valid) return null;
  return spec;
}

export function ResultPresentation({ presentation }: { presentation?: unknown }) {
  const spec = useMemo(() => buildPresentation(presentation), [presentation]);
  if (!spec) return null;
  return <JSONUIProvider registry={registry}>
    <Renderer spec={spec} registry={registry} />
  </JSONUIProvider>;
}

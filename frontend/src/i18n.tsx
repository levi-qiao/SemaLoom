import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export type Locale = "zh-CN" | "en";
type Values = Record<string, string | number>;

const en: Record<string, string> = {
  "language.label": "Language",
  "language.zh": "中文",
  "language.en": "English",
  "nav.chat": "Ask",
  "nav.graph": "Graph",
  "nav.objects": "Entities",
  "nav.sources": "Data sources",
  "nav.apis": "API contracts",
  "view.chat.title": "Business Q&A",
  "view.chat.description": "Ask in business language and inspect rule results and evidence.",
  "view.graph.title": "Ontology graph",
  "view.graph.description": "Explore declared relationships and mapping previews.",
  "view.objects.title": "Entities",
  "view.objects.description": "Maintain business objects, properties, and source mappings.",
  "view.sources.title": "Data sources",
  "view.sources.description": "Configure physical source connections and inspect their schema.",
  "view.apis.title": "API contracts",
  "view.apis.description": "Maintain service contracts, OpenAPI imports, and authentication bindings.",
  "common.close": "Close",
  "common.reload": "Reload",
  "common.search": "Search name or ID",
  "common.select": "Select",
  "common.current": "Current",
  "environment.local": "Local development",
  "environment.samples": "Inspect synthetic samples under data sources",
  "chat.title": "Business analysis assistant",
  "chat.checking": "Checking connection",
  "chat.modelSuffix": "current runtime model",
  "chat.history": "History",
  "chat.new": "New conversation",
  "chat.empty.eyebrow": "Business knowledge and analysis",
  "chat.empty.title": "Start with a business question",
  "chat.empty.description": "Find business knowledge, compare data, or evaluate a rule. Missing scope is collected before an answer.",
  "chat.suggestion.objects.tag": "Objects and entities",
  "chat.suggestion.objects.question": "What business objects can I analyze?",
  "chat.suggestion.objects.description": "Browse declared concepts, identities, and key business properties.",
  "chat.suggestion.rules.tag": "Rules and compliance",
  "chat.suggestion.rules.question": "What business rules and scopes are defined?",
  "chat.suggestion.rules.description": "Inspect deterministic rules, applicability, and prerequisites.",
  "chat.suggestion.metrics.tag": "Metrics and comparisons",
  "chat.suggestion.metrics.question": "Which metrics can be compared?",
  "chat.suggestion.metrics.description": "Review available metrics before choosing scope and aggregation.",
  "chat.suggestion.time.tag": "Time analysis",
  "chat.suggestion.time.question": "Which data can be analyzed by year?",
  "chat.suggestion.time.description": "Review time coverage and choose a suitable result view.",
  "chat.you": "You",
  "chat.answer.definition": "Ontology explanation · AI interpretation",
  "chat.answer.engine": "Engine result",
  "chat.answer.ai": "AI interpretation",
  "chat.definitionNotice": "This explanation uses ontology definitions. It does not assert that records exist or sources are available.",
  "chat.visualizing": "Preparing result view…",
  "chat.audit.title": "Evidence and provenance",
  "chat.audit.description": "Expand to inspect definitions, calculations, and physical sources",
  "chat.followUps": "Continue analysis",
  "chat.version": "Semantic release {digest} · engine values and judgments are authoritative",
  "chat.choice.badge": "Confirm business scope",
  "chat.choice.select": "Select",
  "chat.choice.other": "Additional context",
  "chat.choice.otherPlaceholder": "Add a business condition or definition…",
  "chat.choice.continue": "Continue",
  "chat.question": "Business question",
  "chat.placeholder": "Ask a business question. Enter to send; Shift + Enter for a new line",
  "chat.stop": "Stop",
  "chat.send": "Send",
  "chat.footnote": "Expand evidence when needed. Missing scope is requested before calculation.",
  "chat.history.list": "Conversation history",
  "chat.history.loading": "Loading history…",
  "chat.history.empty": "No saved conversations",
  "chat.history.untitled": "Untitled conversation",
  "chat.history.turns": "{count} turns",
  "result.overview": "Business result overview",
  "result.relationships": "Business relationships",
  "result.relationships.note": "Relationships declared by the ontology; query records separately.",
  "result.category": "Category",
  "result.metric": "Chart metric",
  "result.allMetrics": "All metrics",
  "result.view": "{title} view",
  "result.view.bar": "Bar",
  "result.view.line": "Trend",
  "result.view.table": "Table",
  "result.more": " Showing {count} rows. Narrow the query to inspect more.",
  "result.key": "Key results",
};

const I18nContext = createContext<{ locale: Locale; setLocale: (locale: Locale) => void; t: (key: string, values?: Values) => string } | null>(null);

export function resolveLocale(value?: string | null): Locale {
  return value?.toLowerCase().startsWith("en") ? "en" : "zh-CN";
}

export function currentLocale(): Locale {
  return resolveLocale(document.documentElement.lang || navigator.language);
}

function interpolate(template: string, values: Values = {}) {
  return template.replace(/\{(\w+)\}/g, (_match, key) => String(values[key] ?? ""));
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() =>
    resolveLocale(localStorage.getItem("semaloom.locale") || navigator.language),
  );
  const value = useMemo(() => ({
    locale,
    setLocale(next: Locale) {
      localStorage.setItem("semaloom.locale", next);
      document.documentElement.lang = next;
      setLocaleState(next);
    },
    t(key: string, values?: Values) {
      return interpolate(locale === "en" ? (en[key] ?? key) : zh[key] ?? key, values);
    },
  }), [locale]);
  document.documentElement.lang = locale;
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error("I18nProvider is required");
  return value;
}

const zh: Record<string, string> = {
  "language.label": "语言",
  "language.zh": "中文",
  "language.en": "English",
  "nav.chat": "问答", "nav.graph": "图谱", "nav.objects": "实体", "nav.sources": "数据源", "nav.apis": "API 接口",
  "view.chat.title": "业务问答", "view.chat.description": "用业务语言提问，查看规则结果与来源依据。",
  "view.graph.title": "图谱", "view.graph.description": "看关系和试读映射。",
  "view.objects.title": "实体", "view.objects.description": "维护业务对象、属性和来源字段对应。",
  "view.sources.title": "数据源", "view.sources.description": "配置物理数据库连接，查看自动读取的结构。",
  "view.apis.title": "API 接口", "view.apis.description": "维护服务契约、OpenAPI 导入和鉴权绑定。",
  "common.close": "关闭", "common.reload": "重新载入", "common.search": "搜索名称或 ID", "common.select": "请选择", "common.current": "当前",
  "environment.local": "本地开发环境", "environment.samples": "业务样本请查看数据源",
  "chat.title": "业务分析助手", "chat.checking": "正在检查连接", "chat.modelSuffix": "基于当前运行模型", "chat.history": "历史会话", "chat.new": "新建对话",
  "chat.empty.eyebrow": "业务资料与分析", "chat.empty.title": "从一个业务问题开始", "chat.empty.description": "查找业务资料、比较数据或核验规则。条件不完整时，先补充再回答。",
  "chat.suggestion.objects.tag": "对象与实体", "chat.suggestion.objects.question": "当前有哪些可分析的业务对象？", "chat.suggestion.objects.description": "浏览系统已声明的实体概念、身份键与关键业务属性",
  "chat.suggestion.rules.tag": "规则与合规", "chat.suggestion.rules.question": "当前模型有哪些业务规则和适用范围？", "chat.suggestion.rules.description": "查验确定性规则的判断标准、适用条件与前置依赖",
  "chat.suggestion.metrics.tag": "指标与比较", "chat.suggestion.metrics.question": "有哪些指标可以用来做比较？", "chat.suggestion.metrics.description": "先了解可用指标，再选择比较范围和统计方式",
  "chat.suggestion.time.tag": "时序分析", "chat.suggestion.time.question": "哪些数据可以按年度分析？", "chat.suggestion.time.description": "了解时间范围，选择适合的问题与展示形式",
  "chat.you": "你", "chat.answer.definition": "本体说明 · AI 解读", "chat.answer.engine": "引擎结果说明", "chat.answer.ai": "AI 解读",
  "chat.definitionNotice": "以下解释基于本体定义；尚未核查实际记录、年份覆盖或来源可用性。",
  "chat.visualizing": "正在整理可视化结果…", "chat.audit.title": "核验与来源", "chat.audit.description": "展开查看口径、逐项计算与物理来源", "chat.followUps": "继续分析",
  "chat.version": "语义版本 {digest} · 数值与判断以引擎结果为准", "chat.choice.badge": "业务口径确认", "chat.choice.select": "请选择", "chat.choice.other": "补充说明", "chat.choice.otherPlaceholder": "请补充业务条件或口径…", "chat.choice.continue": "按补充说明继续",
  "chat.question": "业务问题", "chat.placeholder": "输入业务问题，Enter 发送，Shift + Enter 换行", "chat.stop": "停止分析", "chat.send": "发送", "chat.footnote": "结果可展开查看来源；条件不完整时会先询问。",
  "chat.history.list": "历史会话列表", "chat.history.loading": "正在加载历史记录…", "chat.history.empty": "暂无历史会话记录", "chat.history.untitled": "未命名会话", "chat.history.turns": "{count} 轮问答",
  "result.overview": "业务结果概览", "result.relationships": "业务关系", "result.relationships.note": "模型中声明的关联，实际记录需另行查询。", "result.category": "类别", "result.metric": "图表指标", "result.allMetrics": "全部指标", "result.view": "{title}展示方式", "result.view.bar": "柱状", "result.view.line": "趋势", "result.view.table": "表格", "result.more": " 当前展示 {count} 行，更多明细请缩小查询范围。", "result.key": "关键结果",
};

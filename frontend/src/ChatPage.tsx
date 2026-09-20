import { lazy, Suspense, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiHeaders, checkedJson, errorDetail, type StudioSession } from "./api";

import { EvidenceCard, type Evidence } from "./EvidenceCard";
import { IconHistory, IconSend, IconSparkle } from "./icons";
const ResultPresentation = lazy(() => import("./ResultPresentation").then(module => ({ default: module.ResultPresentation })));
type Confidence = { score: number; level: string; label: string; factors: { code: string; detail: string }[] };
type FollowUp = { label: string; message: string };
type Answer = {
  textOrigin?: string; text: string; kind: string; releaseDigest: string; evidence: Evidence[];
  confidence?: Confidence; followUps?: FollowUp[]; presentation?: unknown;
};
type Turn = { question: string; answer?: Answer };
type ChoiceOption = { id: string; label: string; explanation: string; choice?: { kind: string; id: string } };
type ChoiceQuestion = { questionId: string; revision: number; slot: string; prompt: string; reason: string; control?: "CARDS" | "SELECT"; options: ChoiceOption[] };
type ConversationSummary = { id: string; releaseDigest: string; updatedAt: string; turnCount: number; title: string };

function formatHistoryTime(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const m = d.getMonth() + 1;
    const day = d.getDate();
    const h = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${m}月${day}日 ${h}:${min}`;
  } catch {
    return iso.slice(0, 16);
  }
}

function choiceControl(question: ChoiceQuestion): "CARDS" | "SELECT" {
  if (question.control) return question.control;
  const kinds = new Set(question.options.map(item => item.choice?.kind).filter(kind => kind && kind !== "ABORT" && kind !== "OTHER"));
  return kinds.size > 0 && [...kinds].every(kind => ["YEAR", "DIMENSION_VALUE", "CLAIM", "SUBJECT"].includes(kind ?? "")) ? "SELECT" : "CARDS";
}
const messages: Record<string, string> = {
  CHAT_NOT_CONFIGURED: "尚未配置模型连接。请在服务端配置 provider 后重新启动。",
  HARNESS_NOT_INSTALLED: "pi 模块依赖尚未安装，请完成 harness 安装后重试。",
  CHAT_HISTORY_SAVE_FAILED: "分析结果未能保存，本次未交付成功。请重试。",
  CHAT_BUSY: "当前对话正在处理，或服务正忙，请稍后再试。",
  CHAT_TIMEOUT: "本次分析超时，已停止。请缩小问题范围再试。",
  MODEL_REQUEST_FAILED: "模型调用未完成，请检查百炼连接或稍后重试。",
  ANSWER_NOT_VALIDATED: "模型没有提交可核验的回答，请换一种问法重试。",
  RELEASE_CHANGED_START_NEW_CHAT: "业务模型版本已变化，请新建对话，避免混用两个版本。",
  CONTEXT_LIMIT_START_NEW_CHAT: "已达到本次对话的上下文上限，请新建对话继续。",
  FORBIDDEN: "当前身份不能读取业务数据，请切换到有分析权限的身份。",
  SESSION_EXPIRED: "会话已失效，请重新登录。",
};
const toolNames: Record<string, string> = {
  list_semantics: "浏览当前业务模型", search_semantics: "查找业务定义", describe_semantic: "确认业务口径",
  find_objects: "定位业务对象", semantic_query: "读取指标与事实",
  prepare_semantic_query: "准备语义分析",
  evaluate_claim: "执行确定性规则", present_answer: "核对回答证据",
};

export function ChatPage({ session }: { session: StudioSession }) {
  const storageKey = `semaloom.chat.${session.tenant}.${session.subject}`;
  const [conversation, setConversation] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState<{ question: ChoiceQuestion; originalQuestion: string } | null>(null);
  const [picked, setPicked] = useState("");
  const [otherText, setOtherText] = useState("");
  const [config, setConfig] = useState<{ ready: boolean; model?: string; enabled: boolean } | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyList, setHistoryList] = useState<ConversationSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    fetch("/v0.1/chat/status", { signal: controller.signal }).then(checkedJson).then(value => {
      if (active) setConfig(value);
    }).catch(cause => { if (active) setError(messages[errorDetail(cause)] ?? errorDetail(cause)); });
    const saved = sessionStorage.getItem(storageKey);
    if (saved) fetch(`/v0.1/chat/conversations/${saved}`, { signal: controller.signal }).then(checkedJson).then(value => {
      if (active) {
        setConversation(saved);
        const restored = value.turns ?? [];
        const original = value.originalQuestion ?? "";
        if (value.pendingQuestion) {
          setPending({ question: value.pendingQuestion, originalQuestion: original });
          if (original && restored.at(-1)?.question !== original) {
            setTurns([...restored, { question: original }]);
          } else {
            setTurns(restored.length || !original ? restored : [{ question: original }]);
          }
        } else {
          setTurns(restored);
        }
      }
    }).catch(() => { if (active) sessionStorage.removeItem(storageKey); });
    return () => { active = false; controller.abort(); abort.current?.abort(); };
  }, [storageKey]);
  const answerStart = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!busy && !pending && turns.at(-1)?.answer) answerStart.current?.scrollIntoView({ block: "start" });
    else bottom.current?.scrollIntoView({ block: "nearest" });
  }, [turns, phase, busy, pending, picked]);

  function fresh() {
    abort.current?.abort(); setConversation(null); setTurns([]); setError(""); setPhase("");
    setPending(null); setPicked(""); setOtherText("");
    sessionStorage.removeItem(storageKey);
  }

  async function openHistory() {
    setHistoryOpen(true);
    setHistoryLoading(true);
    try {
      const res = await fetch("/v0.1/chat/conversations", { headers: apiHeaders() });
      if (!res.ok) await checkedJson(res);
      const data = await res.json();
      setHistoryList(data.conversations ?? []);
    } catch (cause) {
      setError(messages[errorDetail(cause)] ?? errorDetail(cause));
    } finally {
      setHistoryLoading(false);
    }
  }

  async function selectConversation(id: string) {
    if (busy || id === conversation) {
      setHistoryOpen(false);
      return;
    }
    abort.current?.abort();
    setError("");
    setPhase("");
    setPending(null);
    setPicked("");
    setOtherText("");
    setHistoryOpen(false);
    try {
      const res = await fetch(`/v0.1/chat/conversations/${id}`, { headers: apiHeaders() });
      if (!res.ok) await checkedJson(res);
      const value = await res.json();
      setConversation(id);
      sessionStorage.setItem(storageKey, id);
      const restored = value.turns ?? [];
      const original = value.originalQuestion ?? "";
      if (value.pendingQuestion) {
        setPending({ question: value.pendingQuestion, originalQuestion: original });
        if (original && restored.at(-1)?.question !== original) {
          setTurns([...restored, { question: original }]);
        } else {
          setTurns(restored.length || !original ? restored : [{ question: original }]);
        }
      } else {
        setTurns(restored);
      }
    } catch (cause) {
      setError(messages[errorDetail(cause)] ?? errorDetail(cause));
    }
  }
  async function send(preset?: string) {
    const question = (preset ?? text).trim();
    if (!question || busy || !config?.ready) return;
    const controller = new AbortController(); abort.current = controller;
    setText(""); setError(""); setBusy(true); setPhase("正在理解问题");
    setTurns(previous => [...previous, { question }]);
    let answered = false;
    try {
      const response = await fetch("/v0.1/chat/turns", {
        method: "POST", headers: apiHeaders(), signal: controller.signal,
        body: JSON.stringify({ message: question, conversationId: conversation }),
      });
      if (!response.ok) await checkedJson(response);
      if (!response.body) throw new Error("无法读取响应");
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1);
          if (!line.trim()) continue;
          const item = JSON.parse(line);
          if (item.type === "start") {
            setConversation(item.conversationId); sessionStorage.setItem(storageKey, item.conversationId);
          } else if (item.type === "progress") {
            setPhase(item.stage === "tool" ? toolNames[item.name] ?? "读取业务信息" : item.outcome === "error" ? `正在修正工具请求（${item.code}）` : "正在组织分析");
          } else if (item.type === "choice") {
            answered = true;
            setPending({ question: item.question, originalQuestion: item.originalQuestion ?? question });
            setPicked(""); setOtherText("");
          } else if (item.type === "answer") {
            answered = true;
            setTurns(previous => previous.map((t, index) => index === previous.length - 1 ? { ...t, answer: item.answer } : t));
          } else if (item.type === "error") throw new Error(messages[item.code] ?? item.code);
        }
      }
      if (!answered) throw new Error("连接已结束，但未收到完整回答，请重试。");
    } catch (cause) {
      setError(controller.signal.aborted ? "已停止本次分析。" : messages[errorDetail(cause)] ?? errorDetail(cause));
      setText(question);
      if (!answered) setTurns(previous => previous.slice(0, -1));
    } finally { setBusy(false); setPhase(""); abort.current = null; }
  }
  async function submitChoice(optionId?: string) {
    const selected = optionId ?? picked;
    if (!pending || !selected || !conversation || busy) return;
    const option = pending.question.options.find(item => item.id === selected);
    const isOther = option?.choice?.kind === "OTHER";
    if (isOther && !otherText.trim()) { setPicked(selected); return; }
    setBusy(true); setError("");
    try {
      const result = await fetch("/v0.1/chat/choices", {
        method: "POST", headers: apiHeaders(),
        body: JSON.stringify({
          conversationId: conversation, questionId: pending.question.questionId,
          revision: pending.question.revision, optionIds: [selected],
          ...(isOther ? { otherText: otherText.trim() } : {}),
        }),
      }).then(checkedJson);
      if (result.status === "ABORTED") { setPending(null); setPicked(""); setOtherText(""); return; }
      if (result.status === "NEEDS_INPUT" && result.question) {
        setPending({ question: result.question, originalQuestion: pending.originalQuestion });
        setPicked(""); setOtherText("");
        return;
      }
      if (result.answerReady) {
        const answer = {
          kind: result.status === "UNSUPPORTED" ? "unsupported" : (result.kind ?? "answer"),
          textOrigin: result.textOrigin ?? "ENGINE",
          text: result.text ?? "已按发布口径完成计算。",
          releaseDigest: result.plan?.releaseDigest ?? result.releaseDigest ?? "",
          evidence: result.evidence ?? [{ id: "e1", tool: "prepare_semantic_query", result: result.population ?? result.result ?? result }],
          confidence: result.confidence, followUps: result.followUps ?? [], presentation: result.presentation,
        };
        setTurns(previous => {
          const last = previous[previous.length - 1];
          if (last && last.question === pending.originalQuestion && !last.answer) {
            return previous.map((turn, index) => index === previous.length - 1 ? { ...turn, answer } : turn);
          }
          return [...previous, { question: pending.originalQuestion, answer }];
        });
        setPending(null); setPicked(""); setOtherText("");
        return;
      }
      if (result.status === "SOURCE_ERROR" || result.status === "UNSUPPORTED") {
        setError(result.errorMessage ?? result.errorCode ?? "当前无法确定结果，请核对条件或稍后重试。");
      }
    } catch (cause) {
      setError(messages[errorDetail(cause)] ?? errorDetail(cause));
    } finally { setBusy(false); }
  }

  return <section className="chat-page" aria-label="业务问答">
    <div className="chat-toolbar">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ display: "grid", placeItems: "center", width: 28, height: 28, borderRadius: 6, background: "var(--accent-subtle)", color: "var(--accent)" }}>
          <IconSparkle size={15} />
        </span>
        <div>
          <strong>业务分析助手</strong>
          <small>{config?.model ?? "正在检查连接"} · 基于当前运行模型</small>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="secondary" type="button" onClick={() => void openHistory()} disabled={busy}>
          <IconHistory size={14} style={{ marginRight: 4, verticalAlign: "middle" }} />
          历史会话
        </button>
        <button className="secondary" onClick={fresh} disabled={busy}>新建对话</button>
      </div>
    </div>
    <div className="chat-history" aria-live="polite">
      {!turns.length && !pending && <div className="chat-empty">
        <div className="chat-empty-badge">
          <IconSparkle size={13} />
          <span>企业级语义智能体</span>
        </div>
        <h2>从一个业务问题开始</h2>
        <p className="chat-empty-sub">基于已发布的语义本体模型与确定性计算引擎，实时穿透业务对象、聚合度量与合规判断。</p>
        <div className="chat-empty-grid">
          <button type="button" className="chat-empty-card" onClick={() => setText("当前有哪些可分析的业务对象？")}>
            <span className="chat-empty-card-tag">对象与实体</span>
            <strong className="chat-empty-card-title">当前有哪些可分析的业务对象？</strong>
            <small className="chat-empty-card-desc">浏览系统已声明的实体概念、身份键与关键业务属性</small>
          </button>
          <button type="button" className="chat-empty-card" onClick={() => setText("当前模型有哪些业务规则和适用范围？")}>
            <span className="chat-empty-card-tag">规则与合规</span>
            <strong className="chat-empty-card-title">当前模型有哪些业务规则和适用范围？</strong>
            <small className="chat-empty-card-desc">查验确定性规则的判断标准、适用条件与前置依赖</small>
          </button>
          <button type="button" className="chat-empty-card" onClick={() => setText("各供应商按采购金额排名前五的是哪些？")}>
            <span className="chat-empty-card-tag">度量与排序</span>
            <strong className="chat-empty-card-title">各供应商按采购金额排名前五的是哪些？</strong>
            <small className="chat-empty-card-desc">执行多维聚合与排序，由引擎提供完整计算溯源</small>
          </button>
          <button type="button" className="chat-empty-card" onClick={() => setText("企业近三年的营业收入趋势如何？")}>
            <span className="chat-empty-card-tag">时序分析</span>
            <strong className="chat-empty-card-title">企业近三年的营业收入趋势如何？</strong>
            <small className="chat-empty-card-desc">生成年度对比与趋势图表，数据与口径双向对应</small>
          </button>
        </div>
      </div>}
      {turns.map((turn, index) => <article className="chat-turn" key={index}>
        <div className="chat-question"><small>你</small><p>{turn.question}</p></div>
        {turn.answer && <div className="chat-answer" ref={index === turns.length - 1 ? answerStart : undefined}><small>{turn.answer.kind === "explanation" ? "本体说明 · AI 解读，非数据查询结果" : turn.answer.textOrigin === "ENGINE" ? "引擎结果说明" : "AI 解读"}</small>{turn.answer.kind === "explanation" && <p className="evidence-note">以下解释基于本体定义；尚未核查实际记录、年份覆盖或来源可用性。以定义证据表中的口径为准。</p>}
          {turn.answer.confidence && <p className="chat-confidence" data-level={turn.answer.confidence.level}>置信度 {turn.answer.confidence.label}<small>{turn.answer.confidence.factors.map(item => item.detail).join("；")}</small></p>}
          <div className="chat-markdown"><Markdown remarkPlugins={[remarkGfm]} disallowedElements={["img"]}>{turn.answer.text}</Markdown></div>
          <Suspense fallback={<div className="result-loading" role="status">正在整理可视化结果…</div>}>
            <ResultPresentation presentation={turn.answer.presentation} />
          </Suspense>
          <div className="chat-audit-label"><span>核验与来源</span><small>展开查看口径、逐项计算与物理来源</small></div>
          <div className="chat-evidence">{turn.answer.evidence.map(item => <EvidenceCard key={item.id} evidence={item} />)}</div>
          {!!turn.answer.followUps?.length && <div className="chat-followups" aria-label="继续分析">{turn.answer.followUps.map(item => <button type="button" className="secondary" key={item.label} disabled={busy} onClick={() => void send(item.message)}>{item.label}</button>)}</div>}
          <small className="chat-version">语义版本 {turn.answer.releaseDigest.slice(0, 12)} · 数值与判断以引擎结果为准</small>
        </div>}
      </article>)}
      {pending && <form className="chat-choice" aria-label="业务选择" onSubmit={event => { event.preventDefault(); void submitChoice(); }}>
        <div className="chat-choice-header">
          <span className="chat-choice-badge">业务口径确认</span>
          <strong>{pending.question.prompt}</strong>
          <p className="chat-choice-reason">{pending.question.reason}</p>
        </div>
        {choiceControl(pending.question) === "SELECT" ? <>
          <label className="chat-choice-select"><span>请选择</span>
            <select aria-label={pending.question.prompt} value={picked} disabled={busy}
              onChange={event => {
                const value = event.target.value;
                if (!value) { setPicked(""); return; }
                const option = pending.question.options.find(item => item.id === value);
                if (option?.choice?.kind === "OTHER") { setPicked(value); return; }
                void submitChoice(value);
              }}>
              <option value="">请选择…</option>
              {pending.question.options.map(option => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
            </select>
          </label>
          {pending.question.options.find(item => item.id === picked)?.choice?.kind === "OTHER" ? <div className="chat-choice-other chat-choice-other-standalone">
            <label className="chat-choice-other-label" htmlFor="chat-choice-other-input">补充说明</label>
            <textarea id="chat-choice-other-input" aria-label="其他说明" value={otherText} maxLength={400} disabled={busy}
              placeholder="请补充业务条件或口径…" onChange={event => setOtherText(event.target.value)} />
            <div className="chat-choice-other-footer">
              <small>{otherText.length} / 400</small>
              <button className="primary" type="submit" disabled={busy || !otherText.trim()}>按补充说明继续</button>
            </div>
          </div> : null}
        </> : <div className="chat-choice-cards" role="radiogroup" aria-label={pending.question.prompt}>
        {pending.question.options.map(option => {
          const isOther = option.choice?.kind === "OTHER";
          const isSelected = picked === option.id;
          if (isOther) {
            return <div key={option.id} className={"chat-choice-option" + (isSelected ? " is-selected" : "")}>
              <button type="button" className="chat-choice-pick" aria-label={option.label} disabled={busy} onClick={() => setPicked(option.id)}>
                <span className="chat-choice-radio" aria-hidden="true" />
                <div className="chat-choice-text">
                  <strong>{option.label}</strong><small>{option.explanation}</small>
                </div>
              </button>
              {isSelected && <div className="chat-choice-other">
                <label className="chat-choice-other-label" htmlFor="chat-choice-other-input">补充说明</label>
                <textarea id="chat-choice-other-input" aria-label="其他说明" value={otherText} maxLength={400} disabled={busy}
                  placeholder="例如：只要 2024 年平均值，或指定某个特定口径…" onChange={event => setOtherText(event.target.value)} />
                <div className="chat-choice-other-footer">
                  <small>{otherText.length} / 400</small>
                  <button className="primary" type="submit" disabled={busy || !otherText.trim()}>按补充说明继续</button>
                </div>
              </div>}
            </div>;
          }
          return <button key={option.id} type="button" className={"chat-choice-option" + (isSelected ? " is-selected" : "")} aria-label={option.label} disabled={busy}
            onClick={() => void submitChoice(option.id)}>
            <span className="chat-choice-radio" aria-hidden="true" />
            <div className="chat-choice-text">
              <strong>{option.label}</strong><small>{option.explanation}</small>
            </div>
          </button>;
        })}
        </div>}
      </form>}
      {busy && <p className="chat-progress" role="status">{phase}…</p>}
      <div ref={bottom} />
    </div>
    {error && <p className="chat-error" role="alert">{error}</p>}
    {config && !config.ready && <p className="chat-error">{config.enabled ? messages.HARNESS_NOT_INSTALLED : messages.CHAT_NOT_CONFIGURED}</p>}
    <form className="chat-composer" onSubmit={event => { event.preventDefault(); void send(); }}>
      <textarea aria-label="业务问题" placeholder="输入业务问题，Enter 发送，Shift + Enter 换行" value={text} maxLength={4000} disabled={busy || !config?.ready}
        onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
      {busy ? <button type="button" className="secondary" onClick={() => abort.current?.abort()}>停止分析</button>
        : <button className="primary" type="submit" disabled={!text.trim() || !config?.ready}>
            <IconSend size={13} style={{ marginRight: 4, verticalAlign: "middle" }} />
            发送
          </button>}
    </form>
    <p className="chat-footnote">来源未复核、对象不唯一或数据缺失时，会明确说明；规则成立不代表其他业务判断。</p>
    {historyOpen && (
      <div className="chat-history-drawer-backdrop" onClick={() => setHistoryOpen(false)}>
        <aside className="chat-history-drawer" onClick={e => e.stopPropagation()} aria-label="历史会话列表">
          <div className="chat-history-drawer-head">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <IconHistory size={16} />
              <strong>历史会话</strong>
            </div>
            <button type="button" className="chat-history-close" onClick={() => setHistoryOpen(false)} aria-label="关闭历史会话">✕</button>
          </div>
          <div className="chat-history-drawer-body">
            {historyLoading ? (
              <p className="chat-history-empty">正在加载历史记录…</p>
            ) : historyList.length === 0 ? (
              <p className="chat-history-empty">暂无历史会话记录</p>
            ) : (
              <div className="chat-history-list">
                {historyList.map(item => {
                  const isActive = item.id === conversation;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={`chat-history-item${isActive ? " is-active" : ""}`}
                      onClick={() => void selectConversation(item.id)}
                    >
                      <div className="chat-history-item-main">
                        <span className="chat-history-item-title">{item.title || "未命名会话"}</span>
                        <div className="chat-history-item-meta">
                          <span>{item.turnCount} 轮问答</span>
                          <span>·</span>
                          <span>{formatHistoryTime(item.updatedAt)}</span>
                        </div>
                      </div>
                      {isActive && <span className="chat-history-active-badge">当前</span>}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </aside>
      </div>
    )}
  </section>;
}

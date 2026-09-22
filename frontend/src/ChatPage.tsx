import { lazy, Suspense, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiHeaders, checkedJson, errorDetail, type StudioSession } from "./api";

import { EvidenceCard, type Evidence } from "./EvidenceCard";
import { IconHistory, IconSend, IconSparkle } from "./icons";
import { useI18n, type Locale, type I18nKey, translate } from "./i18n";
const ResultPresentation = lazy(() => import("./ResultPresentation").then(module => ({ default: module.ResultPresentation })));
type FollowUp = { label: string; message: string };
type Answer = {
  textOrigin?: string; text: string; kind: string; releaseDigest: string; evidence: Evidence[];
  followUps?: FollowUp[]; presentation?: unknown;
};
type Turn = { question: string; answer?: Answer };
type ChoiceOption = { id: string; label: string; explanation: string; choice?: { kind: string; id: string } };
type ChoiceQuestion = { questionId: string; revision: number; slot: string; prompt: string; reason: string; control?: "CARDS" | "SELECT"; options: ChoiceOption[] };
type ConversationSummary = { id: string; releaseDigest: string; updatedAt: string; turnCount: number; title: string };

function formatHistoryTime(iso: string, locale: Locale): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const m = d.getMonth() + 1;
    const day = d.getDate();
    const h = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return translate(locale, "chat.timeFormat", { m, day, h, min });
  } catch {
    return iso.slice(0, 16);
  }
}

function choiceControl(question: ChoiceQuestion): "CARDS" | "SELECT" {
  if (question.control) return question.control;
  const kinds = new Set(question.options.map(item => item.choice?.kind).filter(kind => kind && kind !== "ABORT" && kind !== "OTHER"));
  return kinds.size > 0 && [...kinds].every(kind => ["DIMENSION_VALUE", "CLAIM", "SUBJECT"].includes(kind ?? "")) ? "SELECT" : "CARDS";
}

const errorCodeMap: Record<string, I18nKey> = {
  CHAT_NOT_CONFIGURED: "chat.error.notConfigured",
  HARNESS_NOT_INSTALLED: "chat.error.harnessNotInstalled",
  CHAT_HISTORY_SAVE_FAILED: "chat.error.historySaveFailed",
  CHAT_BUSY: "chat.error.busy",
  CHAT_TIMEOUT: "chat.error.timeout",
  MODEL_REQUEST_FAILED: "chat.error.modelFailed",
  ANSWER_NOT_VALIDATED: "chat.error.answerNotValidated",
  RELEASE_CHANGED_START_NEW_CHAT: "chat.error.releaseChanged",
  CONTEXT_LIMIT_START_NEW_CHAT: "chat.error.contextLimit",
  FORBIDDEN: "chat.error.forbidden",
  SESSION_EXPIRED: "chat.error.sessionExpired",
};

const toolNameMap: Record<string, I18nKey> = {
  list_semantics: "chat.tool.list_semantics",
  search_semantics: "chat.tool.search_semantics",
  describe_semantic: "chat.tool.describe_semantic",
  find_objects: "chat.tool.find_objects",
  semantic_query: "chat.tool.semantic_query",
  prepare_semantic_query: "chat.tool.prepare_semantic_query",
  evaluate_claim: "chat.tool.evaluate_claim",
  present_answer: "chat.tool.present_answer",
};

export function ChatPage({ session }: { session: StudioSession }) {
  const { locale, t } = useI18n();
  const getErrorMessage = (code: string) => {
    const key = errorCodeMap[code];
    return key ? t(key) : t("chat.error.unknown");
  };
  const getToolName = (name: string) => {
    const key = toolNameMap[name];
    return key ? t(key) : name;
  };
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
    }).catch(cause => { if (active) setError(getErrorMessage(errorDetail(cause))); });
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
      setError(getErrorMessage(errorDetail(cause)));
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
      setError(getErrorMessage(errorDetail(cause)));
    }
  }
  async function send(preset?: string, continuePending = false) {
    const question = (preset ?? text).trim();
    if (!question || (busy && !continuePending) || !config?.ready) return;
    const controller = new AbortController(); abort.current = controller;
    setText(""); setError(""); setBusy(true); setPhase(t("chat.understandingQuestion"));
    setTurns(previous => [...(continuePending && !previous.at(-1)?.answer ? previous.slice(0, -1) : previous), { question }]);
    let answered = false;
    try {
      const response = await fetch("/v0.1/chat/turns", {
        method: "POST", headers: apiHeaders(), signal: controller.signal,
        body: JSON.stringify({
          message: question,
          conversationId: conversation,
          locale,
        }),
      });
      if (!response.ok) await checkedJson(response);
      if (!response.body) throw new Error(t("chat.responseUnavailable"));
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
            setPhase(
              item.stage === "tool"
                ? (getToolName(item.name) || t("chat.readingBusinessInfo"))
                : item.outcome === "error"
                ? t("chat.correctingTool")
                : t("chat.preparingAnalysis")
            );
          } else if (item.type === "choice") {
            answered = true;
            setPending({ question: item.question, originalQuestion: item.originalQuestion ?? question });
            setPicked(""); setOtherText("");
          } else if (item.type === "answer") {
            answered = true;
            setTurns(previous => previous.map((t, index) => index === previous.length - 1 ? { ...t, answer: item.answer } : t));
          } else if (item.type === "error") throw new Error(getErrorMessage(item.code));
        }
      }
      if (!answered) throw new Error(t("chat.connectionEndedWithoutAnswer"));
    } catch (cause) {
      setError(controller.signal.aborted ? t("chat.analysisStopped") : getErrorMessage(errorDetail(cause)));
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
      if (result.status === "CONTINUE" && result.message) {
        setPending(null); setPicked(""); setOtherText("");
        await send(result.message, true);
        return;
      }
      if (result.status === "NEEDS_INPUT" && result.question) {
        setPending({ question: result.question, originalQuestion: pending.originalQuestion });
        setPicked(""); setOtherText("");
        return;
      }
      if (result.answerReady) {
        const answer = {
          kind: result.status === "UNSUPPORTED" ? "unsupported" : (result.kind ?? "answer"),
          textOrigin: result.textOrigin ?? "ENGINE",
          text: result.text ?? t("chat.calculatedByRelease"),
          releaseDigest: result.plan?.releaseDigest ?? result.releaseDigest ?? "",
          evidence: result.evidence ?? [{ id: "e1", tool: "prepare_semantic_query", result: result.population ?? result.result ?? result }],
          followUps: result.followUps ?? [], presentation: result.presentation,
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
        setError(result.errorMessage ?? (result.errorCode ? getErrorMessage(result.errorCode) : t("chat.cannotDetermine")));
      }
    } catch (cause) {
      setError(getErrorMessage(errorDetail(cause)));
    } finally { setBusy(false); }
  }

  return <section className="chat-page" aria-label={t("view.chat.title")}>
    <div className="chat-toolbar">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ display: "grid", placeItems: "center", width: 28, height: 28, borderRadius: 6, background: "var(--accent-subtle)", color: "var(--accent)" }}>
          <IconSparkle size={15} />
        </span>
        <div>
          <strong>{t("chat.title")}</strong>
          <small>{config?.model ?? t("chat.checking")} · {t("chat.modelSuffix")}</small>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="secondary" type="button" onClick={() => void openHistory()} disabled={busy}>
          <IconHistory size={14} style={{ marginRight: 4, verticalAlign: "middle" }} />
          {t("chat.history")}
        </button>
        <button className="secondary" onClick={fresh} disabled={busy}>{t("chat.new")}</button>
      </div>
    </div>
    <div className="chat-history" aria-live="polite">
      {!turns.length && !pending && <div className="chat-empty">
        <div className="chat-empty-badge">
          <IconSparkle size={13} />
          <span>{t("chat.empty.eyebrow")}</span>
        </div>
        <h2>{t("chat.empty.title")}</h2>
        <p className="chat-empty-sub">{t("chat.empty.description")}</p>
        <div className="chat-empty-grid">
          <button type="button" className="chat-empty-card" onClick={() => setText(t("chat.suggestion.objects.question"))}>
            <span className="chat-empty-card-tag">{t("chat.suggestion.objects.tag")}</span>
            <strong className="chat-empty-card-title">{t("chat.suggestion.objects.question")}</strong>
            <small className="chat-empty-card-desc">{t("chat.suggestion.objects.description")}</small>
          </button>
          <button type="button" className="chat-empty-card" onClick={() => setText(t("chat.suggestion.rules.question"))}>
            <span className="chat-empty-card-tag">{t("chat.suggestion.rules.tag")}</span>
            <strong className="chat-empty-card-title">{t("chat.suggestion.rules.question")}</strong>
            <small className="chat-empty-card-desc">{t("chat.suggestion.rules.description")}</small>
          </button>
          <button type="button" className="chat-empty-card" onClick={() => setText(t("chat.suggestion.metrics.question"))}>
            <span className="chat-empty-card-tag">{t("chat.suggestion.metrics.tag")}</span>
            <strong className="chat-empty-card-title">{t("chat.suggestion.metrics.question")}</strong>
            <small className="chat-empty-card-desc">{t("chat.suggestion.metrics.description")}</small>
          </button>
          <button type="button" className="chat-empty-card" onClick={() => setText(t("chat.suggestion.time.question"))}>
            <span className="chat-empty-card-tag">{t("chat.suggestion.time.tag")}</span>
            <strong className="chat-empty-card-title">{t("chat.suggestion.time.question")}</strong>
            <small className="chat-empty-card-desc">{t("chat.suggestion.time.description")}</small>
          </button>
        </div>
      </div>}
      {turns.map((turn, index) => <article className="chat-turn" key={index}>
        <div className="chat-question"><small>{t("chat.you")}</small><p>{turn.question}</p></div>
        {turn.answer && <div className="chat-answer" ref={index === turns.length - 1 ? answerStart : undefined}><small>{turn.answer.kind === "explanation" ? t("chat.answer.definition") : turn.answer.textOrigin === "ENGINE" ? t("chat.answer.engine") : t("chat.answer.ai")}</small>{turn.answer.kind === "explanation" && <p className="evidence-note">{t("chat.definitionNotice")}</p>}
          <div className="chat-markdown"><Markdown remarkPlugins={[remarkGfm]} disallowedElements={["img"]}>{turn.answer.text}</Markdown></div>
          <Suspense fallback={<div className="result-loading" role="status">{t("chat.visualizing")}</div>}>
            <ResultPresentation presentation={turn.answer.presentation} />
          </Suspense>
          <div className="chat-audit-label"><span>{t("chat.audit.title")}</span><small>{t("chat.audit.description")}</small></div>
          <div className="chat-evidence">{turn.answer.evidence.map(item => <EvidenceCard key={item.id} evidence={item} />)}</div>
          {!!turn.answer.followUps?.length && <div className="chat-followups" aria-label={t("chat.followUps")}>{turn.answer.followUps.map(item => <button type="button" className="secondary" key={item.label} disabled={busy} onClick={() => void send(item.message)}>{item.label}</button>)}</div>}
          <small className="chat-version">{t("chat.version", { digest: turn.answer.releaseDigest.slice(0, 12) })}</small>
        </div>}
      </article>)}
      {pending && <form className="chat-choice" aria-label={t("chat.choiceAria")} onSubmit={event => { event.preventDefault(); void submitChoice(); }}>
        <div className="chat-choice-header">
          <span className="chat-choice-badge">{t("chat.choice.badge")}</span>
          <strong>{pending.question.prompt}</strong>
          <p className="chat-choice-reason">{pending.question.reason}</p>
        </div>
        {choiceControl(pending.question) === "SELECT" ? <>
          <label className="chat-choice-select"><span>{t("chat.choice.select")}</span>
            <select aria-label={pending.question.prompt} value={picked} disabled={busy}
              onChange={event => {
                const value = event.target.value;
                if (!value) { setPicked(""); return; }
                const option = pending.question.options.find(item => item.id === value);
                if (option?.choice?.kind === "OTHER") { setPicked(value); return; }
                void submitChoice(value);
              }}>
              <option value="">{t("common.select")}…</option>
              {pending.question.options.map(option => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
            </select>
          </label>
          {pending.question.options.find(item => item.id === picked)?.choice?.kind === "OTHER" ? <div className="chat-choice-other chat-choice-other-standalone">
            <label className="chat-choice-other-label" htmlFor="chat-choice-other-input">{t("chat.choice.other")}</label>
            <textarea id="chat-choice-other-input" aria-label={t("chat.choice.other")} value={otherText} maxLength={400} disabled={busy}
              placeholder={t("chat.choice.otherPlaceholder")} onChange={event => setOtherText(event.target.value)} />
            <div className="chat-choice-other-footer">
              <small>{otherText.length} / 400</small>
              <button className="primary" type="submit" disabled={busy || !otherText.trim()}>{t("chat.choice.continue")}</button>
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
                <label className="chat-choice-other-label" htmlFor="chat-choice-other-input">{t("chat.choice.other")}</label>
                <textarea id="chat-choice-other-input" aria-label={t("chat.choice.other")} value={otherText} maxLength={400} disabled={busy}
                  placeholder={t("chat.choice.otherPlaceholder")} onChange={event => setOtherText(event.target.value)} />
                <div className="chat-choice-other-footer">
                  <small>{otherText.length} / 400</small>
                  <button className="primary" type="submit" disabled={busy || !otherText.trim()}>{t("chat.choice.continue")}</button>
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
    {config && !config.ready && <p className="chat-error">{config.enabled ? t("chat.error.harnessNotInstalled") : t("chat.error.notConfigured")}</p>}
    <form className="chat-composer" onSubmit={event => { event.preventDefault(); void send(); }}>
      <textarea aria-label={t("chat.question")} placeholder={t("chat.placeholder")} value={text} maxLength={4000} disabled={busy || !config?.ready}
        onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
      {busy ? <button type="button" className="secondary" onClick={() => abort.current?.abort()}>{t("chat.stop")}</button>
        : <button className="primary" type="submit" disabled={!text.trim() || !config?.ready}>
            <IconSend size={13} style={{ marginRight: 4, verticalAlign: "middle" }} />
            {t("chat.send")}
          </button>}
    </form>
    <p className="chat-footnote">{t("chat.footnote")}</p>
    {historyOpen && (
      <div className="chat-history-drawer-backdrop" onClick={() => setHistoryOpen(false)}>
        <aside className="chat-history-drawer" onClick={e => e.stopPropagation()} aria-label={t("chat.history.list")}>
          <div className="chat-history-drawer-head">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <IconHistory size={16} />
              <strong>{t("chat.history")}</strong>
            </div>
            <button type="button" className="chat-history-close" onClick={() => setHistoryOpen(false)} aria-label={t("common.close")}>✕</button>
          </div>
          <div className="chat-history-drawer-body">
            {historyLoading ? (
              <p className="chat-history-empty">{t("chat.history.loading")}</p>
            ) : historyList.length === 0 ? (
              <p className="chat-history-empty">{t("chat.history.empty")}</p>
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
                        <span className="chat-history-item-title">{item.title || t("chat.history.untitled")}</span>
                        <div className="chat-history-item-meta">
                          <span>{t("chat.history.turns", { count: item.turnCount })}</span>
                          <span>·</span>
                          <span>{formatHistoryTime(item.updatedAt, locale)}</span>
                        </div>
                      </div>
                      {isActive && <span className="chat-history-active-badge">{t("common.current")}</span>}
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

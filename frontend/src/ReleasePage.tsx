import { useEffect, useMemo, useState } from "react";

import { ApiError, apiHeaders, checkedJson, errorDetail, hasRole } from "./api";
import type { StudioSession } from "./api";
import {
  digestHelp,
  gateErrorMessage,
  publishStatusLabel,
  validationStatusLabel,
} from "./labels";
import type { DraftReview, DraftRevisionRecord, ReleaseState } from "./types";

type BoundResult = {
  draftRevision: number;
  candidateDigest: string;
  sourceGeneration: number;
  status: string;
};

type Props = {
  ready: boolean;
  session: StudioSession | null;
  draftRevision: number;
  candidateDigest: string | null;
  sourceGeneration: number;
  onError: (message: string | null) => void;
  onPublished: () => void;
};

export function ReleasePage({
  ready,
  session,
  draftRevision,
  candidateDigest,
  sourceGeneration,
  onError,
  onPublished,
}: Props) {
  const [review, setReview] = useState<DraftReview | null>(null);
  const [release, setRelease] = useState<ReleaseState | null>(null);
  const [author, setAuthor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState<BoundResult | null>(null);
  const [approval, setApproval] = useState<BoundResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sourceDetails, setSourceDetails] = useState<Record<string, { revision: number | null; status: string }> | null>(null);
  const [forbiddenReview, setForbiddenReview] = useState(false);

  const canValidate = hasRole(session, "modeler");
  const canApprove = hasRole(session, "reviewer");
  const canPublish = hasRole(session, "publisher");
  const canCheckSources = hasRole(session, "source-admin");
  const canSeeReview = canValidate || canApprove || canPublish;

  async function load() {
    if (!ready) return;
    setForbiddenReview(false);
    try {
      const releasePayload = (await fetch("/v0.1/studio/releases").then(checkedJson)) as ReleaseState;
      setRelease(releasePayload);
      if (canSeeReview) {
        const reviewPayload = (await fetch("/v0.1/studio/drafts/default/review").then(checkedJson)) as DraftReview;
        setReview(reviewPayload);
        try {
          const historyPayload = await fetch("/v0.1/studio/drafts/default/history").then(checkedJson);
          const revisions = (historyPayload.revisions ?? []) as DraftRevisionRecord[];
          setAuthor(revisions[0]?.author ?? null);
        } catch (cause) {
          if (!(cause instanceof ApiError) || cause.status !== 403) throw cause;
          setAuthor(null);
        }
      } else {
        setReview(null);
        setAuthor(null);
        setForbiddenReview(true);
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403 && !canSeeReview) {
        setForbiddenReview(true);
        return;
      }
      onError(gateErrorMessage(errorDetail(cause), cause instanceof ApiError ? cause.status : undefined));
    }
  }

  useEffect(() => {
    void load();
  }, [ready, session?.subject, draftRevision, sourceGeneration]);

  const boundRevision = review?.revision ?? draftRevision;
  const boundDigest = review?.candidateDigest ?? candidateDigest;
  const validationState = bindStatus(validation, boundRevision, boundDigest, sourceGeneration);
  const approvalState = bindStatus(approval, boundRevision, boundDigest, sourceGeneration);
  const active = release?.activeDigest ?? null;
  const candidateMatchesActive = Boolean(boundDigest && active && boundDigest === active);
  const publishState = candidateMatchesActive
    ? "active"
    : approvalState === "VALID"
      ? "approved"
      : validationState === "VALID"
        ? "review"
        : "draft";

  const primary = useMemo(() => {
    if (!session) return canValidate ? { label: "校验候选", action: "validate" as const } : null;
    if (canValidate && !canApprove && !canPublish) return { label: "校验候选", action: "validate" as const };
    if (canApprove && !canValidate && !canPublish) return { label: "批准候选", action: "approve" as const };
    if (canPublish && !canValidate && !canApprove) return { label: "发布到当前环境", action: "publish" as const };
    if (canValidate && validationState !== "VALID") return { label: "校验候选", action: "validate" as const };
    if (canApprove && approvalState !== "VALID") return { label: "批准候选", action: "approve" as const };
    if (canPublish) return { label: "发布到当前环境", action: "publish" as const };
    if (canValidate) return { label: "校验候选", action: "validate" as const };
    return null;
  }, [session, canValidate, canApprove, canPublish, validationState, approvalState]);

  async function run(action: "validate" | "approve" | "publish" | "sources") {
    setBusy(true);
    onError(null);
    setNotice(null);
    try {
      if (action === "sources") {
        await fetch("/v0.1/studio/source-profiles/validate-all", { method: "POST", headers: apiHeaders() }).then(checkedJson);
        setNotice("来源检查已完成。这只更新来源状态，不是模型发布。请再次校验候选。");
        return;
      }
      if (action === "validate") {
        const result = await fetch("/v0.1/studio/drafts/default/validate", {
          method: "POST",
          headers: apiHeaders(),
        }).then(checkedJson);
        const next: BoundResult = {
          draftRevision: Number(result.draftRevision),
          candidateDigest: String(result.candidateDigest),
          sourceGeneration,
          status: String(result.status),
        };
        setValidation(next);
        setApproval(null);
        setSourceDetails(result.details?.sources ?? null);
        if (result.status === "VALID") {
          setNotice(`校验通过，已绑定草稿 revision ${next.draftRevision} 与 candidateDigest。这不是发布。`);
        } else {
          setNotice("校验未通过：所需来源尚未全部为 VALID。可检查来源后重新校验。草稿仍未发布。");
        }
        return;
      }
      if (action === "approve") {
        const result = await fetch("/v0.1/studio/drafts/default/approve", {
          method: "POST",
          headers: apiHeaders(),
        }).then(checkedJson);
        setApproval({
          draftRevision: Number(result.draftRevision),
          candidateDigest: String(result.candidateDigest),
          sourceGeneration,
          status: String(result.status),
        });
        setNotice(`已独立批准 revision ${result.draftRevision}。尚未激活环境，公共查询仍使用当前 activeDigest。`);
        return;
      }
      if (!release) return;
      const result = await fetch("/v0.1/studio/drafts/default/publish", {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({ expectedEnvironmentRevision: release.environmentRevision }),
      }).then(checkedJson);
      await load();
      setNotice(`已激活 ${result.digest}。这是版本生效；草稿保存不会显示这个状态。`);
      onPublished();
    } catch (cause) {
      const status = cause instanceof ApiError ? cause.status : undefined;
      const detail = errorDetail(cause);
      onError(gateErrorMessage(detail, status));
      if (detail === "INDEPENDENT_REVIEW_REQUIRED" || detail === "VALIDATION_REQUIRED" || detail === "APPROVAL_REQUIRED") {
        setNotice(gateErrorMessage(detail, status));
      }
    } finally {
      setBusy(false);
    }
  }

  if (!ready || !release) return <div className="panel-loading">正在读取候选发布…</div>;

  const changeCount = review
    ? review.changes.added.length + review.changes.changed.length + review.changes.removed.length
    : 0;
  const isAuthor = Boolean(author && session?.subject && author === session.subject);

  return (
    <div className="release-panel">
      <section className="release-candidate">
        <div className="candidate-head">
          <div>
            <p className="eyebrow">CANDIDATE</p>
            <h2>草稿 r{boundRevision}</h2>
            <code aria-label="candidateDigest">{boundDigest ?? "尚未读取候选摘要"}</code>
          </div>
          {primary ? (
            <button className="primary" disabled={busy} onClick={() => void run(primary.action)}>
              {primary.label}
            </button>
          ) : (
            <span className="validation-badge">只读，无管理操作</span>
          )}
        </div>
        <ul className="status-lanes" aria-label="草稿与发布状态">
          <li>编辑：{publishState === "active" && changeCount === 0 ? "草稿与生效版本相同" : "草稿"}</li>
          <li>验证：{validationStatusLabel(validationState)}</li>
          <li>发布：{publishStatusLabel(publishState)}</li>
        </ul>
        <div className="digest-grid">
          <div>
            <span>草稿 revision</span>
            <strong>{boundRevision}</strong>
          </div>
          <div>
            <span>candidateDigest</span>
            <code>{boundDigest ?? "—"}</code>
          </div>
          <div>
            <span>当前 activeDigest</span>
            <code aria-label="activeDigest">{active ?? "尚未激活"}</code>
          </div>
          <div>
            <span>环境</span>
            <strong>{release.environment} · r{release.environmentRevision}</strong>
          </div>
        </div>
        <p className="release-explain">{digestHelp()}</p>
        {author ? <p className="release-explain">当前草稿作者：<code>{author}</code>{isAuthor ? "（你是作者，不能自批）" : ""}</p> : null}
        {forbiddenReview ? <p className="release-explain">当前身份不能读取候选差异，只能查看已激活版本。</p> : null}
        {notice ? <p className="notice" role="status">{notice}</p> : null}
        {sourceDetails && validationState === "INVALID" ? (
          <ul className="impact-list">
            {Object.entries(sourceDetails).map(([sourceId, item]) => (
              <li key={sourceId}>{sourceId}：{item.status}{item.revision != null ? ` · 来源 r${item.revision}` : ""}</li>
            ))}
          </ul>
        ) : null}
        {canCheckSources && validationState === "INVALID" ? (
          <button className="secondary" disabled={busy} onClick={() => void run("sources")}>检查来源连接</button>
        ) : null}
        {review ? (
          <div className="change-summary">
            <strong>{changeCount} 项相对基础模型的变更</strong>
            <ChangeGroup label="新增" items={review.changes.added} />
            <ChangeGroup label="修改" items={review.changes.changed} />
            <ChangeGroup label="删除" items={review.changes.removed} />
          </div>
        ) : null}
      </section>
      <section className="release-history">
        <div className="history-head">
          <h2>当前版本与历史</h2>
          <span>{release.environment} · r{release.environmentRevision}</span>
        </div>
        {release.releases.length ? (
          <ul>
            {release.releases.map((item) => (
              <li key={`${item.digest}:${item.environmentRevision}:${item.publicationId}`}>
                <code>{item.digest}</code>
                <span>环境 r{item.environmentRevision}</span>
                <span>{item.publisher}</span>
                <time dateTime={item.createdAt}>{item.createdAt}</time>
              </li>
            ))}
          </ul>
        ) : (
          <p>当前租户尚无 Studio 发布记录。未激活时公共查询可能使用启动模型 fallback，那不是本页的已发布状态。</p>
        )}
      </section>
    </div>
  );
}

function bindStatus(
  bound: BoundResult | null,
  revision: number,
  digest: string | null,
  sourceGeneration: number,
): "none" | "VALID" | "INVALID" | "stale" {
  if (!bound || !digest) return "none";
  if (bound.draftRevision !== revision || bound.candidateDigest !== digest || bound.sourceGeneration !== sourceGeneration) {
    return "stale";
  }
  if (bound.status === "VALID" || bound.status === "APPROVED") return "VALID";
  return "INVALID";
}

function ChangeGroup({ label, items }: { label: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <span>{label}</span>
      {items.map((item) => (
        <code key={item}>{item}</code>
      ))}
    </div>
  );
}

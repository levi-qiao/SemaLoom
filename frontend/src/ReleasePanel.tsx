import { useEffect, useState } from "react";

import { apiHeaders, checkedJson } from "./api";

type Review = {
  revision: number;
  candidateDigest: string;
  changes: { added: string[]; changed: string[]; removed: string[] };
};
type ReleaseState = {
  environment: string;
  activeDigest: string | null;
  environmentRevision: number;
  releases: { digest: string; publisher: string; createdAt: string; environmentRevision: number }[];
};

export function ReleasePanel({ ready, onError }: { ready: boolean; onError: (message: string | null) => void }) {
  const [review, setReview] = useState<Review | null>(null);
  const [release, setRelease] = useState<ReleaseState | null>(null);
  const [stage, setStage] = useState<"review" | "validated" | "approved">("review");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready) void load();
  }, [ready]);

  async function load() {
    try {
      const [reviewPayload, releasePayload] = await Promise.all([
        fetch("/v0.1/studio/drafts/default/review").then(checkedJson),
        fetch("/v0.1/studio/releases").then(checkedJson),
      ]);
      setReview(reviewPayload);
      setRelease(releasePayload);
      setStage("review");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    }
  }

  async function advance() {
    if (!review || !release) return;
    setBusy(true);
    onError(null);
    try {
      if (stage === "review") {
        const result = await fetch("/v0.1/studio/drafts/default/validate", {
          method: "POST", headers: apiHeaders(),
        }).then(checkedJson);
        if (result.status !== "VALID") throw new Error("来源尚未全部通过联机验证");
        setStage("validated");
      } else if (stage === "validated") {
        await fetch("/v0.1/studio/drafts/default/approve", {
          method: "POST", headers: apiHeaders(),
        }).then(checkedJson);
        setStage("approved");
      } else {
        await fetch("/v0.1/studio/drafts/default/publish", {
          method: "POST",
          headers: apiHeaders(),
          body: JSON.stringify({ expectedEnvironmentRevision: release.environmentRevision }),
        }).then(checkedJson);
        await load();
      }
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    } finally {
      setBusy(false);
    }
  }

  if (!review || !release) return <div className="panel-loading">正在读取候选发布…</div>;
  const changeCount = review.changes.added.length + review.changes.changed.length + review.changes.removed.length;
  const action = stage === "review" ? "校验候选" : stage === "validated" ? "批准候选" : "发布到当前环境";
  return (
    <div className="release-panel">
      <section className="release-candidate">
        <div className="candidate-head">
          <div><p className="eyebrow">CANDIDATE</p><h2>草稿 r{review.revision}</h2><code>{review.candidateDigest}</code></div>
          <button className="primary" disabled={busy} onClick={() => void advance()}>{action}</button>
        </div>
        <ol className="release-steps">
          <li data-active={stage === "review"}>1 校验</li>
          <li data-active={stage === "validated"}>2 批准</li>
          <li data-active={stage === "approved"}>3 发布</li>
        </ol>
        <div className="change-summary">
          <strong>{changeCount} 项变更</strong>
          <ChangeGroup label="新增" items={review.changes.added} />
          <ChangeGroup label="修改" items={review.changes.changed} />
          <ChangeGroup label="删除" items={review.changes.removed} />
        </div>
      </section>
      <section className="release-history">
        <div className="history-head"><h2>发布历史</h2><span>{release.environment} · r{release.environmentRevision}</span></div>
        {release.releases.length ? <ul>{release.releases.map((item) => <li key={`${item.digest}:${item.environmentRevision}`}><code>{item.digest.slice(0, 12)}</code><span>环境 r{item.environmentRevision}</span><span>{item.publisher}</span><time>{new Date(item.createdAt).toLocaleString()}</time></li>)}</ul> : <p>当前租户尚无 Studio 发布记录。</p>}
      </section>
    </div>
  );
}

function ChangeGroup({ label, items }: { label: string; items: string[] }) {
  return items.length ? <div><span>{label}</span>{items.map((item) => <code key={item}>{item}</code>)}</div> : null;
}

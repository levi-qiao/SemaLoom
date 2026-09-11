import { useEffect, useState } from "react";

import { apiHeaders, checkedJson } from "./api";

type Profile = {
  sourceId: string;
  revision: number;
  label: string;
  provider: string;
  bindingRef: string;
  secretRef: string | null;
  settings: Record<string, unknown>;
  validationStatus: string;
};

export function SourceManager({ ready, onError }: { ready: boolean; onError: (message: string | null) => void }) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newSourceId, setNewSourceId] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready) void load();
  }, [ready]);

  async function load() {
    try {
      const payload = await fetch("/v0.1/studio/source-profiles").then(checkedJson);
      setProfiles(payload.profiles ?? []);
      setSelectedId((current) => current ?? payload.profiles?.[0]?.sourceId ?? null);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    }
  }

  async function validateAll() {
    setBusy(true);
    onError(null);
    try {
      const payload = await fetch("/v0.1/studio/source-profiles/validate-all", {
        method: "POST",
        headers: apiHeaders(),
      }).then(checkedJson);
      setProfiles(payload.profiles ?? []);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    } finally {
      setBusy(false);
    }
  }

  async function save(profile: Profile) {
    setBusy(true);
    onError(null);
    try {
      const saved = await fetch(
        `/v0.1/studio/source-profiles/${encodeURIComponent(profile.sourceId)}`,
        {
          method: "PUT",
          headers: apiHeaders(),
          body: JSON.stringify({
            expectedRevision: profile.revision,
            label: profile.label,
            provider: profile.provider,
            bindingRef: profile.bindingRef,
            secretRef: profile.secretRef || null,
            settings: profile.settings,
          }),
        },
      ).then(checkedJson);
      setProfiles((items) => items.map((item) => item.sourceId === saved.sourceId ? saved : item));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    } finally {
      setBusy(false);
    }
  }

  async function createSource() {
    const sourceId = newSourceId.trim();
    if (!sourceId) return;
    setBusy(true);
    onError(null);
    try {
      const created = await fetch(
        `/v0.1/studio/source-profiles/${encodeURIComponent(sourceId)}`,
        {
          method: "PUT",
          headers: apiHeaders(),
          body: JSON.stringify({
            expectedRevision: 0,
            label: sourceId,
            provider: "postgres",
            bindingRef: `env:${sourceId.toUpperCase().replaceAll("-", "_")}_URL`,
            secretRef: null,
            settings: {},
          }),
        },
      ).then(checkedJson);
      setProfiles((items) =>
        [...items, created].sort((left, right) => left.sourceId.localeCompare(right.sourceId)),
      );
      setSelectedId(created.sourceId);
      setNewSourceId("");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    } finally {
      setBusy(false);
    }
  }

  const selected = profiles.find((item) => item.sourceId === selectedId);
  function update(patch: Partial<Profile>) {
    setProfiles((items) =>
      items.map((item) => item.sourceId === selectedId ? { ...item, ...patch } : item),
    );
  }

  return (
    <div className="source-manager">
      <div className="manager-toolbar">
        <div><strong>环境绑定</strong><small>连接值由进程环境解析；浏览器只管理引用。</small></div>
        <div className="manager-actions">
          <span className="source-create"><input aria-label="新来源 ID" value={newSourceId} placeholder="新来源 ID" onChange={(event) => setNewSourceId(event.target.value)} /><button className="secondary" disabled={busy || !newSourceId.trim()} onClick={() => void createSource()}>注册来源</button></span>
          <button className="primary" disabled={busy} onClick={() => void validateAll()}>验证全部来源</button>
        </div>
      </div>
      <div className="manager-body">
        <ul className="profile-list">
          {profiles.map((profile) => (
            <li key={profile.sourceId}>
              <button
                className={profile.sourceId === selectedId ? "active" : ""}
                onClick={() => setSelectedId(profile.sourceId)}
              >
                <span>{profile.label}</span>
                <small>{profile.provider} · {statusLabel(profile.validationStatus)}</small>
              </button>
            </li>
          ))}
        </ul>
        {selected ? (
          <div className="profile-form">
            <div className="profile-heading">
              <div><span>来源配置</span><code>{selected.sourceId}</code></div>
              <span className={`validation-badge ${selected.validationStatus.toLowerCase()}`}>
                {statusLabel(selected.validationStatus)}
              </span>
            </div>
            <div className="form-grid">
              <Field label="显示名称"><input value={selected.label} onChange={(event) => update({ label: event.target.value })} /></Field>
              <Field label="协议"><select value={selected.provider} onChange={(event) => update({ provider: event.target.value })}><option value="postgres">PostgreSQL</option><option value="openapi">OpenAPI</option></select></Field>
              <Field label="环境绑定引用"><input value={selected.bindingRef} onChange={(event) => update({ bindingRef: event.target.value })} /></Field>
              <Field label="Secret 引用"><input value={selected.secretRef ?? ""} placeholder="可选，例如 vault:erp/read" onChange={(event) => update({ secretRef: event.target.value || null })} /></Field>
            </div>
            {selected.provider === "openapi" ? <Field label="健康检查路径"><input value={String(selected.settings.healthPath ?? "/health")} onChange={(event) => update({ settings: { ...selected.settings, healthPath: event.target.value } })} /></Field> : null}
            <button className="secondary save-profile" disabled={busy} onClick={() => void save(selected)}>保存来源配置</button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="form-field"><span>{label}</span>{children}</label>;
}

function statusLabel(status: string) {
  if (status === "VALID") return "可用";
  if (status === "INVALID") return "配置无效";
  if (status === "UNAVAILABLE") return "不可连接";
  return "待验证";
}

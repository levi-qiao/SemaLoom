import { useEffect, useRef, useState } from "react";

import { apiHeaders, checkedJson } from "./api";
import { sameJson } from "./doc";
import { validationNotice } from "./labels";
import { Window } from "./StudioDialog";
import { useI18n, type I18nKey } from "./i18n";
import type { Mapping, Source, SourceResource } from "./types";

type Profile = {
  sourceId: string;
  revision: number;
  label: string;
  provider: string;
  bindingRef: string;
  secretRef: string | null;
  settings: Record<string, unknown>;
  validationStatus: string;
  reason?: string | null;
};

type Props = {
  ready: boolean;
  catalog: Source[];
  mappings: Mapping[];
  search: string;
  selectedId: string | null;
  onSelect: (sourceId: string) => void;
  onError: (message: string | null) => void;
  onDirtyChange: (dirty: boolean) => void;
  onSaved?: () => void;
};

export function SourcePage({
  ready,
  catalog,
  mappings,
  search,
  selectedId,
  onSelect,
  onError,
  onDirtyChange,
  onSaved,
}: Props) {
  const { t } = useI18n();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [baseline, setBaseline] = useState<Profile[]>([]);
  const [newSourceId, setNewSourceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [conflict, setConflict] = useState(false);
  const editGen = useRef(0);

  function setDraft(next: Profile[] | ((current: Profile[]) => Profile[])) {
    setProfiles((current) => {
      const resolved = typeof next === "function" ? next(current) : next;
      editGen.current += 1;
      return resolved;
    });
  }

  async function load() {
    try {
      const payload = await fetch("/v0.1/studio/source-profiles").then(checkedJson);
      const next = (payload.profiles ?? []) as Profile[];
      setProfiles(next);
      setBaseline(next);
      setConflict(false);
      editGen.current += 1;
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    }
  }

  useEffect(() => {
    if (ready) void load();
  }, [ready]);

  const dirty = profiles.some((profile) => {
    const saved = baseline.find((item) => item.sourceId === profile.sourceId);
    if (!saved) return true;
    return !sameJson(editFields(profile), editFields(saved));
  });

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  const cards = profiles
    .filter((profile) => `${profile.label} ${profile.sourceId} ${profile.provider}`.toLowerCase().includes(search.toLowerCase()))
    .sort((left, right) => {
      const leftCount = catalog.find((item) => item.sourceId === left.sourceId)?.mappingCount ?? 0;
      const rightCount = catalog.find((item) => item.sourceId === right.sourceId)?.mappingCount ?? 0;
      return rightCount - leftCount;
    });
  const selected = profiles.find((item) => item.sourceId === selectedId) ?? null;
  const catalogItem = catalog.find((item) => item.sourceId === selectedId);
  const selectedDirty = Boolean(selected && !sameJson(editFields(selected), editFields(baseline.find((item) => item.sourceId === selected.sourceId) ?? selected)));

  async function save(profile: Profile, expectedRevision = profile.revision) {
    const gen = editGen.current;
    setBusy(true);
    onError(null);
    try {
      const saved = await fetch(`/v0.1/studio/source-profiles/${encodeURIComponent(profile.sourceId)}`, {
        method: "PUT",
        headers: apiHeaders(),
        body: JSON.stringify({
          expectedRevision,
          label: profile.label,
          provider: profile.provider,
          bindingRef: profile.bindingRef,
          secretRef: profile.secretRef || null,
          settings: profile.settings,
        }),
      }).then(checkedJson) as Profile;
      if (editGen.current !== gen) {
        setBaseline((items) => upsert(items, { ...saved, reason: null }));
        setConflict(false);
        onSaved?.();
        return;
      }
      setProfiles((items) => items.map((item) => (item.sourceId === saved.sourceId ? { ...saved, reason: null } : item)));
      setBaseline((items) => upsert(items, { ...saved, reason: null }));
      setConflict(false);
      onSaved?.();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "UNKNOWN_ERROR";
      if (message.includes("409") || message.includes("REVISION_CONFLICT")) {
        setConflict(true);
        onError(t("source.conflictError"));
      } else {
        onError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function retrySave(profile: Profile) {
    try {
      const payload = await fetch("/v0.1/studio/source-profiles").then(checkedJson);
      const remote = ((payload.profiles ?? []) as Profile[]).find((item) => item.sourceId === profile.sourceId);
      await save(profile, remote?.revision ?? profile.revision);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    }
  }

  async function createSource() {
    const sourceId = newSourceId.trim();
    if (!sourceId) return;
    setBusy(true);
    onError(null);
    try {
      const created = await fetch(`/v0.1/studio/source-profiles/${encodeURIComponent(sourceId)}`, {
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
      }).then(checkedJson) as Profile;
      setProfiles((items) => [...items, created].sort((left, right) => left.sourceId.localeCompare(right.sourceId)));
      setBaseline((items) => [...items, created].sort((left, right) => left.sourceId.localeCompare(right.sourceId)));
      setNewSourceId("");
      onSelect(created.sourceId);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    } finally {
      setBusy(false);
    }
  }

  function mergeValidation(current: Profile[], incoming: Profile[]) {
    return current.map((item) => {
      const saved = incoming.find((entry) => entry.sourceId === item.sourceId);
      if (!saved) return item;
      const localDirty = !sameJson(editFields(item), editFields(baseline.find((entry) => entry.sourceId === item.sourceId) ?? item));
      if (localDirty) {
        return {
          ...item,
          validationStatus: saved.validationStatus,
          reason: saved.reason,
          revision: saved.revision,
        };
      }
      return { ...saved, reason: saved.reason };
    });
  }

  async function validateAll() {
    setBusy(true);
    onError(null);
    try {
      const payload = await fetch("/v0.1/studio/source-profiles/validate-all", {
        method: "POST",
        headers: apiHeaders(),
      }).then(checkedJson);
      const incoming = (payload.profiles ?? []) as Profile[];
      setProfiles((current) => mergeValidation(current, incoming));
      setBaseline((current) => current.map((item) => {
        const saved = incoming.find((entry) => entry.sourceId === item.sourceId);
        return saved ? { ...item, validationStatus: saved.validationStatus, revision: saved.revision, reason: saved.reason } : item;
      }));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    } finally {
      setBusy(false);
    }
  }

  async function validate(sourceId: string) {
    const gen = editGen.current;
    setBusy(true);
    onError(null);
    try {
      const saved = await fetch(`/v0.1/studio/source-profiles/${encodeURIComponent(sourceId)}/validate`, {
        method: "POST",
        headers: apiHeaders(),
      }).then(checkedJson) as Profile;
      setProfiles((items) => {
        if (editGen.current !== gen) {
          return items.map((item) => item.sourceId === saved.sourceId
            ? { ...item, validationStatus: saved.validationStatus, reason: saved.reason, revision: saved.revision }
            : item);
        }
        return mergeValidation(items, [saved]);
      });
      setBaseline((items) => items.map((item) => item.sourceId === saved.sourceId
        ? { ...item, validationStatus: saved.validationStatus, revision: saved.revision, reason: saved.reason }
        : item));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    } finally {
      setBusy(false);
    }
  }

  function update(patch: Partial<Profile>) {
    setDraft((items) => items.map((item) => (item.sourceId === selectedId ? { ...item, ...patch } : item)));
  }

  return (
    <>
      <div className="content-pane">
        <div className="source-toolbar">
          <span className="source-create">
            <input aria-label={t("source.newSourceId")} value={newSourceId} placeholder={t("source.newSourceId")} onChange={(event) => setNewSourceId(event.target.value)} />
            <button className="secondary" disabled={busy || !newSourceId.trim()} onClick={() => void createSource()}>{t("source.add")}</button>
          </span>
          <button className="secondary" disabled={busy} onClick={() => void validateAll()}>{t("source.validateAll")}</button>
        </div>
        <div className="source-grid">
          {cards.map((profile) => {
            const stats = catalog.find((item) => item.sourceId === profile.sourceId);
            return (
              <article
                key={profile.sourceId}
                className={profile.sourceId === selectedId ? "source-card selected" : "source-card"}
                role="button"
                tabIndex={0}
                onClick={() => {
                  onSelect(profile.sourceId);
                  setOpen(true);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(profile.sourceId);
                    setOpen(true);
                  }
                }}
              >
                <div className="source-card-head">
                  <span className={`provider-mark large ${profile.provider}`}>{profile.provider === "postgres" ? "PG" : "API"}</span>
                  <span className={profile.validationStatus === "VALID" ? "source-state verified" : "source-state"}>
                    {statusLabel(profile.validationStatus, t)}
                  </span>
                </div>
                <h2>{profile.label}</h2>
                <code>{profile.sourceId}</code>
                <dl>
                  <div><dt>Mapping</dt><dd>{stats?.mappingCount ?? 0}</dd></div>
                  <div><dt>Action</dt><dd>{stats?.actionCount ?? 0}</dd></div>
                  <div><dt>{t("source.protocol")}</dt><dd>{profile.provider === "postgres" ? "PG" : "API"}</dd></div>
                </dl>
              </article>
            );
          })}
        </div>
      </div>
      {open && selected ? (
        <Window title={selected.label} onClose={() => setOpen(false)}>
          <SourceDetail
            profile={selected}
            catalog={catalogItem}
            mappings={mappings.filter((item) => item.sourceId === selectedId)}
            busy={busy}
            dirty={selectedDirty}
            conflict={conflict}
            onChange={update}
            onSave={() => void save(selected)}
            onRetry={() => void retrySave(selected)}
            onReload={() => void load()}
            onValidate={() => void validate(selected.sourceId)}
          />
        </Window>
      ) : null}
    </>
  );
}

function SourceDetail({
  profile,
  catalog,
  mappings,
  busy,
  dirty,
  conflict,
  onChange,
  onSave,
  onRetry,
  onReload,
  onValidate,
}: {
  profile: Profile;
  catalog?: Source;
  mappings: Mapping[];
  busy: boolean;
  dirty: boolean;
  conflict: boolean;
  onChange: (patch: Partial<Profile>) => void;
  onSave: () => void;
  onRetry: () => void;
  onReload: () => void;
  onValidate: () => void;
}) {
  const { t } = useI18n();
  const [schema, setSchema] = useState<SourceResource[]>([]);
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    if (!profile) {
      setSchema([]);
      return;
    }
    void fetch(`/v0.1/studio/source-profiles/${encodeURIComponent(profile.sourceId)}/schema`)
      .then(checkedJson)
      .then((payload) => {
        setSchema(payload.resources ?? []);
        setReason(payload.reason ?? null);
      })
      .catch(() => {
        setSchema([]);
        setReason("SOURCE_UNAVAILABLE");
      });
  }, [profile?.sourceId]);

  return (
    <>
      <div className="inspector-kicker">
        <span>{profile.provider}</span>
        <span className={`validation-badge ${profile.validationStatus.toLowerCase()}`}>{statusLabel(profile.validationStatus, t)}</span>
      </div>
      <code className="semantic-id">{profile.sourceId}</code>
      <div className="form-grid">
        <label className="form-field"><span>{t("entity.label")}</span><input value={profile.label} onChange={(event) => onChange({ label: event.target.value })} /></label>
        <label className="form-field"><span>{t("source.protocol")}</span>
          <select value={profile.provider} onChange={(event) => onChange({ provider: event.target.value, settings: event.target.value === "openapi" ? { ...profile.settings, healthPath: profile.settings.healthPath ?? "/health" } : profile.settings })}>
            <option value="postgres">PostgreSQL</option>
            <option value="openapi">OpenAPI</option>
          </select>
        </label>
      </div>
      <label className="form-field"><span>{t("source.envBinding")}</span><input aria-label={t("source.envBinding")} value={profile.bindingRef} onChange={(event) => onChange({ bindingRef: event.target.value })} /></label>
      {profile.provider === "openapi" ? (
        <label className="form-field"><span>{t("source.healthPath")}</span>
          <input value={String(profile.settings.healthPath ?? "/health")} onChange={(event) => onChange({ settings: { ...profile.settings, healthPath: event.target.value } })} />
        </label>
      ) : null}
      <p className="mapping-hint">{t("source.connectionHint")}</p>
      {dirty ? <p className="notice">{t("source.unsavedNotice")}</p> : null}
      <p className="mapping-hint" role="status">
        {validationNotice(profile.provider, profile.validationStatus, profile.reason ?? reason, dirty)}
      </p>
      {conflict ? (
        <div className="conflict-actions">
          <button className="secondary" disabled={busy} onClick={onRetry}>{t("status.retryWithCurrent")}</button>
          <button className="secondary" disabled={busy} onClick={onReload}>{t("status.discardAndReload")}</button>
        </div>
      ) : null}
      <div className="chip-row">
        <button className="primary" disabled={busy || !dirty} onClick={onSave}>{t("source.saveConnection")}</button>
        <button className="secondary" disabled={busy} onClick={onValidate}>{t("source.validateConnection")}</button>
      </div>
      <section className="definition-section">
        <div className="section-heading"><h3>{t("source.schema")}</h3><span>{schema.length}</span></div>
        {reason && !schema.length ? <p className="empty">{reason === "SPEC_UNAVAILABLE" ? t("source.specUnavailable") : profile.provider === "openapi" ? t("source.cannotReadApiSpec") : t("source.cannotReadTableSchema")}</p> : null}
        <ul className="schema-list">
          {schema.map((resource) => {
            const tagItems = resource.kind === "operation"
              ? (resource.parameters?.map((item) => item.name) || (resource.operationId ? [resource.operationId] : []))
              : resource.columns.map((column) => column.name);
            return (
              <li key={resource.id}>
                <div className="schema-item-header">
                  <strong>
                    {resource.kind === "operation"
                      ? `${resource.method ?? "GET"} ${resource.name}`
                      : resource.schema && resource.schema !== "public"
                        ? `${resource.schema}.${resource.name}`
                        : resource.name}
                  </strong>
                  <span className="schema-kind-badge">{resource.kind}</span>
                </div>
                {tagItems.length > 0 ? (
                  <div className="schema-tags">
                    {tagItems.map((name) => (
                      <span key={name} className="schema-tag">{name}</span>
                    ))}
                  </div>
                ) : (
                  <small>{resource.kind}</small>
                )}
              </li>
            );
          })}
        </ul>
      </section>
      <section className="definition-section">
        <div className="section-heading"><h3>{t("source.boundMappings")}</h3><span>{mappings.length}</span></div>
        {mappings.length ? (
          <ul className="definition-list">
            {mappings.map((item) => (
              <li key={item.id}>
                <span><strong>{item.target}</strong><code>{item.id}</code></span>
                <small>{item.resource}</small>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">{catalog?.actionCount ? t("source.forActionOnly") : t("source.noMappingsYet")}</p>
        )}
      </section>
    </>
  );
}

function editFields(profile: Profile) {
  return {
    label: profile.label,
    provider: profile.provider,
    bindingRef: profile.bindingRef,
    secretRef: profile.secretRef,
    settings: profile.settings,
  };
}

function upsert(items: Profile[], profile: Profile) {
  if (items.some((item) => item.sourceId === profile.sourceId)) {
    return items.map((item) => (item.sourceId === profile.sourceId ? profile : item));
  }
  return [...items, profile];
}

function statusLabel(status: string, t: (key: I18nKey) => string) {
  if (status === "VALID") return t("source.statusValid");
  if (status === "INVALID") return t("source.statusInvalid");
  if (status === "UNAVAILABLE") return t("source.statusUnavailable");
  return t("source.statusPending");
}

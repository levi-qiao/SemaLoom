import { useEffect, useMemo, useState } from "react";
import { apiHeaders, checkedJson } from "./api";
import { ApiImportModal } from "./ApiImportModal";
import { IconCheck, IconImport } from "./icons";
import { useI18n } from "./i18n";
import type { ApiAuth, ApiOperation, ApiService, DraftDocument } from "./types";

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
  documents: DraftDocument[];
  search: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onError: (message: string | null) => void;
  onChangeDocuments?: (documents: DraftDocument[]) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

export function ApiPage({
  ready,
  documents,
  search,
  selectedId,
  onSelect,
  onError,
  onChangeDocuments,
  onDirtyChange,
}: Props) {
  const { t, locale } = useI18n();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [baseline, setBaseline] = useState<Profile[]>([]);
  const [activeTab, setActiveTab] = useState<"endpoints" | "auth" | "associations" | "settings">("endpoints");
  const [importOpen, setImportOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [filterQuery, setFilterQuery] = useState("");
  const [newApiId, setNewApiId] = useState("");
  const [showAddInline, setShowAddInline] = useState(false);

  async function load() {
    try {
      const payload = await fetch("/v0.1/studio/source-profiles").then(checkedJson);
      const next = (payload.profiles ?? []) as Profile[];
      setProfiles(next);
      setBaseline(next);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "UNKNOWN_ERROR");
    }
  }

  useEffect(() => {
    if (ready) void load();
  }, [ready]);

  // Filter profiles for APIs (provider === 'openapi' or provider === 'api')
  const apiProfiles = useMemo(() => {
    return profiles.filter((p) => p.provider === "openapi" || p.provider === "api");
  }, [profiles]);

  const selectedProfile = useMemo(() => {
    return apiProfiles.find((p) => p.sourceId === selectedId) || apiProfiles[0] || null;
  }, [apiProfiles, selectedId]);

  // Extract endpoints from profile settings or schema
  const currentOperations = useMemo<ApiOperation[]>(() => {
    if (!selectedProfile) return [];
    const settings = selectedProfile.settings || {};
    if (Array.isArray(settings.endpoints)) {
      return settings.endpoints as ApiOperation[];
    }
    // Fallback default operations if standard sample
    if (selectedProfile.sourceId === "proc_draft_api") {
      return [
        {
          operationId: "getOrderRisk",
          method: "GET",
          path: "/order-risk",
          summary: t("api.mockOrderRiskSummary"),
          parameters: [
            { name: "orderId", in: "query", required: true, type: "string" },
            { name: "tenant", in: "query", required: true, type: "string" },
          ],
          responses: { "200": { properties: ["orderId", "deliveryRisk"] } },
        },
        {
          operationId: "createPurchaseDraft",
          method: "POST",
          path: "/drafts",
          summary: t("api.mockPurchaseDraftSummary"),
          parameters: [
            { name: "tenant", in: "query", required: true, type: "string" },
          ],
          requestBody: { properties: ["supplierId", "amount", "items"] },
        },
      ];
    }
    return [];
  }, [selectedProfile]);

  // Find associated Actions & Mappings
  const associations = useMemo(() => {
    if (!selectedProfile) return { actions: [], mappings: [] };
    const sid = selectedProfile.sourceId;

    const actionBindings = documents.filter(
      (doc) => doc.kind === "ActionBinding" && doc.sourceId === sid,
    );
    const actionIds = new Set(actionBindings.map((ab) => String(ab.action)));
    const actions = documents.filter((doc) => doc.kind === "Action" && actionIds.has(doc.id));

    const mappings = documents.filter(
      (doc) => doc.kind === "Mapping" && doc.sourceId === sid,
    );

    return { actions, mappings };
  }, [selectedProfile, documents]);

  // Auth config
  const currentAuth = useMemo<ApiAuth>(() => {
    if (!selectedProfile) return { type: "none" };
    const auth = (selectedProfile.settings?.auth || {}) as Record<string, unknown>;
    return {
      type: (auth.type as ApiAuth["type"]) || "none",
      token: typeof auth.token === "string" ? auth.token : "",
      keyName: typeof auth.keyName === "string" ? auth.keyName : "X-API-Key",
      keyIn: (auth.keyIn as ApiAuth["keyIn"]) || "header",
      keyValue: typeof auth.keyValue === "string" ? auth.keyValue : "",
      username: typeof auth.username === "string" ? auth.username : "",
      password: typeof auth.password === "string" ? auth.password : "",
    };
  }, [selectedProfile]);

  function updateProfile(patch: Partial<Profile>) {
    if (!selectedProfile) return;
    setProfiles((prev) =>
      prev.map((p) => (p.sourceId === selectedProfile.sourceId ? { ...p, ...patch } : p)),
    );
  }

  function updateSettings(patch: Record<string, unknown>) {
    if (!selectedProfile) return;
    const nextSettings = { ...selectedProfile.settings, ...patch };
    updateProfile({ settings: nextSettings });
  }

  async function saveCurrent() {
    if (!selectedProfile) return;
    setBusy(true);
    onError(null);
    try {
      const saved = (await fetch(
        `/v0.1/studio/source-profiles/${encodeURIComponent(selectedProfile.sourceId)}`,
        {
          method: "PUT",
          headers: apiHeaders(),
          body: JSON.stringify({
            expectedRevision: selectedProfile.revision,
            label: selectedProfile.label,
            provider: selectedProfile.provider,
            bindingRef: selectedProfile.bindingRef,
            secretRef: selectedProfile.secretRef || null,
            settings: selectedProfile.settings,
          }),
        },
      ).then(checkedJson)) as Profile;

      setProfiles((prev) =>
        prev.map((p) => (p.sourceId === saved.sourceId ? { ...saved, reason: null } : p)),
      );
      setBaseline((prev) =>
        prev.map((p) => (p.sourceId === saved.sourceId ? { ...saved, reason: null } : p)),
      );
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "SAVE_FAILED");
    } finally {
      setBusy(false);
    }
  }

  async function handleImportConfirm(service: ApiService) {
    setBusy(true);
    onError(null);
    try {
      // Upsert via source profile API with provider=openapi
      const existing = profiles.find((p) => p.sourceId === service.id);
      const expectedRevision = existing ? existing.revision : 0;
      const settings = {
        baseUrl: service.baseUrl,
        description: service.description,
        auth: service.auth,
        endpoints: service.operations,
        healthPath: "/health",
      };

      const saved = (await fetch(
        `/v0.1/studio/source-profiles/${encodeURIComponent(service.id)}`,
        {
          method: "PUT",
          headers: apiHeaders(),
          body: JSON.stringify({
            expectedRevision,
            label: service.label,
            provider: "openapi",
            bindingRef: service.id,
            secretRef: null,
            settings,
          }),
        },
      ).then(checkedJson)) as Profile;

      setProfiles((prev) => {
        const others = prev.filter((p) => p.sourceId !== saved.sourceId);
        return [...others, saved];
      });
      setBaseline((prev) => {
        const others = prev.filter((p) => p.sourceId !== saved.sourceId);
        return [...others, saved];
      });
      onSelect(saved.sourceId);
    } catch (err) {
      onError(err instanceof Error ? err.message : "IMPORT_FAILED");
    } finally {
      setBusy(false);
    }
  }

  async function handleManualCreate() {
    const id = newApiId.trim();
    if (!id) return;
    setBusy(true);
    onError(null);
    try {
      const saved = (await fetch(
        `/v0.1/studio/source-profiles/${encodeURIComponent(id)}`,
        {
          method: "PUT",
          headers: apiHeaders(),
          body: JSON.stringify({
            expectedRevision: 0,
            label: id,
            provider: "openapi",
            bindingRef: id,
            secretRef: null,
            settings: {
              baseUrl: "http://127.0.0.1:8000",
              endpoints: [],
              auth: { type: "none" },
            },
          }),
        },
      ).then(checkedJson)) as Profile;

      setProfiles((prev) => [...prev, saved]);
      setBaseline((prev) => [...prev, saved]);
      onSelect(saved.sourceId);
      setNewApiId("");
      setShowAddInline(false);
    } catch (err) {
      onError(err instanceof Error ? err.message : "CREATE_FAILED");
    } finally {
      setBusy(false);
    }
  }

  const filteredOperations = useMemo(() => {
    if (!filterQuery) return currentOperations;
    const q = filterQuery.toLowerCase();
    return currentOperations.filter(
      (op) =>
        op.path.toLowerCase().includes(q) ||
        op.method.toLowerCase().includes(q) ||
        (op.summary && op.summary.toLowerCase().includes(q)) ||
        op.operationId.toLowerCase().includes(q),
    );
  }, [currentOperations, filterQuery]);

  return (
    <div className="api-tier-page">
      {/* Sidebar: API Services List */}
      <div className="api-tier-sidebar">
        <div className="api-sidebar-header">
          <div className="api-sidebar-title-row">
            <h3>{t("api.listTitle")}</h3>
            <span className="api-count-badge">{apiProfiles.length}</span>
          </div>

          <div className="api-sidebar-actions">
            <button
              type="button"
              className="primary compact-btn"
              onClick={() => setImportOpen(true)}
            >
              <IconImport size={13} style={{ marginRight: 5, verticalAlign: "text-bottom" }} />
              {t("api.importOnline")}
            </button>
            <button
              type="button"
              className="secondary compact-btn"
              onClick={() => setShowAddInline(!showAddInline)}
            >
              {t("api.manualConfig")}
            </button>
          </div>

          {showAddInline ? (
            <div className="api-inline-create">
              <input
                value={newApiId}
                onChange={(e) => setNewApiId(e.target.value)}
                placeholder={t("api.idPlaceholder")}
                autoFocus
              />
              <div className="api-inline-actions">
                <button
                  type="button"
                  className="primary compact-btn"
                  disabled={!newApiId.trim() || busy}
                  onClick={() => void handleManualCreate()}
                >
                  {t("common.create")}
                </button>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setShowAddInline(false)}
                >
                  {t("common.cancel")}
                </button>
              </div>
            </div>
          ) : null}
        </div>

        <ul className="api-service-list">
          {apiProfiles.map((p) => {
            const isSelected = selectedProfile?.sourceId === p.sourceId;
            const opCount = Array.isArray(p.settings?.endpoints) ? p.settings.endpoints.length : (p.sourceId === "proc_draft_api" ? 2 : 0);
            return (
              <li key={p.sourceId}>
                <button
                  type="button"
                  className={`api-service-card ${isSelected ? "active" : ""}`}
                  onClick={() => onSelect(p.sourceId)}
                >
                  <div className="api-card-top">
                    <span className="method-badge get">API</span>
                    <span className={`api-card-status ${p.validationStatus === "VALID" ? "is-valid" : ""}`}>
                      {p.validationStatus === "VALID" ? (
                        <>
                          <IconCheck size={11} style={{ marginRight: 3, verticalAlign: "middle" }} />
                          {t("api.verified")}
                        </>
                      ) : t("api.unverified")}
                    </span>
                  </div>
                  <strong className="api-card-title">{p.label || p.sourceId}</strong>
                  <code className="api-card-id">{p.sourceId}</code>
                  <div className="api-card-meta">
                    <span>{t("api.endpointCount", { count: opCount })}</span>
                    <span className="meta-sep">·</span>
                    <span>{String(p.settings?.baseUrl || "http://127.0.0.1:8000")}</span>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      {/* Main detail area */}
      <div className="api-tier-main">
        {selectedProfile ? (
          <>
            <div className="api-main-header">
              <div className="api-main-title-block">
                <div className="api-title-row">
                  <h2>{selectedProfile.label || selectedProfile.sourceId}</h2>
                  <span className="api-proto-badge">OpenAPI / REST</span>
                  <span className="api-id-tag">{selectedProfile.sourceId}</span>
                </div>
                <div className="api-url-row">
                  <span className="url-label">Base URL:</span>
                  <code className="url-val">{String(selectedProfile.settings?.baseUrl || "http://127.0.0.1:8000")}</code>
                </div>
              </div>

              <div className="api-main-actions">
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={() => void saveCurrent()}
                >
                  {busy ? t("common.saving") : t("api.saveConfig")}
                </button>
              </div>
            </div>

            <div className="api-tabs-nav">
              <button
                type="button"
                className={`api-tab-link ${activeTab === "endpoints" ? "active" : ""}`}
                onClick={() => setActiveTab("endpoints")}
              >
                {t("api.tabEndpoints", { count: currentOperations.length })}
              </button>
              <button
                type="button"
                className={`api-tab-link ${activeTab === "auth" ? "active" : ""}`}
                onClick={() => setActiveTab("auth")}
              >
                {t("api.tabAuth", { scheme: currentAuth.type === "none" ? t("common.none") : currentAuth.type })}
              </button>
              <button
                type="button"
                className={`api-tab-link ${activeTab === "associations" ? "active" : ""}`}
                onClick={() => setActiveTab("associations")}
              >
                {t("api.tabAssoc", { actions: associations.actions.length, mappings: associations.mappings.length })}
              </button>
              <button
                type="button"
                className={`api-tab-link ${activeTab === "settings" ? "active" : ""}`}
                onClick={() => setActiveTab("settings")}
              >
                {t("api.tabBase")}
              </button>
            </div>

            <div className="api-tab-content">
              {activeTab === "endpoints" ? (
                <div className="endpoints-pane">
                  <div className="endpoints-filter-bar">
                    <input
                      value={filterQuery}
                      onChange={(e) => setFilterQuery(e.target.value)}
                      placeholder={t("api.filterEndpointsPlaceholder")}
                      className="endpoints-search-input"
                    />
                    <span className="endpoints-stats">
                      {t("api.showingEndpoints", { filtered: filteredOperations.length, total: currentOperations.length })}
                    </span>
                  </div>

                  <div className="endpoints-list">
                    {filteredOperations.length > 0 ? (
                      filteredOperations.map((op) => (
                        <div key={`${op.method}-${op.path}`} className="endpoint-item-card">
                          <div className="endpoint-card-head">
                            <span className={`method-badge ${op.method.toLowerCase()}`}>
                              {op.method}
                            </span>
                            <code className="endpoint-path">{op.path}</code>
                            <span className="endpoint-opid">{op.operationId}</span>
                          </div>
                          {op.summary ? (
                            <p className="endpoint-summary">{op.summary}</p>
                          ) : null}

                          {op.parameters && op.parameters.length > 0 ? (
                            <div className="endpoint-params-row">
                              <span className="params-label">{t("api.requestParams")}</span>
                              <div className="params-tags">
                                {op.parameters.map((param) => (
                                  <span key={param.name} className="param-tag">
                                    <code>{param.name}</code>
                                    <small>({param.in})</small>
                                    {param.required ? <strong className="req-star">*</strong> : null}
                                  </span>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      ))
                    ) : (
                      <div className="empty-endpoints">
                        <p>{t("api.noMatchingEndpoints")}</p>
                        <button
                          type="button"
                          className="secondary compact-btn"
                          onClick={() => setImportOpen(true)}
                        >
                          {t("api.importOpenApiFromWeb")}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ) : null}

              {activeTab === "auth" ? (
                <div className="api-auth-pane">
                  <div className="form-grid">
                    <label className="form-field">
                      <span>{t("api.authScheme")}</span>
                      <select
                        value={currentAuth.type}
                        onChange={(e) =>
                          updateSettings({
                            auth: { ...currentAuth, type: e.target.value as ApiAuth["type"] },
                          })
                        }
                      >
                        <option value="none">{t("api.authNone")}</option>
                        <option value="bearer">Bearer Token (JWT / OAuth2)</option>
                        <option value="apiKey">API Key (Header / Query)</option>
                        <option value="basic">{t("api.authBasic")}</option>
                      </select>
                    </label>

                    {currentAuth.type === "bearer" ? (
                      <label className="form-field full-width">
                        <span>{t("api.tokenCredential")}</span>
                        <input
                          type="password"
                          value={currentAuth.token || ""}
                          onChange={(e) =>
                            updateSettings({
                              auth: { ...currentAuth, token: e.target.value },
                            })
                          }
                          placeholder="ey..."
                        />
                      </label>
                    ) : null}

                    {currentAuth.type === "apiKey" ? (
                      <>
                        <label className="form-field">
                          <span>{t("api.keyParamName")}</span>
                          <input
                            value={currentAuth.keyName || "X-API-Key"}
                            onChange={(e) =>
                              updateSettings({
                                auth: { ...currentAuth, keyName: e.target.value },
                              })
                            }
                            placeholder="X-API-Key"
                          />
                        </label>
                        <label className="form-field">
                          <span>{t("api.paramLocation")}</span>
                          <select
                            value={currentAuth.keyIn || "header"}
                            onChange={(e) =>
                              updateSettings({
                                auth: {
                                  ...currentAuth,
                                  keyIn: e.target.value as ApiAuth["keyIn"],
                                },
                              })
                            }
                          >
                            <option value="header">HTTP Header</option>
                            <option value="query">Query Parameter</option>
                          </select>
                        </label>
                        <label className="form-field full-width">
                          <span>{t("api.apiKeyCredential")}</span>
                          <input
                            type="password"
                            value={currentAuth.keyValue || ""}
                            onChange={(e) =>
                              updateSettings({
                                auth: { ...currentAuth, keyValue: e.target.value },
                              })
                            }
                            placeholder="Secret key..."
                          />
                        </label>
                      </>
                    ) : null}

                    {currentAuth.type === "basic" ? (
                      <>
                        <label className="form-field">
                          <span>{t("api.username")}</span>
                          <input
                            value={currentAuth.username || ""}
                            onChange={(e) =>
                              updateSettings({
                                auth: { ...currentAuth, username: e.target.value },
                              })
                            }
                          />
                        </label>
                        <label className="form-field">
                          <span>{t("api.password")}</span>
                          <input
                            type="password"
                            value={currentAuth.password || ""}
                            onChange={(e) =>
                              updateSettings({
                                auth: { ...currentAuth, password: e.target.value },
                              })
                            }
                          />
                        </label>
                      </>
                    ) : null}
                  </div>
                  <p className="mapping-hint">
                    {t("api.authNotice")}
                  </p>
                </div>
              ) : null}

              {activeTab === "associations" ? (
                <div className="api-assoc-pane">
                  <div className="assoc-section">
                    <div className="assoc-head">
                      <h4>{t("api.assocActions")}</h4>
                      <span className="assoc-badge">{associations.actions.length}</span>
                    </div>
                    {associations.actions.length > 0 ? (
                      <ul className="assoc-items-list">
                        {associations.actions.map((act) => (
                          <li key={act.id} className="assoc-item">
                            <span className="assoc-kind-badge action">Action</span>
                            <strong>{String(act.label || act.id)}</strong>
                            <code>{act.id}</code>
                            <span className="assoc-desc">{String(act.effect || "")}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="empty-hint">{t("api.assocEmptyActions")}</p>
                    )}
                  </div>

                  <div className="assoc-section">
                    <div className="assoc-head">
                      <h4>{t("api.assocMappings")}</h4>
                      <span className="assoc-badge">{associations.mappings.length}</span>
                    </div>
                    {associations.mappings.length > 0 ? (
                      <ul className="assoc-items-list">
                        {associations.mappings.map((m) => {
                          const phys = (m.physical || {}) as Record<string, unknown>;
                          const resName = String(phys.operationId || phys.path || "");
                          return (
                            <li key={m.id} className="assoc-item">
                              <span className="assoc-kind-badge mapping">Mapping</span>
                              <strong>{String(m.target)}</strong>
                              <code>{m.id}</code>
                              <span className="assoc-desc">{t("api.assocPhysicalResource", { resource: resName })}</span>
                            </li>
                          );
                        })}
                      </ul>
                    ) : (
                      <p className="empty-hint">{t("api.assocEmptyMappings")}</p>
                    )}
                  </div>
                </div>
              ) : null}

              {activeTab === "settings" ? (
                <div className="api-settings-pane">
                  <div className="form-grid">
                    <label className="form-field">
                      <span>{t("api.serviceName")}</span>
                      <input
                        value={selectedProfile.label}
                        onChange={(e) => updateProfile({ label: e.target.value })}
                      />
                    </label>

                    <label className="form-field">
                      <span>{t("api.serviceId")}</span>
                      <input value={selectedProfile.sourceId} disabled className="is-readonly" />
                    </label>

                    <label className="form-field full-width">
                      <span>{t("api.serviceBaseUrl")}</span>
                      <input
                        value={String(selectedProfile.settings?.baseUrl || "http://127.0.0.1:8000")}
                        onChange={(e) =>
                          updateSettings({ baseUrl: e.target.value })
                        }
                        placeholder="http://127.0.0.1:8000"
                      />
                    </label>

                    <label className="form-field full-width">
                      <span>{t("api.healthCheckPath")}</span>
                      <input
                        value={String(selectedProfile.settings?.healthPath || "/health")}
                        onChange={(e) =>
                          updateSettings({ healthPath: e.target.value })
                        }
                        placeholder="/health"
                      />
                    </label>

                    <label className="form-field full-width">
                      <span>{t("api.description")}</span>
                      <textarea
                        rows={3}
                        value={String(selectedProfile.settings?.description || "")}
                        onChange={(e) =>
                          updateSettings({ description: e.target.value })
                        }
                        placeholder={t("api.descriptionPlaceholder")}
                      />
                    </label>
                  </div>
                </div>
              ) : null}
            </div>
          </>
        ) : (
          <div className="empty-selection">
            <h3>{t("api.selectOrImport")}</h3>
            <p>{t("api.selectOrImportDesc")}</p>
            <button
              type="button"
              className="primary"
              onClick={() => setImportOpen(true)}
            >
              <IconImport size={14} style={{ marginRight: 6, verticalAlign: "text-bottom" }} />
              {t("api.importOnlineBtn")}
            </button>
          </div>
        )}
      </div>

      <ApiImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImport={(svc) => void handleImportConfirm(svc)}
        onError={onError}
      />
    </div>
  );
}

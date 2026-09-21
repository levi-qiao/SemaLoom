import { useState } from "react";
import { apiHeaders, checkedJson } from "./api";
import { IconAlert } from "./icons";
import { Modal } from "./Modal";
import { useI18n, currentLocale } from "./i18n";
import type { ApiAuth, ApiOperation, ApiParameter, ApiService } from "./types";

type Props = {
  open: boolean;
  onClose: () => void;
  onImport: (service: ApiService) => void;
  onError: (message: string | null) => void;
};

export function ApiImportModal({ open, onClose, onImport, onError }: Props) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<"url" | "text">("url");
  const [url, setUrl] = useState("http://127.0.0.1:8000/openapi.json");
  const [authType, setAuthType] = useState<ApiAuth["type"]>("none");
  const [token, setToken] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [rawText, setRawText] = useState("");
  const [busy, setBusy] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [previewService, setPreviewService] = useState<ApiService | null>(null);

  if (!open) return null;

  function parseSpec(specObj: Record<string, unknown>, sourceUrl?: string): ApiService {
    // 1. Check if it's Postman Collection v2.1
    if (
      specObj.info &&
      typeof specObj.info === "object" &&
      (Boolean((specObj.info as Record<string, unknown>)._postman_id) ||
        Array.isArray(specObj.item))
    ) {
      return parsePostmanCollection(specObj, sourceUrl);
    }

    // 2. Otherwise handle OpenAPI 2.0 / 3.0 / 3.1
    return parseOpenApiSpec(specObj, sourceUrl);
  }

  function parsePostmanCollection(
    spec: Record<string, unknown>,
    sourceUrl?: string,
  ): ApiService {
    const info = (spec.info || {}) as Record<string, unknown>;
    const title = String(info.name || "Postman Imported API");
    const id = slugify(title);
    const operations: ApiOperation[] = [];

    function walkItems(items: unknown[]) {
      for (const item of items) {
        if (typeof item !== "object" || item === null) continue;
        const entry = item as Record<string, unknown>;
        if (Array.isArray(entry.item)) {
          walkItems(entry.item);
          continue;
        }
        const req = (entry.request || {}) as Record<string, unknown>;
        const method = String(req.method || "GET").toUpperCase() as ApiOperation["method"];
        let path = "/";
        let rawUrl = "";
        if (typeof req.url === "string") {
          rawUrl = req.url;
        } else if (typeof req.url === "object" && req.url !== null) {
          const u = req.url as Record<string, unknown>;
          rawUrl = String(u.raw || "");
          if (Array.isArray(u.path)) {
            path = "/" + u.path.map(String).join("/");
          }
        }
        if (!path.startsWith("/")) path = "/" + path;

        operations.push({
          operationId: slugify(String(entry.name || `${method} ${path}`)),
          method,
          path,
          summary: String(entry.name || path),
          parameters: [],
        });
      }
    }

    if (Array.isArray(spec.item)) {
      walkItems(spec.item);
    }

    return {
      id,
      label: title,
      baseUrl: sourceUrl ? extractBaseUrl(sourceUrl) : "http://127.0.0.1:8000",
      description: String(info.description || t("api.postmanDefaultDesc")),
      auth: { type: "none" },
      operations,
    };
  }

  function parseOpenApiSpec(spec: Record<string, unknown>, sourceUrl?: string): ApiService {
    const info = (spec.info || {}) as Record<string, unknown>;
    const title = String(info.title || "OpenAPI Imported Service");
    const id = slugify(title);
    const description = String(info.description || "");

    // Extract baseUrl
    let baseUrl = "http://127.0.0.1:8000";
    if (Array.isArray(spec.servers) && spec.servers.length > 0) {
      const s = spec.servers[0] as Record<string, unknown>;
      if (typeof s.url === "string" && s.url.startsWith("http")) {
        baseUrl = s.url;
      }
    } else if (sourceUrl) {
      baseUrl = extractBaseUrl(sourceUrl);
    }

    // Extract auth from components.securitySchemes
    const detectedAuth: ApiAuth = { type: "none" };
    const components = (spec.components || {}) as Record<string, unknown>;
    const schemes = (components.securitySchemes || {}) as Record<string, unknown>;
    for (const [sName, sVal] of Object.entries(schemes)) {
      if (typeof sVal !== "object" || sVal === null) continue;
      const scheme = sVal as Record<string, unknown>;
      const stype = String(scheme.type || "").toLowerCase();
      if (stype === "http" && String(scheme.scheme || "").toLowerCase() === "bearer") {
        detectedAuth.type = "bearer";
        break;
      } else if (stype === "apikey") {
        detectedAuth.type = "apiKey";
        detectedAuth.keyName = String(scheme.name || "X-API-Key");
        detectedAuth.keyIn = scheme.in === "query" ? "query" : "header";
        break;
      } else if (stype === "http" && String(scheme.scheme || "").toLowerCase() === "basic") {
        detectedAuth.type = "basic";
        break;
      }
    }

    // Extract operations from paths
    const operations: ApiOperation[] = [];
    const paths = (spec.paths || {}) as Record<string, unknown>;
    for (const [pathStr, pathVal] of Object.entries(paths)) {
      if (typeof pathVal !== "object" || pathVal === null) continue;
      const pathObj = pathVal as Record<string, unknown>;
      const commonParams = Array.isArray(pathObj.parameters) ? pathObj.parameters : [];

      for (const [methodKey, opVal] of Object.entries(pathObj)) {
        if (!["get", "post", "put", "delete", "patch"].includes(methodKey.toLowerCase())) {
          continue;
        }
        if (typeof opVal !== "object" || opVal === null) continue;
        const op = opVal as Record<string, unknown>;
        const method = methodKey.toUpperCase() as ApiOperation["method"];
        const opId = String(op.operationId || `${method.toLowerCase()}_${pathStr.replace(/[^a-zA-Z0-9]/g, "_")}`);
        const summary = String(op.summary || op.description || `${method} ${pathStr}`);

        const parameters: ApiParameter[] = [];
        const opParams = Array.isArray(op.parameters) ? op.parameters : [];
        for (const p of [...commonParams, ...opParams]) {
          if (typeof p !== "object" || p === null) continue;
          const param = p as Record<string, unknown>;
          const pName = String(param.name || "");
          if (pName && pName !== "tenant") {
            parameters.push({
              name: pName,
              in: (param.in === "path" || param.in === "header" ? param.in : "query"),
              required: Boolean(param.required),
              type: typeof param.schema === "object" ? String((param.schema as Record<string, unknown>).type || "string") : "string",
              description: typeof param.description === "string" ? param.description : undefined,
            });
          }
        }

        operations.push({
          operationId: opId,
          method,
          path: pathStr,
          summary,
          parameters,
        });
      }
    }

    return {
      id,
      label: title,
      baseUrl,
      description,
      auth: detectedAuth,
      operations,
    };
  }

  async function handleFetchUrl() {
    if (!url.trim()) return;
    setBusy(true);
    setParseError(null);
    try {
      const res = await fetch("/v0.1/studio/apis/fetch-spec", {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({
          url: url.trim(),
          auth_type: authType,
          token: authType === "bearer" ? token : undefined,
          api_key: authType === "apiKey" ? apiKey : undefined,
        }),
      }).then(checkedJson);

      let specObj: Record<string, unknown>;
      if (res.spec && typeof res.spec === "object") {
        specObj = res.spec as Record<string, unknown>;
      } else if (typeof res.raw === "string") {
        specObj = JSON.parse(res.raw) as Record<string, unknown>;
      } else {
        throw new Error(t("api.unrecognizedSpec"));
      }

      const parsed = parseSpec(specObj, url.trim());
      setPreviewService(parsed);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : t("api.fetchFailed"));
    } finally {
      setBusy(false);
    }
  }

  function handleParseText() {
    if (!rawText.trim()) return;
    setParseError(null);
    try {
      const parsedJson = JSON.parse(rawText.trim()) as Record<string, unknown>;
      const parsed = parseSpec(parsedJson);
      setPreviewService(parsed);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : t("api.jsonParseFailed"));
    }
  }

  function handleConfirmImport() {
    if (!previewService) return;
    onImport(previewService);
    onClose();
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("api.importModalTitle")}
      subtitle={t("api.importModalSubtitle")}
      ariaLabel={t("api.importModalAria")}
      size="lg"
      className="api-import-modal"
    >
      <div className="import-tab-row">
          <button
            type="button"
            className={`import-tab-btn ${activeTab === "url" ? "active" : ""}`}
            onClick={() => { setActiveTab("url"); setPreviewService(null); }}
          >
            {t("api.fromUrlTab")}
          </button>
          <button
            type="button"
            className={`import-tab-btn ${activeTab === "text" ? "active" : ""}`}
            onClick={() => { setActiveTab("text"); setPreviewService(null); }}
          >
            {t("api.fromPasteTab")}
          </button>
        </div>

        <div className="modal-body api-import-body">
          {activeTab === "url" ? (
            <div className="form-grid">
              <label className="form-field full-width">
                <span>{t("api.urlLabel")}</span>
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://api.example.com/openapi.json"
                />
              </label>

              <label className="form-field">
                <span>{t("api.fetchAuth")}</span>
                <select value={authType} onChange={(e) => setAuthType(e.target.value as ApiAuth["type"])}>
                  <option value="none">{t("api.authNone")}</option>
                  <option value="bearer">Bearer Token</option>
                  <option value="apiKey">API Key</option>
                </select>
              </label>

              {authType === "bearer" ? (
                <label className="form-field">
                  <span>Bearer Token</span>
                  <input
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder={t("api.tokenPlaceholder")}
                  />
                </label>
              ) : null}

              {authType === "apiKey" ? (
                <label className="form-field">
                  <span>API Key</span>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={t("api.keyPlaceholder")}
                  />
                </label>
              ) : null}

              <div className="form-action-row full-width">
                <button
                  type="button"
                  className="primary"
                  disabled={busy || !url.trim()}
                  onClick={() => void handleFetchUrl()}
                >
                  {busy ? t("api.fetching") : t("api.fetchAndParse")}
                </button>
              </div>
            </div>
          ) : (
            <div className="text-import-group">
              <label className="form-field">
                <span>{t("api.pasteLabel")}</span>
                <textarea
                  rows={8}
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  placeholder='{"openapi": "3.0.0", "info": {"title": "Sample API", "version": "1.0.0"}, "paths": {...}}'
                />
              </label>
              <button
                type="button"
                className="primary"
                disabled={!rawText.trim()}
                onClick={handleParseText}
              >
                {t("api.parseContent")}
              </button>
            </div>
          )}

          {parseError ? (
            <div className="import-error-box" role="alert">
              <IconAlert size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>{parseError}</span>
            </div>
          ) : null}

          {previewService ? (
            <div className="import-preview-box">
              <div className="import-preview-head">
                <div className="preview-service-meta">
                  <span className="api-badge">API</span>
                  <strong>{previewService.label}</strong>
                  <code>{previewService.id}</code>
                  <span className="preview-url">{previewService.baseUrl}</span>
                </div>
                <div className="preview-auth-badge">
                  {t("api.authSchemeDisplay", { scheme: previewService.auth.type === "none" ? t("api.authNone") : previewService.auth.type })}
                </div>
              </div>

              <div className="preview-operations-list">
                <div className="preview-list-title">
                  {t("api.parseSuccessCount", { count: previewService.operations.length })}
                </div>
                <ul className="preview-op-items">
                  {previewService.operations.map((op) => (
                    <li key={`${op.method}-${op.path}`} className="preview-op-item">
                      <span className={`method-badge ${op.method.toLowerCase()}`}>{op.method}</span>
                      <code className="op-path">{op.path}</code>
                      <span className="op-summary">{op.summary}</span>
                      <span className="op-params-count">{t("api.paramCount", { count: op.parameters?.length ?? 0 })}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="import-confirm-row">
                <button type="button" className="primary" onClick={handleConfirmImport}>
                  {t("api.confirmImport")}
                </button>
                <button type="button" className="secondary" onClick={() => setPreviewService(null)}>
                  {t("api.reconfigure")}
                </button>
              </div>
            </div>
          ) : null}
        </div>
    </Modal>
  );
}

function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "api_service"
  );
}

function extractBaseUrl(fullUrl: string): string {
  try {
    const parsed = new URL(fullUrl);
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

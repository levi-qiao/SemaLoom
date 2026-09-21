export type PackLabel = { id: string; namespace?: string; label: string };
import { currentLocale, translate } from "./i18n";

export function namespaceLabel(id: string, packs: PackLabel[] = []) {
  const pack = packs.find((item) => item.id === id || item.namespace === id);
  return pack?.label || id;
}

export function additivityOptions() {
  const locale = currentLocale();
  return [
    { id: "FULL", label: translate(locale, "labels.additivity.full") },
    { id: "SEMI", label: translate(locale, "labels.additivity.semi") },
    { id: "NONE", label: translate(locale, "labels.additivity.none") },
  ] as const;
}

export function cardinalityLabel(cardinality: string) {
  const locale = currentLocale();
  return cardinality === "MANY"
    ? translate(locale, "labels.cardinality.many")
    : translate(locale, "labels.cardinality.one");
}

export function cardinalityMark(cardinality: string) {
  return cardinality === "MANY" ? "N→N" : "N→1";
}

export function cardinalityHint(sourceLabel: string, targetLabel: string, cardinality: string) {
  const locale = currentLocale();
  if (cardinality === "MANY") {
    return translate(locale, "labels.link.many", { source: sourceLabel, target: targetLabel });
  }
  return translate(locale, "labels.link.one", { source: sourceLabel, target: targetLabel });
}

export function draftPreviewHint(saved: boolean, revision: number) {
  const locale = currentLocale();
  if (!saved) return translate(locale, "labels.preview.saveBefore");
  return translate(locale, "labels.preview.savedModel", { revision });
}

export function publishedExecutionHint() {
  return translate(currentLocale(), "labels.preview.saveShared");
}

export function draftSaveLabel() {
  return translate(currentLocale(), "common.save");
}

export function gateErrorMessage(detail: string, status?: number) {
  const locale = currentLocale();
  if (status === 401 || detail === "UNAUTHENTICATED" || detail === "SESSION_EXPIRED" || detail === "SESSION_REQUIRED") {
    return translate(locale, "gate.sessionExpired", { detail });
  }
  if (status === 403 || detail === "FORBIDDEN") {
    return translate(locale, "gate.forbidden");
  }
  if (status === 409 || detail === "REVISION_CONFLICT") {
    return translate(locale, "gate.conflict");
  }
  return detail;
}

export function previewOutcomeText(provider: string, kind: string, reason: string | null) {
  const locale = currentLocale();
  if (kind === "PRESENT") return translate(locale, "labels.preview.hit");
  const api = provider === "openapi";
  if (kind === "MISSING" || reason === "NO_ROW") {
    return translate(locale, api ? "labels.preview.noRecordApi" : "labels.preview.noRecordDb");
  }
  if (kind === "NULL") {
    return translate(locale, api ? "labels.preview.nullApi" : "labels.preview.nullDb");
  }
  return previewFailureText(provider, reason);
}

function previewFailureText(provider: string, reason: string | null) {
  const locale = currentLocale();
  const api = provider === "openapi";
  if (reason === "SOURCE_UNAVAILABLE" || reason === "PROVIDER_NOT_CONFIGURED" || reason === "BINDING_NOT_RESOLVED") {
    return translate(locale, api ? "labels.preview.connectFailApi" : "labels.preview.connectFailDb");
  }
  if (reason === "SOURCE_TIMEOUT") {
    return translate(locale, api ? "labels.preview.timeoutApi" : "labels.preview.timeoutDb");
  }
  if (reason === "IDENTITY_MISMATCH") {
    return translate(locale, api ? "labels.preview.idMismatchApi" : "labels.preview.idMismatchDb");
  }
  const sep = locale === "en" ? ": " : "：";
  const reasonText = reason ? `${sep}${reason}` : "";
  return translate(locale, api ? "labels.preview.readFailedApi" : "labels.preview.readFailedDb", { reason: reasonText });
}

export function validationNotice(provider: string, status: string, reason: string | null, unsaved: boolean) {
  const locale = currentLocale();
  const checked = unsaved ? translate(locale, "labels.validation.unsaved") : "";
  if (status === "VALID") return unsaved ? checked : translate(locale, "labels.validation.valid");
  if (status === "UNAVAILABLE") {
    const failure = translate(locale, provider === "openapi" ? "labels.validation.cannotConnectApi" : "labels.validation.cannotConnectDb");
    const sep = locale === "en" ? ": " : "：";
    return `${failure}${reason ? `${sep}${reason}` : ""}. ${checked}`.trim();
  }
  if (status === "INVALID") {
    const failure = translate(locale, provider === "openapi" ? "labels.validation.invalidConfigApi" : "labels.validation.invalidConfigDb");
    const sep = locale === "en" ? ": " : "：";
    return `${failure}${reason ? `${sep}${reason}` : ""}. ${checked}`.trim();
  }
  return checked || translate(locale, "labels.validation.pending");
}

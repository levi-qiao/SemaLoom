export type PackLabel = { id: string; namespace?: string; label: string };

export function namespaceLabel(id: string, packs: PackLabel[] = []) {
  const pack = packs.find((item) => item.id === id || item.namespace === id);
  return pack?.label || id;
}

export const ADDITIVITY_OPTIONS = [
  { id: "FULL", label: "可合计" },
  { id: "SEMI", label: "时点存量" },
  { id: "NONE", label: "不可合计" },
] as const;

export function cardinalityLabel(cardinality: string) {
  return cardinality === "MANY" ? "源到目标可有多个" : "源到目标至多一个";
}

export function cardinalityMark(cardinality: string) {
  return cardinality === "MANY" ? "N→N" : "N→1";
}

export function cardinalityHint(sourceLabel: string, targetLabel: string, cardinality: string) {
  if (cardinality === "MANY") return `每个${sourceLabel}可对应多个${targetLabel}`;
  return `每个${sourceLabel}对应一个${targetLabel}`;
}

export function draftPreviewHint(saved: boolean, revision: number) {
  if (!saved) return "先保存再试读。";
  return `试读已保存模型 r${revision}（与问答同一份）。`;
}

export function publishedExecutionHint() {
  return "保存后，试读与问答使用同一份模型。";
}

export function draftSaveLabel() {
  return "保存";
}

export function gateErrorMessage(detail: string, status?: number) {
  if (status === 401 || detail === "UNAUTHENTICATED" || detail === "SESSION_EXPIRED" || detail === "SESSION_REQUIRED") {
    return `会话已失效（${detail}）。请重新载入页面。`;
  }
  if (status === 403 || detail === "FORBIDDEN") {
    return "当前身份没有这项权限。服务端已拒绝；隐藏按钮不能代替后端检查。";
  }
  if (status === 409 || detail === "REVISION_CONFLICT") {
    return "保存冲突。本地修改仍保留，可用当前修改重试保存，或放弃本地修改并载入。";
  }
  return detail;
}

export function previewOutcomeText(provider: string, kind: string, reason: string | null) {
  if (kind === "PRESENT") return "命中";
  const api = provider === "openapi";
  if (kind === "MISSING" || reason === "NO_ROW") {
    return api ? "接口没有返回这条记录" : "数据库中没有这条记录";
  }
  if (kind === "NULL") return api ? "接口返回空值" : "数据库返回空值";
  return previewFailureText(provider, reason);
}

export function previewFailureText(provider: string, reason: string | null) {
  const api = provider === "openapi";
  if (reason === "SOURCE_UNAVAILABLE" || reason === "PROVIDER_NOT_CONFIGURED" || reason === "BINDING_NOT_RESOLVED") {
    return api ? "接口无法连接，可检查来源后重试" : "数据库连接失败，可检查来源后重试";
  }
  if (reason === "SOURCE_TIMEOUT") return api ? "接口读取超时，可稍后重试" : "数据库读取超时，可稍后重试";
  if (reason === "IDENTITY_MISMATCH") {
    return api ? "接口返回的身份与请求不一致" : "数据库返回的身份与请求不一致";
  }
  if (reason === "SPEC_UNAVAILABLE" || reason === "HEALTH_CHECK_FAILED" || reason === "PROVIDER_ERROR") {
    return `接口读取失败${reason ? `：${reason}` : ""}，可修改后重试`;
  }
  const prefix = api ? "接口读取失败" : "数据库读取失败";
  return `${prefix}${reason ? `：${reason}` : ""}，可修改后重试`;
}

export function validationNotice(provider: string, status: string, reason: string | null, unsaved: boolean) {
  const checked = unsaved ? "检查结果基于已保存配置，当前修改尚未保存。" : "";
  if (status === "VALID") return unsaved ? checked : "连接可用";
  if (status === "UNAVAILABLE") {
    const failure = provider === "openapi" ? "接口无法连接" : "数据库无法连接";
    return `${failure}${reason ? `：${reason}` : ""}。${checked}`.trim();
  }
  if (status === "INVALID") {
    const failure = provider === "openapi" ? "接口配置无效" : "数据库配置无效";
    return `${failure}${reason ? `：${reason}` : ""}。${checked}`.trim();
  }
  return checked || "待验证";
}

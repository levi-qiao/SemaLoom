export function namespaceLabel(id: string) {
  if (id === "procurement") return "采购";
  if (id === "tax") return "税务";
  return id;
}

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
  if (!saved) return "先保存草稿再试读。";
  return `试读当前草稿 r${revision}，不是已发布结果。`;
}

export function publishedExecutionHint() {
  return "试读看草稿；问答使用已发布版本。";
}

export function draftSaveLabel() {
  return "草稿保存";
}

export function digestHelp() {
  return "candidateDigest 是当前草稿规范化后的内容摘要；revision 是草稿保存次数。校验和批准都绑定这两个值以及当时的来源配置。保存草稿或改来源后，旧校验/批准立即失效。公共查询只使用环境激活后的 activeDigest，草稿保存不会让版本生效。";
}

export function gateErrorMessage(detail: string, status?: number) {
  if (detail === "INDEPENDENT_REVIEW_REQUIRED") {
    return "作者不能批准自己的候选（INDEPENDENT_REVIEW_REQUIRED）。请切换到其他审核人。";
  }
  if (detail === "VALIDATION_REQUIRED") {
    return "当前校验已过期或尚未通过（VALIDATION_REQUIRED）。草稿或来源变化后必须重新校验。";
  }
  if (detail === "APPROVAL_REQUIRED") {
    return "需要独立审核人批准当前这次校验（APPROVAL_REQUIRED）。";
  }
  if (detail === "ENVIRONMENT_REVISION_CONFLICT") {
    return "环境指针已变化（ENVIRONMENT_REVISION_CONFLICT）。请重新载入后再发布。";
  }
  if (status === 401 || detail === "UNAUTHENTICATED" || detail === "SESSION_EXPIRED" || detail === "SESSION_REQUIRED") {
    return `会话已失效（${detail}）。请重新选择本地身份。`;
  }
  if (status === 403 || detail === "FORBIDDEN") {
    return "当前身份没有这项权限。服务端已拒绝；隐藏按钮不能代替后端检查。";
  }
  if (status === 409 || detail === "REVISION_CONFLICT") {
    return "保存冲突。本地修改仍保留，可用当前修改重试保存，或放弃本地修改并载入。";
  }
  return detail;
}

export function validationStatusLabel(status: "none" | "VALID" | "INVALID" | "stale") {
  if (status === "VALID") return "通过";
  if (status === "INVALID") return "失败";
  if (status === "stale") return "过期";
  return "未验证";
}

export function publishStatusLabel(status: "draft" | "review" | "approved" | "active") {
  if (status === "active") return "已发布";
  if (status === "approved") return "已批准";
  if (status === "review") return "待审核";
  return "草稿";
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

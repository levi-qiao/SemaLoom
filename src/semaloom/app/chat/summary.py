"""Population narratives from engine values, not model arithmetic."""

# ruff: noqa: RUF001 -- Chinese UI prose uses Chinese punctuation.

from __future__ import annotations

from typing import Any

from semaloom.core.bundle import CompiledBundle
from semaloom.core.semantic_query import FilterAtom, FilterGroup, QueryResult, SemanticQuery

OPERATIONS = {
    "mean": "平均值",
    "sum": "合计",
    "min": "最小值",
    "max": "最大值",
    "count": "有效观测数量",
}
COMPARISONS = {
    "shareOfTotal": "占集合总额比例",
    "percentAboveMean": "相对集合均值增幅",
    "outperforms": "严格优于同行比例",
}


def _filter_description(node: FilterAtom | FilterGroup | None) -> str:
    if node is None:
        return "无额外筛选"
    if isinstance(node, FilterAtom):
        value = node.value.value
        rendered = "、".join(str(v) for v in value) if isinstance(value, tuple) else str(value)
        return f"{node.field} {node.op} {rendered}"
    return "(" + (f" {node.kind} ").join(_filter_description(arg) for arg in node.args) + ")"


def semantic_summary(
    bundle: CompiledBundle,
    query: SemanticQuery,
    result: QueryResult,
    assumptions: list[dict[str, str]] | None = None,
    confidence: dict[str, Any] | None = None,
) -> str:
    labels = {metric.id: metric.label or metric.id for metric in bundle.metrics}
    rows: list[str] = []
    headline = _headline(labels, result)
    if headline:
        rows.append(f"### 📊 计算结论\n\n**{headline}**")

    breakdown_values = [v for v in result.values if v.get("grain")]
    if breakdown_values:
        breakdown_rows = []
        for value in breakdown_values:
            grain = "；".join(
                (
                    f"{key} = {value.get('labels', {}).get(key)}（{item}）"
                    if value.get("labels", {}).get(key)
                    else f"{key} = {item}"
                )
                for key, item in value.get("grain", {}).items()
            )
            operation = OPERATIONS[
                {"SUM": "sum", "AVG": "mean", "MIN": "min", "MAX": "max", "COUNT": "count"}[
                    value["aggregation"]
                ]
            ]
            display_value = value["value"] if value["value"] is not None else "未知"
            metric_label = labels.get(value["metric"], value["metric"])
            grain_suffix = f"（{grain}）" if grain else ""
            breakdown_rows.append(
                f"- {metric_label}{grain_suffix}，{operation}：`{display_value} {value['unit']}`。"
            )
        if breakdown_rows:
            rows.append("#### 分组明细\n\n" + "\n".join(breakdown_rows))
    elif not headline:
        for value in result.values:
            operation = OPERATIONS[
                {"SUM": "sum", "AVG": "mean", "MIN": "min", "MAX": "max", "COUNT": "count"}[
                    value["aggregation"]
                ]
            ]
            display_value = value["value"] if value["value"] is not None else "未知"
            metric_label = labels.get(value["metric"], value["metric"])
            rows.append(f"{metric_label}，{operation}：{display_value} {value['unit']}。")

    comparison = result.scope.get("comparison")
    if comparison:
        if comparison.get("value") is None:
            rows.append("比较无法确定：" + str(comparison.get("reason")) + "。")
        else:
            rows.append(
                f"**比较分析**：{COMPARISONS[comparison['operation']]} `{comparison['value']}%`"
                f"（分子 {comparison['numerator']}，分母 {comparison['denominator']}）。"
            )
            if query.comparison and query.comparison.op == "STRICT_PEER":
                rows.append(
                    "按越小越好比较。"
                    if query.comparison.direction == "lower"
                    else "按越大越好比较。"
                )

    scope_lines = ["• 筛选范围：" + _filter_description(query.filters) + "。"]
    scopes = result.scope.get("metrics", {})
    for ref in query.metrics:
        scope = scopes.get(ref.id, result.scope)
        scope_lines.append(
            f"• {labels[ref.id]}：范围内 {scope.get('populationCount')} 个对象，"
            f"有效 {scope.get('observedCount')} 个，缺失 {scope.get('missingCount')} 个。"
        )
        if scope.get("reason"):
            scope_lines.append("无法确定数值：" + scope["reason"] + "。缺失不当零。")
    scope_lines.append(
        "• 缺失处理："
        + ("按用户选择排除缺失。" if query.missing_policy == "exclude" else "存在缺失则不计算。")
    )
    if assumptions:
        scope_lines.append(
            "• 系统默认：" + "；".join(_assumption_line(item) for item in assumptions) + "。"
        )
    rows.append("#### 📐 口径与范围说明\n\n" + "\n".join(scope_lines))

    if confidence:
        rows.append(
            f"置信度：{confidence['label']}（{confidence['score']}）。"
            + "规则只用于评分，不阻止回答。"
        )
    rows.append("结果限于当前授权、筛选范围和来源快照；不自动代表范围外事实或业务认可。")
    return "\n\n".join(rows)


def _headline(labels: dict[str, str], result: QueryResult) -> str | None:
    totals = [item for item in result.values if not item.get("grain")]
    if len(totals) != 1 or totals[0]["value"] is None:
        return None
    value = totals[0]
    operation = OPERATIONS[
        {"SUM": "sum", "AVG": "mean", "MIN": "min", "MAX": "max", "COUNT": "count"}[
            value["aggregation"]
        ]
    ]
    name = labels.get(value["metric"], value["metric"])
    return f"{name}{operation} {value['value']} {value['unit']}。"


def _assumption_line(item: dict[str, str]) -> str:
    if item["slot"] == "year":
        return f"年份未指定，按来源最新年度 {item['id']}"
    if item["slot"] == "aggregation":
        return "未指定统计方式，按金额/数量可加性取合计"
    if item["slot"] == "grain":
        return "未要求明细，按总体回答"
    return item.get("reason") or item["slot"]


def evidence_summary(evidence: list[dict[str, Any]]) -> str:
    """Only engine facts enter definitive prose; free model prose cannot assert truth."""
    import json

    sections: list[str] = []

    # 1. Claims / Rules checks
    claims_rows: list[str] = []
    for entry in evidence:
        result = entry["result"]
        for claim_result in [result, *result.get("checks", [])]:
            claim = claim_result.get("claim")
            if claim:
                truth = claim.get("truth", "UNKNOWN")
                claim_id = claim.get("claimId")
                status_icon = "✅" if truth == "TRUE" else "❌" if truth == "FALSE" else "⚠️"
                status_desc = (
                    "规则校验通过"
                    if truth == "TRUE"
                    else "规则校验存在差异/未通过"
                    if truth == "FALSE"
                    else "规则状态未知"
                )
                reason_codes = claim.get("reasonCodes", [])
                reasons_str = (
                    "；".join(str(r) for r in reason_codes) if reason_codes else "无异常原因码"
                )
                claims_rows.append(
                    f"- {status_icon} **{status_desc}**（`{claim_id}`：**{truth}**）\n"
                    f"  - 核验说明：{reasons_str}"
                )
            elif claim_result.get("error"):
                claims_rows.append(
                    f"- ⚠️ **规则未完成**（`{claim_result.get('claimId', '未知')}`）："
                    f"{claim_result['error']}。不能判断为通过。"
                )
    if claims_rows:
        sections.append("### ⚖️ 业务规则与命题核验\n\n" + "\n".join(claims_rows))

    # 2. Observations
    obs_rows: list[str] = []
    for entry in evidence:
        result = entry["result"]
        for observation in result.get("observations", []):
            observed = observation.get("value") if observation.get("kind") == "PRESENT" else "未知"
            if observation.get("valueType") == "OBJECT":
                observed = "属性见证据表"
            elif isinstance(observed, str) and observed.startswith("{"):
                try:
                    parsed = json.loads(observed)
                    observed = ", ".join(f"{k}: {v}" for k, v in parsed.items())
                except Exception:
                    pass
            target = observation.get("target")
            unit = f" {observation.get('unit')}" if observation.get("unit") else ""
            kind = observation.get("kind", "")
            reason = observation.get("reason") or "来源已观测"
            obs_rows.append(f"- **{target}**：`{observed}{unit}` （状态：`{kind}` · {reason}）")
    if obs_rows:
        sections.append("### 🔍 事实观测与指标数据\n\n" + "\n".join(obs_rows))

    # 3. Objects
    obj_sections: list[str] = []
    seen_object_identities: set[tuple[str, str]] = set()
    for entry in evidence:
        result = entry["result"]
        if "objects" in result:
            objs = result["objects"]
            obj_type = result.get("objectType", "业务对象")
            new_objs = []
            for obj in objs:
                ident_key = (obj_type, json.dumps(obj.get("identity", {}), sort_keys=True))
                if ident_key not in seen_object_identities:
                    seen_object_identities.add(ident_key)
                    new_objs.append(obj)
            if not new_objs:
                continue
            limit_hint = "还有未展示记录" if result.get("hasMore") else "全量已授权记录"
            obj_lines = [f"### 📋 {obj_type}（检索到 {len(new_objs)} 项记录 · {limit_hint}）\n"]
            for obj in new_objs[:10]:
                ident_str = ", ".join(f"{k}={v}" for k, v in obj.get("identity", {}).items())
                props = obj.get("properties", {})
                props_display = [
                    f"**{k}**: `{v}`"
                    for k, v in props.items()
                    if k not in obj.get("identity", {}) and v is not None
                ]
                props_text = " · ".join(props_display) if props_display else "无额外属性"
                obj_lines.append(f"- 🔹 **`{ident_str}`** — {props_text}")
            obj_sections.append("\n".join(obj_lines))
    if obj_sections:
        sections.extend(obj_sections)

    if not sections:
        raise ValueError("FACTUAL_EVIDENCE_REQUIRED")

    sections.append(
        "> ℹ️ **口径与审计说明**：以上结论来自系统已发布的不可变语义模型、来源观测与已审核规则引擎；"
        "UNKNOWN 不等于 FALSE，规则成立不自动代表业务合规。"
    )
    return "\n\n".join(sections)

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
    "periodOverPeriod": "较上年同期",
}

CAPABILITY_MESSAGES: dict[str, str] = {
    "LINK_ANALYSIS_UNSUPPORTED": (
        "当前集合分析不能沿该路径做跨表 JOIN。"
        "已声明、基数为 ONE、且同一 PostgreSQL 来源的关系，可用于按关联对象属性分组或筛选；"
        "一对多、跨数据源、多跳或未声明的路径仍不支持。"
        "请改用已声明的一对一关系字段，或先用 find_objects / semantic_query 按业务键分步查询。"
    ),
    "MULTI_METRIC_ORDER_COMPARISON_UNSUPPORTED": (
        "当前不支持多个指标的联合排序或联合比较。请一次只对一个指标做排序或比较，或拆成多个问题。"
    ),
    "TIME_GRAIN_UNSUPPORTED": (
        "当前不支持该时间粒度分组。请改用已声明的年度或日期字段，或去掉时间分组。"
    ),
    "CROSS_SOURCE_SQL": (
        "当前不能把该请求编译成跨数据源集合 SQL。"
        "已声明的一对一 PostgreSQL 关系会由引擎按业务键分批对齐；"
        "非 PostgreSQL 目标、多指标跨源或一对多仍不支持。"
    ),
    "BUDGET_EXCEEDED": ("跨源关联的键数量超过本轮预算。请缩小筛选范围后再统计。"),
    "OPERATOR_NOT_SUPPORTED": (
        "当前引擎不支持该分析算子或请求形状。请缩小范围或改用已支持的聚合与筛选。"
    ),
    "ADDITIVITY_VIOLATION": (
        "该测量按可加性不能这样汇总。"
        "库存和余额（SEMI）只在单一年度或按年分组时允许合计，不能把多年余额加总；"
        "比率（NONE）不能合计或平均，可问有效数量、最小值或最大值。"
        "流量类金额（收入、利润）可以合计或平均。"
    ),
}


def capability_message(capability: str | None) -> str:
    """Engine-owned Chinese prose for UNSUPPORTED analysis capabilities."""
    code = (capability or "OPERATOR_NOT_SUPPORTED").strip()
    return CAPABILITY_MESSAGES.get(
        code,
        f"当前不支持该分析能力（{code}）。请改用同表集合统计、对象点查或已定义规则。",
    )


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
        rows.append(f"### 计算结论\n\n**{headline}**")

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
            op_label = COMPARISONS.get(comparison["operation"], comparison["operation"])
            rows.append(
                f"**比较分析**：{op_label} `{comparison['value']}%`"
                f"（分子 {comparison['numerator']}，分母 {comparison['denominator']}）。"
            )
            if comparison.get("currentYear") and comparison.get("priorYear"):
                rows.append(
                    f"本期 {comparison['currentYear']} 年 `{comparison.get('currentValue')}`，"
                    f"上年 {comparison['priorYear']} 年 `{comparison.get('priorValue')}`。"
                )
            if query.comparison and query.comparison.op == "STRICT_PEER":
                rows.append(
                    "按越小越好比较。"
                    if query.comparison.direction == "lower"
                    else "按越大越好比较。"
                )

    scope_lines = ["- 筛选范围：" + _filter_description(query.filters) + "。"]
    scopes = result.scope.get("metrics", {})
    for ref in query.metrics:
        scope = scopes.get(ref.id, result.scope)
        scope_lines.append(
            f"- {labels[ref.id]}：范围内 {scope.get('populationCount')} 个对象，"
            f"有效 {scope.get('observedCount')} 个，缺失 {scope.get('missingCount')} 个。"
        )
        if scope.get("reason"):
            scope_lines.append("无法确定数值：" + scope["reason"] + "。缺失不当零。")
    scope_lines.append(
        "- 缺失处理："
        + ("按用户选择排除缺失。" if query.missing_policy == "exclude" else "存在缺失则不计算。")
    )
    if assumptions:
        scope_lines.append(
            "- 系统默认：" + "；".join(_assumption_line(item) for item in assumptions) + "。"
        )
    rows.append("#### 口径与范围说明\n\n" + "\n".join(scope_lines))

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


def evidence_summary(evidence: list[dict[str, Any]], bundle: CompiledBundle | None = None) -> str:
    """Only engine facts enter definitive prose; free model prose cannot assert truth."""
    import json

    obj_labels: dict[str, str] = {}
    prop_labels: dict[tuple[str, str], str] = {}
    prop_units: dict[tuple[str, str], str] = {}
    val_labels: dict[tuple[str, str, str], str] = {}
    rule_labels: dict[str, str] = {}
    if bundle is not None:
        for obj_type in bundle.object_types:
            obj_labels[obj_type.id] = obj_type.label or obj_type.id
            for prop in obj_type.properties:
                prop_labels[(obj_type.id, prop.id)] = prop.label or prop.id
                if prop.unit:
                    prop_units[(obj_type.id, prop.id)] = prop.unit
                for val in prop.values:
                    val_labels[(obj_type.id, prop.id, str(val.id))] = val.label or val.id
        for rule in bundle.rules:
            rule_labels[rule.id] = rule.label or rule.id

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
                claim_name = rule_labels.get(claim_id, claim_id)
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
                name_suffix = f" · {claim_name}" if claim_name != claim_id else ""
                claims_rows.append(
                    f"- {status_icon} **{status_desc}**（`{claim_id}`{name_suffix}：**{truth}**）\n"
                    f"  - 核验说明：{reasons_str}"
                )
            elif claim_result.get("error"):
                claim_id = claim_result.get("claimId", "未知")
                claim_name = rule_labels.get(claim_id, claim_id)
                name_suffix = f" · {claim_name}" if claim_name != claim_id else ""
                err_code = claim_result["error"]
                if err_code == "NO_APPLICABLE_POLICY":
                    req_dims = claim_result.get("requiredDimensions") or []
                    sample_dims = claim_result.get("sampleDimensions") or {}
                    if req_dims:
                        dims_str = "、".join(req_dims)
                        sample_str = (
                            f"（例如 {', '.join(f'{k}={v}' for k, v in sample_dims.items())}）"
                            if sample_dims
                            else ""
                        )
                        msg = (
                            f"未匹配到适用政策（NO_APPLICABLE_POLICY：该规则需指定适用维度："
                            f"{dims_str}{sample_str}，或未覆盖请求期间）"
                        )
                    else:
                        msg = (
                            "未匹配到适用政策（NO_APPLICABLE_POLICY："
                            "未覆盖请求期间或未满足政策维度）"
                        )
                else:
                    msg = f"{err_code}"
                claims_rows.append(
                    f"- ⚠️ **规则未完成**（`{claim_id}`{name_suffix}）：{msg}。不能判断为通过。"
                )
    if claims_rows:
        sections.append("#### 业务规则与命题核验\n\n" + "\n".join(claims_rows))

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
                    observed = "，".join(f"{k}: {v}" for k, v in parsed.items())
                except Exception:
                    pass
            target = observation.get("target")
            unit = f" {observation.get('unit')}" if observation.get("unit") else ""
            if observation.get("kind") == "PRESENT":
                obs_rows.append(f"- **{target}**：`{observed}{unit}`")
            else:
                reason = observation.get("reason") or "未获取到观测值"
                obs_rows.append(f"- **{target}**：`{observed}`（{reason}）")
    if obs_rows:
        sections.append("#### 事实指标观测\n\n" + "\n".join(obs_rows))

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
            obj_label = obj_labels.get(obj_type, obj_type)
            count_suffix = (
                f"（共 {len(new_objs)} 项）"
                if not result.get("hasMore")
                else f"（前 {len(new_objs)} 项，尚有更多）"
            )
            obj_lines = [f"#### {obj_label}{count_suffix}\n"]
            for obj in new_objs[:10]:
                ident_dict = obj.get("identity", {})
                props_dict = obj.get("properties", {})
                ident_parts = [
                    f"{prop_labels.get((obj_type, k), k)} `{v}`" for k, v in ident_dict.items()
                ]
                primary_ident = "，".join(ident_parts)
                props_display = []
                for k, v in props_dict.items():
                    if k in ident_dict or v is None:
                        continue
                    k_label = prop_labels.get((obj_type, k), k)
                    v_raw = str(v)
                    v_label = val_labels.get((obj_type, k, v_raw), v_raw)
                    unit = f" {prop_units[(obj_type, k)]}" if (obj_type, k) in prop_units else ""
                    if unit and "." in v_label:
                        parts = v_label.split(".", 1)
                        trimmed = parts[1].rstrip("0")
                        v_label = parts[0] if not trimmed else f"{parts[0]}.{trimmed}"
                    if v_label != v_raw:
                        props_display.append(f"{k_label}：{v_label}")
                    else:
                        props_display.append(f"{k_label}：{v_label}{unit}")
                if props_display:
                    obj_lines.append(f"- **{primary_ident}** — {'；'.join(props_display)}")
                else:
                    obj_lines.append(f"- **{primary_ident}**")
            obj_sections.append("\n".join(obj_lines))
    if obj_sections:
        sections.extend(obj_sections)

    if not sections:
        raise ValueError("FACTUAL_EVIDENCE_REQUIRED")

    if claims_rows:
        sections.append(
            "> ℹ️ **说明**：规则判定基于系统已发布的不变语义模型与来源观测，"
            "数据不足不等于判断不成立。"
        )
    return "\n\n".join(sections)

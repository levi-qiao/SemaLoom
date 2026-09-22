"""Population narratives from engine values, not model arithmetic."""

# ruff: noqa: RUF001 -- Chinese UI prose uses Chinese punctuation.

from __future__ import annotations

from typing import Any

from semaloom.app.chat.formatting import natural_number
from semaloom.app.chat.i18n import semantic_label
from semaloom.core.bundle import CompiledBundle
from semaloom.core.semantic_query import FilterAtom, FilterGroup, QueryResult, SemanticQuery
from semaloom.runtime.vocabulary import display_label, find_property

OPERATIONS = {
    "mean": "平均值",
    "sum": "合计",
    "min": "最小值",
    "max": "最大值",
    "count": "有效观测数量",
}
REASON_TEXT = {
    "EMPTY_POPULATION": "当前筛选范围没有匹配记录",
    "NO_OBSERVED_VALUES": "当前范围没有可用于计算的有效观测",
    "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION": "当前范围存在缺失值，需要明确是否排除后再计算",
    "PRIOR_PERIOD_MISSING": "没有可比较的上一期间观测",
    "SUBJECT_VALUE_MISSING": "当前期间缺少可比较的有效观测",
    "ZERO_DENOMINATOR": "比较基准为零，无法计算比例",
    "NON_POSITIVE_MEAN": "当前范围的比较基准不是正数",
    "NEGATIVE_VALUES_NOT_A_SHARE": "当前范围含负值，不能解释为占比",
    "INCOMPLETE_METRIC_SET": "所选指标中至少一项数据不完整",
}
REASON_TEXT_EN = {
    "EMPTY_POPULATION": "No records match the selected scope",
    "NO_OBSERVED_VALUES": "The selected scope has no usable observations",
    "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION": (
        "The selected scope contains missing values; confirm whether to exclude them"
    ),
    "PRIOR_PERIOD_MISSING": "No prior observed period is available for comparison",
    "SUBJECT_VALUE_MISSING": "The current period has no usable observation",
    "ZERO_DENOMINATOR": "The comparison baseline is zero",
    "NON_POSITIVE_MEAN": "The comparison baseline is not positive",
    "NEGATIVE_VALUES_NOT_A_SHARE": "Negative values cannot be presented as a share",
    "INCOMPLETE_METRIC_SET": "At least one selected metric is incomplete",
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
        "库存和余额（SEMI）只有在全部范围属性被单值约束或进入分组时才允许合计；"
        "比率（NONE）不能合计或平均，可问有效数量、最小值或最大值。"
        "流量类金额（收入、利润）可以合计或平均。"
    ),
    "INVALID_PROPERTIES": (
        "请求中的筛选或分组字段不是当前本体声明的业务属性。"
        "请使用 ObjectType.property 形式的属性标识；关系 ID 只能表示关联，不能直接分组。"
    ),
    "GROUP_BY_REQUIRES_PROPERTY_NOT_LINK_ID": (
        "分组需要使用关联对象的业务属性，例如 ObjectType.property，不能把关系 ID 当作字段。"
    ),
    "INVALID_GROUP_BY_FIELD": (
        "分组字段不是当前本体声明的业务属性，请改用目录中的 ObjectType.property。"
    ),
    "DUPLICATE_OR_MISSING_STATISTICAL_UNIT": (
        "当前范围里同一对象有多条记录，需要再选定口径或期间后才能计算。"
        "请补充要看的口径、期间或对象，不要把多条记录混成一个数。"
    ),
}

CAPABILITY_MESSAGES_EN: dict[str, str] = {
    "LINK_ANALYSIS_UNSUPPORTED": (
        "This collection analysis cannot follow that relationship. Use a declared "
        "one-to-one collection link or query the objects in separate steps."
    ),
    "MULTI_METRIC_ORDER_COMPARISON_UNSUPPORTED": (
        "Combined ordering or comparison across multiple metrics is not supported. "
        "Compare one metric at a time."
    ),
    "TIME_GRAIN_UNSUPPORTED": (
        "This time grain is not supported. Use a declared ordered-period property, "
        "or remove the time grouping."
    ),
    "CROSS_SOURCE_SQL": (
        "This collection request cannot be compiled across the selected sources. "
        "Narrow the request to a supported declared relationship."
    ),
    "BUDGET_EXCEEDED": (
        "The cross-source relationship exceeds this turn's key budget. "
        "Narrow the filters and try again."
    ),
    "OPERATOR_NOT_SUPPORTED": (
        "The engine does not support this analysis shape. "
        "Use a supported aggregation and filter combination."
    ),
    "ADDITIVITY_VIOLATION": (
        "This measurement cannot be aggregated in the requested way. "
        "Use an operation allowed by its declared additivity."
    ),
    "INVALID_PROPERTIES": (
        "A filter or group is not an ontology-declared business property. "
        "Use an ObjectType.property identifier."
    ),
    "GROUP_BY_REQUIRES_PROPERTY_NOT_LINK_ID": (
        "Grouping requires a business property on the linked object; a Link ID is not a field."
    ),
    "INVALID_GROUP_BY_FIELD": "The group field is not an ontology-declared business property.",
    "DUPLICATE_OR_MISSING_STATISTICAL_UNIT": (
        "The current scope has more than one record for the same object. "
        "Choose a perspective, period, or object before calculating."
    ),
}


def capability_message(capability: str | None, locale: str = "zh-CN") -> str:
    """Engine-owned localized prose for unsupported analysis capabilities."""
    code = (capability or "OPERATOR_NOT_SUPPORTED").strip()
    if locale.startswith("en"):
        return CAPABILITY_MESSAGES_EN.get(
            code,
            "This question still needs a business condition. "
            "Choose a metric, period, or perspective, or add a short clarification.",
        )
    return CAPABILITY_MESSAGES.get(
        code,
        "这个问题还需要补充业务条件才能计算。请选择指标、期间或口径，或用一句话说明要看哪一种。",
    )


def _filter_description(
    node: FilterAtom | FilterGroup | None,
    labels: dict[str, str],
    bundle: CompiledBundle | None = None,
) -> str:
    if node is None:
        return "当前可查询范围"
    if isinstance(node, FilterAtom):
        value = node.value.value
        prop = find_property(bundle, node.field) if bundle is not None else None
        if isinstance(value, tuple):
            rendered = "、".join(display_label(prop, item) for item in value)
        else:
            rendered = display_label(prop, value)
        operator = {
            "EQ": "为",
            "NE": "不为",
            "IN": "为以下任一值：",
            "GT": "大于",
            "GE": "不小于",
            "LT": "小于",
            "LE": "不大于",
        }.get(node.op, node.op)
        return f"{labels.get(node.field, node.field)}{operator}{rendered}"
    parts = [_filter_description(arg, labels, bundle) for arg in node.args]
    if node.kind == "NOT":
        return "不满足：" + "；".join(parts)
    return ("；" if node.kind == "AND" else "，或").join(parts)


def semantic_summary(
    bundle: CompiledBundle,
    query: SemanticQuery,
    result: QueryResult,
    assumptions: list[dict[str, str]] | None = None,
    locale: str = "zh-CN",
) -> str:
    if locale.startswith("en"):
        return _semantic_summary_en(bundle, query, result, assumptions or [])
    labels = {metric.id: metric.label or metric.id for metric in bundle.metrics}
    owners = {
        metric.object_type
        for metric in bundle.metrics
        if metric.id in {ref.id for ref in query.metrics}
    }
    for obj in bundle.object_types:
        for prop in obj.properties:
            if obj.id in owners:
                labels[prop.id] = prop.label or prop.id
            labels[f"{obj.id}.{prop.id}"] = prop.label or prop.id
    for group in query.group_by:
        if "." not in group.id:
            continue
        owner_id, prop_id = group.id.rsplit(".", 1)
        owner = next((item for item in bundle.object_types if item.id == owner_id), None)
        group_prop = (
            next((item for item in owner.properties if item.id == prop_id), None)
            if owner is not None
            else None
        )
        if owner and group_prop and group_prop.label in {"名称", "编号"} and owner.label:
            labels[prop_id] = f"{owner.label}{group_prop.label}"
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
                    f"{labels.get(key, key)}：{value.get('labels', {}).get(key)}"
                    if value.get("labels", {}).get(key)
                    else f"{labels.get(key, key)}：{item}"
                )
                for key, item in value.get("grain", {}).items()
            )
            operation = OPERATIONS[
                {"SUM": "sum", "AVG": "mean", "MIN": "min", "MAX": "max", "COUNT": "count"}[
                    value["aggregation"]
                ]
            ]
            display_value = natural_number(value["value"]) if value["value"] is not None else "暂缺"
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
            display_value = natural_number(value["value"]) if value["value"] is not None else "暂缺"
            metric_label = labels.get(value["metric"], value["metric"])
            rows.append(f"{metric_label}，{operation}：{display_value} {value['unit']}。")

    calculation = result.scope.get("calculation")
    if isinstance(calculation, dict) and calculation:
        if calculation.get("value") is None:
            rows.append("计算无法确定：" + _reason_text(calculation.get("reason"), "zh-CN") + "。")
        else:
            rows.append(f"计算结果：{natural_number(calculation['value'])}。")
            if calculation.get("numerator") is not None:
                rows.append(
                    f"分子 `{calculation['numerator']}`，分母 `{calculation.get('denominator')}`。"
                )
            if calculation.get("priorPeriod") is not None:
                rows.append(f"上一观测期间 {calculation.get('priorPeriod')}。")
            if calculation.get("peerRelation") == "GT":
                rows.append("按越小越好比较。")
            elif calculation.get("peerRelation") == "LT":
                rows.append("按越大越好比较。")

    scope_lines = ["- 筛选范围：" + _filter_description(query.filters, labels, bundle) + "。"]
    scopes = result.scope.get("metrics", {})
    for ref in query.metrics:
        scope = scopes.get(ref.id, result.scope)
        scope_lines.append(
            f"- {labels[ref.id]}：范围内 {scope.get('populationCount')} 个对象，"
            f"有效 {scope.get('observedCount')} 个，缺失 {scope.get('missingCount')} 个。"
        )
        if scope.get("reason"):
            scope_lines.append(
                "无法确定数值：" + _reason_text(scope["reason"], "zh-CN") + "。缺失不当零。"
            )
    scope_lines.append(
        "- 缺失处理："
        + ("按用户选择排除缺失。" if query.missing_policy == "exclude" else "存在缺失则不计算。")
    )
    if assumptions:
        scope_lines.append(
            "- 系统默认：" + "；".join(_assumption_line(item) for item in assumptions) + "。"
        )
    rows.append("#### 口径与范围说明\n\n" + "\n".join(scope_lines))

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
    return f"{name}{operation} {natural_number(value['value'])} {value['unit']}。"


def _reason_text(reason: Any, locale: str) -> str:
    code = str(reason or "")
    mapping = REASON_TEXT_EN if locale == "en" else REASON_TEXT
    return mapping.get(code, "当前数据不足以完成计算" if locale != "en" else "Insufficient data")


def _assumption_line(item: dict[str, str]) -> str:
    if item["slot"] == "aggregation":
        return "未指定统计方式，按金额/数量可加性取合计"
    if item["slot"] == "grain":
        return "未要求明细，按总体回答"
    return item.get("reason") or item["slot"]


def _semantic_summary_en(
    bundle: CompiledBundle,
    query: SemanticQuery,
    result: QueryResult,
    assumptions: list[dict[str, str]],
) -> str:
    labels = {metric.id: semantic_label("en", metric.label, metric.id) for metric in bundle.metrics}
    operation = {
        "SUM": "total",
        "AVG": "average",
        "MIN": "minimum",
        "MAX": "maximum",
        "COUNT": "observed count",
    }
    lines = ["### Result"]
    for value in result.values:
        shown = natural_number(value["value"]) if value["value"] is not None else "Unavailable"
        label = labels.get(value["metric"], value["metric"])
        grain = value.get("grain") or {}
        suffix = (
            " (" + ", ".join(f"{key}: {item}" for key, item in grain.items()) + ")" if grain else ""
        )
        lines.append(
            f"- **{label}{suffix}** — {operation.get(value['aggregation'], value['aggregation'])}: "
            f"{shown} {value['unit']}"
        )
    calculation = result.scope.get("calculation")
    if isinstance(calculation, dict) and calculation:
        if calculation.get("value") is None:
            lines.append(
                f"- Calculation unavailable: {_reason_text(calculation.get('reason'), 'en')}."
            )
        else:
            lines.append(f"- Calculation: {natural_number(calculation['value'])}.")
    scopes = result.scope.get("metrics", {})
    lines.extend(["", "#### Scope"])
    for ref in query.metrics:
        scope = scopes.get(ref.id, result.scope)
        lines.append(
            f"- {labels.get(ref.id, ref.id)}: {scope.get('populationCount')} in scope, "
            f"{scope.get('observedCount')} observed, {scope.get('missingCount')} missing."
        )
        if scope.get("reason"):
            lines.append(f"- Value unavailable: {_reason_text(scope.get('reason'), 'en')}.")
    lines.append(
        "- Missing values are excluded by explicit user choice."
        if query.missing_policy == "exclude"
        else "- Calculation stops when required values are missing."
    )
    if assumptions:
        lines.append(
            "- Defaults: "
            + "; ".join(str(item.get("reason") or item.get("slot")) for item in assumptions)
            + "."
        )
    return "\n".join(lines)


def _evidence_summary_en(evidence: list[dict[str, Any]], bundle: CompiledBundle | None) -> str:
    metric_labels = {
        item.id: item.label or item.id for item in (bundle.metrics if bundle is not None else [])
    }
    sections: list[str] = []
    for item in evidence:
        result = item.get("result") or {}
        values = result.get("values") or []
        if values:
            rows = []
            for value in values:
                shown = (
                    natural_number(value.get("value"))
                    if value.get("value") is not None
                    else "Unavailable"
                )
                label = metric_labels.get(
                    value.get("metric"), value.get("label") or value.get("metric") or "Metric"
                )
                rows.append(f"- **{label}**: {shown} {value.get('unit') or ''}".rstrip())
            sections.append("### Result\n\n" + "\n".join(rows))
        objects = result.get("objects") or []
        if objects:
            object_label = result.get("labels", {}).get(
                result.get("objectType"), "Business records"
            )
            sections.append(
                f"### {object_label}\n\n{len(objects)} authorized record(s) "
                "matched the current scope."
            )
        claims = [
            result.get("claim"),
            *(row.get("claim") for row in result.get("checks") or [] if isinstance(row, dict)),
        ]
        claim_rows = []
        for claim in claims:
            if isinstance(claim, dict):
                truth = {"TRUE": "True", "FALSE": "False", "UNKNOWN": "Undetermined"}.get(
                    str(claim.get("truth")), "Unavailable"
                )
                claim_rows.append(f"- **Rule evaluation**: {truth}")
        if claim_rows:
            sections.append("### Rules\n\n" + "\n".join(claim_rows))
    return "\n\n".join(sections) or "The authorized semantic operation completed."


def evidence_summary(
    evidence: list[dict[str, Any]],
    bundle: CompiledBundle | None = None,
    locale: str = "zh-CN",
) -> str:
    """Only engine facts enter definitive prose; free model prose cannot assert truth."""
    if locale.startswith("en"):
        return _evidence_summary_en(evidence, bundle)
    import json

    obj_labels: dict[str, str] = {}
    prop_labels: dict[tuple[str, str], str] = {}
    prop_units: dict[tuple[str, str], str] = {}
    identity_keys: dict[str, set[str]] = {}
    val_labels: dict[tuple[str, str, str], str] = {}
    rule_labels: dict[str, str] = {}
    metric_labels: dict[str, str] = {}
    if bundle is not None:
        for obj_type in bundle.object_types:
            obj_labels[obj_type.id] = obj_type.label or obj_type.id
            identity_keys[obj_type.id] = set(obj_type.identity_keys)
            for prop in obj_type.properties:
                prop_labels[(obj_type.id, prop.id)] = prop.label or prop.id
                if prop.unit:
                    prop_units[(obj_type.id, prop.id)] = prop.unit
                for val in prop.values:
                    val_labels[(obj_type.id, prop.id, str(val.id))] = val.label or val.id
        for link in bundle.links:
            identity_keys.setdefault(link.source, set()).update(
                pair.source for pair in link.identity
            )
        metric_labels = {metric.id: metric.label or metric.id for metric in bundle.metrics}
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
                status_desc = {
                    "TRUE": "成立",
                    "FALSE": "不成立",
                    "UNKNOWN": "现有数据不足以判断",
                }.get(truth, "尚未完成")
                claims_rows.append(f"- **{claim_name}：{status_desc}。**")
            elif claim_result.get("error"):
                claim_id = claim_result.get("claimId", "未知")
                claim_name = rule_labels.get(claim_id, claim_id)
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
                            f"未匹配到适用政策（该规则需指定适用维度："
                            f"{dims_str}{sample_str}，或未覆盖请求期间）"
                        )
                    else:
                        msg = "未匹配到适用政策（未覆盖请求期间或未满足政策维度）"
                else:
                    msg = "核验暂未完成，具体原因可在证据中查看"
                claims_rows.append(f"- **{claim_name}：规则未完成。**{msg}。不能判断为通过。")
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
            raw_target = observation.get("target")
            target = metric_labels.get(raw_target, obj_labels.get(raw_target, raw_target))
            unit = f" {observation.get('unit')}" if observation.get("unit") else ""
            if observation.get("unit"):
                observed = natural_number(observed)
            if observation.get("kind") == "PRESENT":
                obs_rows.append(f"- **{target}**：`{observed}{unit}`")
            else:
                reason = (
                    "来源暂不可用"
                    if observation.get("kind") == "UNAVAILABLE"
                    else "来源未提供所需数值"
                )
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
                props_display = []
                for k, v in props_dict.items():
                    k_label = prop_labels.get((obj_type, k), k)
                    if k in ident_dict or k in identity_keys.get(obj_type, set()) or v is None:
                        continue
                    v_raw = str(v).lower() if isinstance(v, bool) else str(v)
                    v_label = val_labels.get((obj_type, k, v_raw), v_raw)
                    unit = f" {prop_units[(obj_type, k)]}" if (obj_type, k) in prop_units else ""
                    if unit:
                        v_label = natural_number(v_label)
                    props_display.append(f"{k_label}：{v_label}{unit}")
                if props_display:
                    obj_lines.append(f"- {'；'.join(props_display)}")
            obj_sections.append("\n".join(obj_lines))
    if obj_sections:
        sections.extend(obj_sections)

    if not sections:
        raise ValueError("FACTUAL_EVIDENCE_REQUIRED")

    if claims_rows:
        sections.append("本次判断依据已发布规则和来源数据，数据不足不等于判断不成立。")
    return "\n\n".join(sections)

"""Deterministic browser projection; never send physical metadata to the model."""

# ruff: noqa: RUF001 -- Chinese UI prose uses Chinese punctuation.

from __future__ import annotations

from copy import deepcopy
from typing import Any

from semaloom.core.bundle import CompiledBundle
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.studio import mapping_summary

_MAX_METRICS = 8
_MAX_REPORTS = 4
_MAX_COLUMNS = 12
_MAX_ROWS = 50
_OPERATIONS = {
    "SUM": "合计",
    "AVG": "平均值",
    "MIN": "最小值",
    "MAX": "最大值",
    "COUNT": "有效数量",
    "shareOfTotal": "占总体比例",
    "percentAboveMean": "相对均值",
    "outperforms": "超过同类",
    "periodOverPeriod": "较上期",
}
_TRUTH = {"TRUE": "成立", "FALSE": "不成立", "UNKNOWN": "尚不确定"}


def project_browser_answer(answer: dict[str, Any], bundle: CompiledBundle) -> dict[str, Any]:
    """Enrich one authorized answer for the browser through a single app-layer seam."""

    result = deepcopy(answer)
    metric_ids = {m.id for m in bundle.metrics}
    labels = _document_labels(bundle)
    for evidence in result.get("evidence", []):
        d = evidence.get("result", {})
        mapping_ids = _mapping_ids(d)

        if isinstance(d, dict):
            supplied = d.get("labels")
            d["labels"] = _referenced_labels(
                d, labels, supplied if isinstance(supplied, dict) else {}
            )

        if isinstance(d, dict) and "definitions" in d and isinstance(d["definitions"], list):
            for doc in d["definitions"]:
                if isinstance(doc, dict):
                    _enrich_definition_sources(doc, bundle, metric_ids)
        elif isinstance(d, dict) and "id" in d and "kind" in d:
            _enrich_definition_sources(d, bundle, metric_ids)

        evidence["lineage"] = [
            mapping_summary(m, metric_ids) for m in bundle.mappings if m.id in mapping_ids
        ]
    presentation = _presentation(result.get("evidence", []), labels, result.get("query"), bundle)
    if presentation is not None:
        result["presentation"] = presentation
    return result


def _referenced_labels(
    value: Any, catalog: dict[str, str], supplied: dict[str, Any]
) -> dict[str, str]:
    referenced: set[str] = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, nested in item.items():
                if key in {"labels", "lineage", "mappingFields", "sources"}:
                    continue
                referenced.add(key)
                pending.append(nested)
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        elif isinstance(item, str):
            referenced.add(item)
    return {
        key: str(supplied.get(key) or catalog[key])
        for key in sorted(referenced)
        if supplied.get(key) or key in catalog
    }


def _presentation(
    evidence: list[dict[str, Any]],
    labels: dict[str, str],
    query: Any,
    bundle: CompiledBundle,
) -> dict[str, Any] | None:
    metrics: list[dict[str, str]] = []
    reports: list[dict[str, Any]] = []
    for entry in evidence:
        payload = entry.get("result")
        if not isinstance(payload, dict):
            continue
        supplied_labels = payload.get("labels")
        payload_labels = {
            **labels,
            **(supplied_labels if isinstance(supplied_labels, dict) else {}),
        }
        report = _report(entry, payload, payload_labels, query, bundle)
        if report is not None and len(reports) < _MAX_REPORTS:
            reports.append(report)
        for index, value in enumerate(payload.get("values") or []):
            if len(metrics) >= _MAX_METRICS or not isinstance(value, dict):
                break
            if report is not None and value.get("grain"):
                continue
            raw = value.get("value")
            if raw is None:
                continue
            raw_grain = value.get("grain")
            raw_grain_labels = value.get("labels")
            grain: dict[str, Any] = raw_grain if isinstance(raw_grain, dict) else {}
            grain_labels: dict[str, Any] = (
                raw_grain_labels if isinstance(raw_grain_labels, dict) else {}
            )
            grain_text = " · ".join(
                f"{grain_labels[key]}（{item}）" if grain_labels.get(key) else str(item)
                for key, item in grain.items()
            )
            operation = _OPERATIONS.get(str(value.get("aggregation")), "")
            metrics.append(
                {
                    "id": f"{entry.get('id', 'evidence')}:value:{index}",
                    "label": str(
                        payload_labels.get(value.get("metric"))
                        or value.get("label")
                        or value.get("metric")
                        or "引擎结果"
                    ),
                    "value": str(raw),
                    "displayValue": _natural_number(raw),
                    "unit": str(value.get("unit") or ""),
                    "meta": " · ".join(part for part in (operation, grain_text) if part),
                    "tone": "neutral",
                }
            )
        claims = [payload.get("claim")]
        claims.extend(
            check.get("claim") for check in payload.get("checks") or [] if isinstance(check, dict)
        )
        for index, claim in enumerate(claims):
            if len(metrics) >= _MAX_METRICS or not isinstance(claim, dict):
                continue
            truth = str(claim.get("truth") or "UNKNOWN")
            claim_id = str(claim.get("claimId") or "")
            metrics.append(
                {
                    "id": f"{entry.get('id', 'evidence')}:claim:{index}",
                    "label": str(payload_labels.get(claim_id) or claim.get("label") or "规则判断"),
                    "value": truth,
                    "displayValue": _TRUTH.get(truth, truth),
                    "unit": "",
                    "meta": claim_id,
                    "tone": "positive"
                    if truth == "TRUE"
                    else "danger"
                    if truth == "FALSE"
                    else "warning",
                }
            )
        scope = payload.get("scope")
        comparison = payload.get("comparison") or (
            scope.get("comparison") if isinstance(scope, dict) else None
        )
        if (
            len(metrics) < _MAX_METRICS
            and isinstance(comparison, dict)
            and comparison.get("value") is not None
        ):
            raw = comparison["value"]
            operation = str(comparison.get("operation") or "")
            denominator = comparison.get("denominator")
            metrics.append(
                {
                    "id": f"{entry.get('id', 'evidence')}:comparison",
                    "label": _OPERATIONS.get(operation, "比较结果"),
                    "value": str(raw),
                    "displayValue": _natural_number(raw),
                    "unit": str(comparison.get("unit") or ""),
                    "meta": (
                        f"分子 {comparison.get('numerator')} · 分母 {denominator}"
                        if denominator is not None
                        else ""
                    ),
                    "tone": "neutral",
                }
            )
    if not metrics and not reports:
        return None
    return {"version": "semaloom/presentation-v0.1", "metrics": metrics, "reports": reports}


def _report(
    entry: dict[str, Any],
    payload: dict[str, Any],
    labels: dict[str, str],
    query: Any,
    bundle: CompiledBundle,
) -> dict[str, Any] | None:
    values = [
        item
        for item in payload.get("values") or []
        if isinstance(item, dict)
        and item.get("value") is not None
        and isinstance(item.get("grain"), dict)
        and item["grain"]
    ]
    if len(values) < 2:
        return None
    group_items = query.get("groupBy") if isinstance(query, dict) else None
    requested_groups = [
        str(item.get("id"))
        for item in (group_items or [])
        if isinstance(item, dict) and item.get("id")
    ]
    grain_ids: list[str] = []
    available_grains = {str(key) for value in values for key in (value.get("grain") or {}).keys()}
    for requested in requested_groups:
        bare = requested.split(".")[-1]
        if bare in available_grains and bare not in grain_ids:
            grain_ids.append(bare)
    for value in values:
        for field in value.get("grain") or {}:
            if field not in grain_ids:
                grain_ids.append(str(field))
    metric_ids = list(
        dict.fromkeys(str(value.get("metric")) for value in values if value.get("metric"))
    )[:4]
    if not grain_ids or not metric_ids or len(grain_ids) + len(metric_ids) > _MAX_COLUMNS:
        return None

    columns: list[dict[str, Any]] = []
    for index, field in enumerate(grain_ids):
        prop = _property(bundle, field, requested_groups)
        columns.append(
            {
                "key": f"c{index}",
                "semanticId": field,
                "label": str(labels.get(field) or (prop.label if prop else None) or field),
                "role": "CATEGORY" if index == 0 else "DIMENSION",
                "valueType": prop.value_type if prop else None,
                "unit": prop.unit if prop else None,
            }
        )
    for metric_id in metric_ids:
        metric = next((item for item in bundle.metrics if item.id == metric_id), None)
        sample = next(value for value in values if str(value.get("metric")) == metric_id)
        columns.append(
            {
                "key": f"c{len(columns)}",
                "semanticId": metric_id,
                "label": str(
                    labels.get(metric_id) or (metric.label if metric else None) or metric_id
                ),
                "role": "MEASURE",
                "valueType": metric.value_type if metric else None,
                "unit": sample.get("unit") or (metric.unit if metric else None),
            }
        )
    grain_keys: dict[tuple[str, ...], dict[str, str]] = {}
    for value in values:
        grain = value["grain"]
        key = tuple(str(grain.get(field, "—")) for field in grain_ids)
        row = grain_keys.setdefault(key, {})
        supplied = value.get("labels")
        display_labels: dict[str, Any] = supplied if isinstance(supplied, dict) else {}
        for index, field in enumerate(grain_ids):
            raw = str(grain.get(field, "—"))
            shown = display_labels.get(field)
            row[f"c{index}"] = f"{shown}（{raw}）" if shown and str(shown) != raw else raw
        metric_id = str(value.get("metric") or "")
        if metric_id in metric_ids:
            row[f"c{len(grain_ids) + metric_ids.index(metric_id)}"] = _natural_number(
                value["value"]
            )
    rows = list(grain_keys.values())[:_MAX_ROWS]
    series = [
        {
            "key": column["key"],
            "label": column["label"],
            **({"unit": column["unit"]} if column["unit"] else {}),
        }
        for column in columns
        if column["role"] == "MEASURE"
    ]
    metric_names = [str(labels.get(item) or item) for item in metric_ids]
    if _is_time_query(group_items) and len(metric_names) == 1:
        title = f"{metric_names[0]}趋势"
    else:
        title = f"{metric_names[0]}分布" if len(metric_names) == 1 else "分析结果"
    preferred = "table" if len(grain_ids) > 1 else "line" if _is_time_query(group_items) else "bar"
    return {
        "id": f"{entry.get('id', 'evidence')}:report",
        "title": title,
        "description": "图形与表格使用同一组聚合结果；切换视图不会重新计算。",
        "columns": columns,
        "rows": rows,
        "categoryKey": columns[0]["key"],
        "series": series,
        "preferredView": preferred,
        "truncated": len(grain_keys) > _MAX_ROWS,
        "rowCount": len(grain_keys),
    }


def _is_time_query(group_items: Any) -> bool:
    return any(
        isinstance(item, dict) and item.get("timeGrain") in {"YEAR", "MONTH"}
        for item in (group_items or [])
    )


def _property(bundle: CompiledBundle, field: str, requested: list[str]) -> Any | None:
    qualified = next((item for item in requested if item.split(".")[-1] == field), field)
    if "." in qualified:
        owner, prop_id = qualified.rsplit(".", 1)
        obj = next((item for item in bundle.object_types if item.id == owner), None)
        if obj is not None:
            return next((item for item in obj.properties if item.id == prop_id), None)
    matches = [prop for obj in bundle.object_types for prop in obj.properties if prop.id == field]
    return matches[0] if len(matches) == 1 else None


def _natural_number(value: Any) -> str:
    raw = str(value)
    if "." not in raw:
        return raw
    try:
        whole, fractional = raw.split(".", 1)
    except ValueError:
        return raw
    if not whole.lstrip("-").isdigit() or not fractional.isdigit():
        return raw
    compact = f"{whole}.{fractional.rstrip('0')}".rstrip(".")
    return "0" if compact == "-0" else compact


def _document_labels(bundle: CompiledBundle) -> dict[str, str]:
    labels: dict[str, str] = {}
    for collection in (
        bundle.packs,
        bundle.object_types,
        bundle.metrics,
        bundle.links,
        bundle.rules,
        bundle.policies,
        bundle.actions,
        bundle.mappings,
        bundle.action_bindings,
    ):
        for item in collection:
            if item.label:
                labels[item.id] = item.label
    for obj in bundle.object_types:
        for prop in obj.properties:
            if prop.label:
                labels[prop.id] = prop.label
                labels[f"{obj.id}.{prop.id}"] = prop.label
    for rule in bundle.rules:
        if rule.claim and rule.label:
            labels[rule.claim] = rule.label
    for action in bundle.actions:
        for param in action.parameters:
            if param.label:
                labels[param.name] = param.label
    return labels


def _enrich_definition_sources(
    doc: dict[str, Any], bundle: CompiledBundle, metric_ids: set[str]
) -> None:
    doc_id = doc.get("id")
    if not doc_id:
        return
    kind = doc.get("kind")
    sources: list[dict[str, Any]] = []

    if kind == "Action":
        for b in bundle.action_bindings:
            if b.action == doc_id:
                path = str(b.physical.get("path") or "")
                method = str(b.physical.get("method") or "POST").upper()
                sources.append(
                    {
                        "type": "actionBinding",
                        "id": b.id,
                        "label": b.label or b.source_id,
                        "sourceId": b.source_id,
                        "provider": b.provider,
                        "resource": f"{method} {path}".strip() if path else method,
                        "operation": b.physical.get("operationId"),
                        "method": method,
                        "path": path,
                        "idempotent": b.idempotent,
                        "reconcilable": b.reconcilable,
                    }
                )
    elif kind in {"ObjectType", "Metric"}:
        for m in bundle.mappings:
            if m.target == doc_id or m.object_type == doc_id:
                sources.append(mapping_summary(m, metric_ids))
    elif kind == "Rule":
        rule_obj = next((r for r in bundle.rules if r.id == doc_id), None)
        if rule_obj:
            input_ids = {spec.metric or spec.object_type for spec in rule_obj.inputs}
            for m in bundle.mappings:
                if m.target in input_ids or m.object_type in input_ids:
                    sources.append(mapping_summary(m, metric_ids))

    if sources:
        doc["sources"] = sources


def visible_answer(answer: dict[str, Any], actor: RequestActor) -> dict[str, Any]:
    result = deepcopy(answer)
    if not set(actor.roles) & {"modeler", "model-viewer", "source-admin"}:
        result = without_physical_metadata(result)
    return result


def _mapping_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("mappingId"), str):
            found.add(value["mappingId"])
        for item in value.values():
            found.update(_mapping_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_mapping_ids(item))
    return found


def without_physical_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: without_physical_metadata(item)
            for key, item in value.items()
            if key not in {"lineage", "mappingFields", "sources"}
        }
    if isinstance(value, list):
        return [without_physical_metadata(item) for item in value]
    return value

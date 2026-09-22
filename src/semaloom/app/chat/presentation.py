"""Deterministic browser projection; never send physical metadata to the model."""

# ruff: noqa: RUF001 -- Chinese UI prose uses Chinese punctuation.

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel

from semaloom.app.chat.formatting import natural_number
from semaloom.app.chat.i18n import semantic_label
from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import EmbeddedProperty
from semaloom.core.wire import wire_config
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
}
_TRUTH = {"TRUE": "成立", "FALSE": "不成立", "UNKNOWN": "尚不确定"}


def _copy(locale: str, zh: str, en: str) -> str:
    return en if locale.startswith("en") else zh


View = Literal["auto", "none", "table", "bar", "line", "relationships"]


class ViewSelection(BaseModel):
    """A model may choose a view, never its data or executable UI properties."""

    model_config = wire_config()
    evidence_id: str
    view: View = "auto"


def project_browser_answer(
    answer: dict[str, Any], bundle: CompiledBundle, locale: str = "zh-CN"
) -> dict[str, Any]:
    """Enrich one authorized answer for the browser through a single app-layer seam."""

    result = deepcopy(answer)
    metric_ids = {m.id for m in bundle.metrics}
    labels = _document_labels(bundle)
    if locale.startswith("en"):
        labels = {key: semantic_label(locale, value, key) for key, value in labels.items()}
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
    selections = {
        item.evidence_id: item.view
        for raw in result.get("views", [])
        for item in [ViewSelection.model_validate(raw)]
    }
    presentation = _presentation(
        result.get("evidence", []), labels, result.get("query"), bundle, locale
    )
    relationships = []
    for entry in result.get("evidence", []):
        view = selections.get(entry.get("id"), "auto")
        if view != "relationships":
            continue
        definitions = entry.get("result", {}).get("definitions", [])
        objects = {doc["id"]: doc for doc in definitions if doc.get("kind") == "ObjectType"}
        edges = [
            {
                "source": objects[doc["source"]].get("label") or doc["source"],
                "target": objects[doc["target"]].get("label") or doc["target"],
                "label": doc.get("label") or _copy(locale, "关联", "Relationship"),
                "cardinality": (
                    _copy(locale, "至多一个", "At most one")
                    if doc.get("cardinality") == "ONE"
                    else _copy(locale, "可有多个", "May have many")
                ),
            }
            for doc in definitions
            if doc.get("kind") == "Link"
            and doc.get("source") in objects
            and doc.get("target") in objects
        ][:20]
        if edges:
            relationships.append({"id": entry["id"], "edges": edges})
    if presentation is not None or relationships:
        presentation = presentation or {
            "version": "semaloom/presentation-v0.1",
            "metrics": [],
            "reports": [],
        }
        presentation["relationships"] = relationships[:4]
        for report in presentation["reports"]:
            view = selections.get(report["evidenceId"], "auto")
            if view in report["availableViews"]:
                report["preferredView"] = view
        presentation["reports"] = [
            report
            for report in presentation["reports"]
            if selections.get(report["evidenceId"]) != "none"
        ]
        presentation["metrics"] = [
            metric
            for metric in presentation["metrics"]
            if selections.get(metric["evidenceId"]) != "none"
        ]
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
    locale: str,
) -> dict[str, Any] | None:
    operations = (
        {
            "SUM": "Total",
            "AVG": "Average",
            "MIN": "Minimum",
            "MAX": "Maximum",
            "COUNT": "Observed count",
        }
        if locale.startswith("en")
        else _OPERATIONS
    )
    truths = (
        {"TRUE": "True", "FALSE": "False", "UNKNOWN": "Undetermined"}
        if locale.startswith("en")
        else _TRUTH
    )
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
        report = _report(
            entry, payload, payload_labels, entry.get("query", query), bundle, locale
        ) or _object_report(entry, payload, bundle, locale)
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
                str(grain_labels[key]) if grain_labels.get(key) else str(item)
                for key, item in grain.items()
            )
            operation = operations.get(str(value.get("aggregation")), "")
            metrics.append(
                {
                    "id": f"{entry.get('id', 'evidence')}:value:{index}",
                    "evidenceId": str(entry.get("id", "")),
                    "label": str(
                        payload_labels.get(value.get("metric"))
                        or value.get("label")
                        or value.get("metric")
                        or _copy(locale, "引擎结果", "Engine result")
                    ),
                    "value": str(raw),
                    "displayValue": natural_number(raw),
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
                    "evidenceId": str(entry.get("id", "")),
                    "label": str(
                        payload_labels.get(claim_id)
                        or claim.get("label")
                        or _copy(locale, "规则判断", "Rule evaluation")
                    ),
                    "value": truth,
                    "displayValue": truths.get(truth, truth),
                    "unit": "",
                    "meta": "",
                    "tone": "positive"
                    if truth == "TRUE"
                    else "danger"
                    if truth == "FALSE"
                    else "warning",
                }
            )
        scope = payload.get("scope")
        calculation = payload.get("calculation") or (
            scope.get("calculation") if isinstance(scope, dict) else None
        )
        if (
            len(metrics) < _MAX_METRICS
            and isinstance(calculation, dict)
            and calculation.get("value") is not None
            and calculation.get("numerator") is not None
        ):
            raw = calculation["value"]
            denominator = calculation.get("denominator")
            metrics.append(
                {
                    "id": f"{entry.get('id', 'evidence')}:calculation",
                    "evidenceId": str(entry.get("id", "")),
                    "label": _copy(locale, "计算结果", "Calculation"),
                    "value": str(raw),
                    "displayValue": natural_number(raw),
                    "unit": "",
                    "meta": (
                        _copy(locale, "分子", "Numerator")
                        + f" {calculation.get('numerator')} · "
                        + _copy(locale, "分母", "denominator")
                        + f" {denominator}"
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
    locale: str,
) -> dict[str, Any] | None:
    values = [
        item
        for item in payload.get("values") or []
        if isinstance(item, dict) and isinstance(item.get("grain"), dict) and item["grain"]
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
        owners = {item.object_type for item in bundle.metrics if item.id in metric_ids}
        prop = _property(bundle, field, requested_groups, owners)
        label = _property_label(bundle, field, requested_groups, prop)
        columns.append(
            {
                "key": f"c{index}",
                "semanticId": field,
                "label": str(label or labels.get(field) or field),
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
    grain_keys: dict[tuple[str, ...], dict[str, str | None]] = {}
    for value in values:
        grain = value["grain"]
        key = tuple(str(grain.get(field, "—")) for field in grain_ids)
        row = grain_keys.setdefault(key, {})
        supplied = value.get("labels")
        display_labels: dict[str, Any] = supplied if isinstance(supplied, dict) else {}
        for index, field in enumerate(grain_ids):
            raw = str(grain.get(field, "—"))
            shown = display_labels.get(field)
            row[f"c{index}"] = str(shown) if shown else raw
        metric_id = str(value.get("metric") or "")
        if metric_id in metric_ids:
            row[f"c{len(grain_ids) + metric_ids.index(metric_id)}"] = (
                natural_number(value["value"]) if value.get("value") is not None else None
            )
    if _is_time_query(group_items):
        grain_keys = dict(sorted(grain_keys.items()))
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
        title = f"{metric_names[0]} trend" if locale.startswith("en") else f"{metric_names[0]}趋势"
    else:
        title = (
            (f"{metric_names[0]} distribution" if len(metric_names) == 1 else "Analysis results")
            if locale.startswith("en")
            else (f"{metric_names[0]}分布" if len(metric_names) == 1 else "分析结果")
        )
    available = ["table"]
    # Shared axes require comparable measures and an unambiguous category. Never
    # invent a temporal relationship between names or collapse multiple dimensions.
    if len(grain_ids) == 1 and len({item.get("unit") for item in series}) == 1:
        cells = [row.get(item["key"]) for row in rows for item in series]
        if any(cell is not None for cell in cells) and all(_chart_number(cell) for cell in cells):
            available.append("bar")
            if _is_time_query(group_items):
                available.append("line")
    preferred = (
        "line"
        if "line" in available
        else "bar"
        if "bar" in available and len(rows) <= 12
        else "table"
    )
    return {
        "id": f"{entry.get('id', 'evidence')}:report",
        "evidenceId": str(entry.get("id", "")),
        "title": title,
        "description": _copy(
            locale,
            "图形与表格使用同一组聚合结果；切换视图不会重新计算。",
            "Charts and tables use the same aggregated result; "
            "switching views does not recalculate it.",
        ),
        "columns": columns,
        "rows": rows,
        "categoryKey": columns[0]["key"],
        "series": series,
        "preferredView": preferred,
        "availableViews": available,
        "truncated": len(grain_keys) > _MAX_ROWS,
        "rowCount": len(grain_keys),
    }


def _object_report(
    entry: dict[str, Any], payload: dict[str, Any], bundle: CompiledBundle, locale: str
) -> dict[str, Any] | None:
    objects = payload.get("objects") or []
    obj = next((item for item in bundle.object_types if item.id == payload.get("objectType")), None)
    if obj is None or len(objects) < 2:
        return None
    records = [{**item.get("identity", {}), **item.get("properties", {})} for item in objects]
    # Identity and foreign-key fields are useful for audit reconciliation but
    # are not readable business dimensions. Keep them in the evidence payload;
    # the human result view only exposes descriptive and measurable properties.
    identity_fields = set(obj.identity_keys)
    for link in bundle.links:
        if link.source == obj.id:
            identity_fields.update(pair.source for pair in link.identity)
    properties = [
        prop
        for prop in obj.properties
        if prop.id not in identity_fields and any(prop.id in row for row in records)
    ][:_MAX_COLUMNS]
    columns = [
        {
            "key": prop.id,
            "semanticId": f"{obj.id}.{prop.id}",
            "label": prop.label or prop.id,
            "role": "MEASURE" if prop.unit else "DIMENSION",
            "valueType": prop.value_type,
            "unit": prop.unit,
        }
        for prop in properties
    ]
    rows = []
    for record in records[:_MAX_ROWS]:
        row: dict[str, str | None] = {}
        for prop in properties:
            raw = record.get(prop.id)
            key = str(raw).lower() if isinstance(raw, bool) else str(raw)
            display = next((item.label or item.id for item in prop.values if item.id == key), None)
            row[prop.id] = (
                None if raw is None else display or (natural_number(raw) if prop.unit else key)
            )
        rows.append(row)
    return {
        "id": f"{entry.get('id', 'evidence')}:objects",
        "evidenceId": str(entry.get("id", "")),
        "title": obj.label or obj.id,
        "description": _copy(
            locale, "当前查询返回的业务记录。", "Business records returned by this query."
        )
        + (
            _copy(locale, "还有更多记录，请缩小范围。", " More records exist; narrow the scope.")
            if payload.get("hasMore")
            else ""
        ),
        "columns": columns,
        "rows": rows,
        "categoryKey": properties[0].id if properties else "",
        "series": [
            {"key": prop.id, "label": prop.label or prop.id, "unit": prop.unit}
            for prop in properties
            if prop.unit
        ][:4],
        "preferredView": "table",
        "availableViews": ["table"],
        "truncated": bool(payload.get("hasMore")) or len(records) > _MAX_ROWS,
        "rowCount": len(records),
    }


def _chart_number(value: str | None) -> bool:
    if value is None:
        return True
    try:
        number = Decimal(value)
        return number.is_finite() and abs(number) <= 2**53 - 1
    except InvalidOperation:
        return False


def _is_time_query(group_items: Any) -> bool:
    return any(
        isinstance(item, dict) and bool(item.get("timeGrain")) for item in (group_items or [])
    )


def _property(
    bundle: CompiledBundle, field: str, requested: list[str], owners: set[str]
) -> EmbeddedProperty | None:
    qualified = next((item for item in requested if item.split(".")[-1] == field), field)
    if "." in qualified:
        owner, prop_id = qualified.rsplit(".", 1)
        obj = next((item for item in bundle.object_types if item.id == owner), None)
        if obj is not None:
            return next((item for item in obj.properties if item.id == prop_id), None)
    matches = [
        prop
        for obj in bundle.object_types
        if obj.id in owners
        for prop in obj.properties
        if prop.id == field
    ]
    return matches[0] if len(matches) == 1 else None


def _property_label(
    bundle: CompiledBundle, field: str, requested: list[str], prop: EmbeddedProperty | None
) -> str | None:
    if prop is None:
        return None
    qualified = next((item for item in requested if item.split(".")[-1] == field), field)
    if "." not in qualified or prop.label not in {"名称", "编号"}:
        return prop.label
    owner_id = qualified.rsplit(".", 1)[0]
    owner = next((item for item in bundle.object_types if item.id == owner_id), None)
    return f"{owner.label}{prop.label}" if owner and owner.label else prop.label


def _document_labels(bundle: CompiledBundle) -> dict[str, str]:
    labels: dict[str, str] = {}
    property_labels: dict[str, set[str]] = {}
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
                property_labels.setdefault(prop.id, set()).add(prop.label)
                labels[f"{obj.id}.{prop.id}"] = prop.label
    labels.update(
        {key: next(iter(names)) for key, names in property_labels.items() if len(names) == 1}
    )
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
    if result.pop("confidence", None) is not None:
        # Old stored answers retain their original scope and evidence; retire only
        # the former generated score in the browser projection.
        result["text"] = "\n".join(
            line
            for line in str(result.get("text") or "").splitlines()
            if not line.startswith("置信度：")
        )
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

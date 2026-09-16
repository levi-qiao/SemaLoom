"""Browser-only evidence projection; never send physical metadata to the model."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from semaloom.core.bundle import CompiledBundle
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.studio import mapping_summary


def attach_lineage(answer: dict[str, Any], bundle: CompiledBundle) -> dict[str, Any]:
    result = deepcopy(answer)
    metric_ids = {m.id for m in bundle.metrics}
    for evidence in result.get("evidence", []):
        d = evidence.get("result", {})
        mapping_ids = _mapping_ids(d)

        if isinstance(d, dict) and "definitions" in d and isinstance(d["definitions"], list):
            for doc in d["definitions"]:
                if isinstance(doc, dict):
                    _enrich_definition_sources(doc, bundle, metric_ids)
        elif isinstance(d, dict) and "id" in d and "kind" in d:
            _enrich_definition_sources(d, bundle, metric_ids)

        evidence["lineage"] = [
            mapping_summary(m, metric_ids) for m in bundle.mappings if m.id in mapping_ids
        ]
    return result


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

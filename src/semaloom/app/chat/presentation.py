"""Browser-only evidence projection; never send physical metadata to the model."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from semaloom.core.bundle import CompiledBundle
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.studio import mapping_summary


def attach_lineage(answer: dict[str, Any], bundle: CompiledBundle) -> dict[str, Any]:
    result = deepcopy(answer)
    for evidence in result.get("evidence", []):
        mapping_ids = _mapping_ids(evidence["result"])
        metric_ids = {m.id for m in bundle.metrics}
        evidence["lineage"] = [
            mapping_summary(m, metric_ids) for m in bundle.mappings if m.id in mapping_ids
        ]
    return result


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
            if key not in {"lineage", "mappingFields"}
        }
    if isinstance(value, list):
        return [without_physical_metadata(item) for item in value]
    return value

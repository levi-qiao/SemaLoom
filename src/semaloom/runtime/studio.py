"""Studio projections from a compiled bundle. No domain special cases."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from semaloom.core.bundle import CompiledBundle


def studio_graph(bundle: CompiledBundle) -> dict[str, Any]:
    nodes = [
        {
            "id": item.id,
            "label": item.label or item.id,
            "kind": "ObjectType",
            "properties": [prop.id for prop in item.properties],
        }
        for item in bundle.object_types
    ]
    edges = [
        {
            "id": item.id,
            "source": item.source,
            "target": item.target,
            "cardinality": item.cardinality,
        }
        for item in bundle.links
    ]
    return {"nodes": nodes, "edges": edges}


def studio_inspector(bundle: CompiledBundle, object_id: str) -> dict[str, Any] | None:
    obj = next((item for item in bundle.object_types if item.id == object_id), None)
    if obj is None:
        return None
    metrics = [item.id for item in bundle.metrics if item.object_type == object_id]
    mappings = [item.id for item in bundle.mappings if item.object_type == object_id]
    metric_set = set(metrics)
    rules = [
        item.id for item in bundle.rules if any(spec.metric in metric_set for spec in item.inputs)
    ]
    return {
        "id": obj.id,
        "label": obj.label or obj.id,
        "identityKeys": list(obj.identity_keys),
        "properties": [prop.model_dump(mode="json") for prop in obj.properties],
        "metrics": metrics,
        "mappings": mappings,
        "rules": rules,
    }


def save_draft(
    engine: Engine, draft_id: str, payload: dict[str, Any], expected_revision: int
) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT revision FROM studio_draft WHERE draft_id = :draft_id"),
            {"draft_id": draft_id},
        ).first()
        if row is None:
            conn.execute(
                text(
                    """
                    INSERT INTO studio_draft(draft_id, revision, payload)
                    VALUES (:draft_id, 1, CAST(:payload AS jsonb))
                    """
                ),
                {"draft_id": draft_id, "payload": json.dumps(payload)},
            )
            return 1
        if int(row.revision) != expected_revision:
            raise ValueError("REVISION_CONFLICT")
        conn.execute(
            text(
                """
                UPDATE studio_draft
                SET revision = revision + 1, payload = CAST(:payload AS jsonb)
                WHERE draft_id = :draft_id
                """
            ),
            {"draft_id": draft_id, "payload": json.dumps(payload)},
        )
        return int(row.revision) + 1

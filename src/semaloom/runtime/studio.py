"""Studio projections from a compiled bundle. No domain special cases."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import MappingDef


def _namespace(semantic_id: str) -> str:
    return semantic_id.partition(".")[0]


def _resource(mapping: MappingDef) -> str:
    """Return a safe physical resource label without exposing connection settings."""

    physical = mapping.physical
    if mapping.provider == "postgres":
        table = physical.get("table")
        schema = physical.get("schema")
        if isinstance(table, str):
            return f"{schema}.{table}" if isinstance(schema, str) else table
    operation = physical.get("operationId")
    if isinstance(operation, str):
        return operation
    return "registered resource"


def _field_count(mapping: MappingDef) -> int:
    physical = mapping.physical
    fields: set[str] = set()
    for key in ("identityColumn", "valueColumn"):
        value = physical.get(key)
        if isinstance(value, str):
            fields.add(value)
    for key in ("grainColumns", "propertyColumns"):
        value = physical.get(key)
        if isinstance(value, dict):
            fields.update(str(item) for item in value.values())
    return len(fields)


def mapping_summary(mapping: MappingDef) -> dict[str, Any]:
    return {
        "id": mapping.id,
        "label": mapping.label or mapping.id,
        "target": mapping.target,
        "objectType": mapping.object_type,
        "sourceId": mapping.source_id,
        "provider": mapping.provider,
        "resource": _resource(mapping),
        "fieldCount": _field_count(mapping),
        "completeness": mapping.completeness,
        "expectedCardinality": mapping.expected_cardinality,
        "perspective": mapping.perspective,
    }


def studio_graph(bundle: CompiledBundle) -> dict[str, Any]:
    metric_ids_by_object = {
        item.id: [metric.id for metric in bundle.metrics if metric.object_type == item.id]
        for item in bundle.object_types
    }
    nodes = []
    for item in bundle.object_types:
        metric_ids = set(metric_ids_by_object[item.id])
        mappings = [mapping for mapping in bundle.mappings if mapping.object_type == item.id]
        rules = [
            rule
            for rule in bundle.rules
            if any(spec.metric in metric_ids or spec.object_type == item.id for spec in rule.inputs)
        ]
        nodes.append(
            {
                "id": item.id,
                "label": item.label or item.id.rpartition(".")[2],
                "namespace": _namespace(item.id),
                "kind": "ObjectType",
                "properties": [prop.id for prop in item.properties],
                "metricCount": len(metric_ids),
                "ruleCount": len(rules),
                "mappingCount": len(mappings),
                "sourceCount": len({mapping.source_id for mapping in mappings}),
            }
        )
    edges = [
        {
            "id": item.id,
            "label": item.label or item.id.rpartition(".")[2],
            "source": item.source,
            "target": item.target,
            "cardinality": item.cardinality,
            "sourceKey": item.identity.source,
            "targetKey": item.identity.target,
        }
        for item in bundle.links
    ]
    return {
        "meta": {
            "releaseDigest": bundle.digest,
            "onlineValidation": bundle.online_validation,
            "packs": [
                {"id": item.id, "label": item.label or item.id, "version": item.version}
                for item in bundle.packs
            ],
            "counts": {
                "objects": len(bundle.object_types),
                "links": len(bundle.links),
                "mappings": len(bundle.mappings),
                "sources": len(bundle.integration_bindings),
                "rules": len(bundle.rules),
            },
        },
        "nodes": nodes,
        "edges": edges,
    }


def studio_inspector(bundle: CompiledBundle, object_id: str) -> dict[str, Any] | None:
    obj = next((item for item in bundle.object_types if item.id == object_id), None)
    if obj is None:
        return None
    object_mappings = [item for item in bundle.mappings if item.object_type == object_id]
    metrics = [item for item in bundle.metrics if item.object_type == object_id]
    metric_ids = {item.id for item in metrics}
    rules = [
        item
        for item in bundle.rules
        if any(spec.metric in metric_ids or spec.object_type == object_id for spec in item.inputs)
    ]
    object_labels = {
        item.id: item.label or item.id.rpartition(".")[2] for item in bundle.object_types
    }
    relations = []
    for item in bundle.links:
        if item.source == object_id:
            relations.append(
                {
                    "id": item.id,
                    "label": item.label or item.id.rpartition(".")[2],
                    "direction": "OUTGOING",
                    "target": item.target,
                    "targetLabel": object_labels[item.target],
                    "cardinality": item.cardinality,
                }
            )
        elif item.target == object_id:
            relations.append(
                {
                    "id": item.id,
                    "label": item.label or item.id.rpartition(".")[2],
                    "direction": "INCOMING",
                    "target": item.source,
                    "targetLabel": object_labels[item.source],
                    "cardinality": item.cardinality,
                }
            )
    return {
        "id": obj.id,
        "label": obj.label or obj.id.rpartition(".")[2],
        "version": obj.version,
        "namespace": _namespace(obj.id),
        "identityKeys": list(obj.identity_keys),
        "properties": [prop.model_dump(mode="json", by_alias=True) for prop in obj.properties],
        "metrics": [
            {
                "id": item.id,
                "label": item.label or item.id.rpartition(".")[2],
                "valueType": item.value_type,
                "unit": item.unit,
                "perspective": item.perspective,
            }
            for item in metrics
        ],
        "mappings": [mapping_summary(item) for item in object_mappings],
        "rules": [
            {
                "id": item.id,
                "label": item.label or item.id.rpartition(".")[2],
                "claim": item.claim,
            }
            for item in rules
        ],
        "relations": relations,
    }


def studio_mappings(bundle: CompiledBundle) -> dict[str, Any]:
    return {
        "mappings": [mapping_summary(item) for item in bundle.mappings],
        "onlineValidation": bundle.online_validation,
    }


def studio_sources(bundle: CompiledBundle) -> dict[str, Any]:
    mappings_by_id = {item.id: item for item in bundle.mappings}
    action_bindings_by_id = {item.id: item for item in bundle.action_bindings}
    sources = []
    for binding in bundle.integration_bindings:
        mappings = [mappings_by_id[item] for item in binding.mappings]
        action_bindings = [action_bindings_by_id[item] for item in binding.action_bindings]
        targets = {item.target for item in mappings}
        targets.update(item.action for item in action_bindings)
        sources.append(
            {
                "id": binding.id,
                "label": binding.label or binding.source_id,
                "sourceId": binding.source_id,
                "provider": binding.provider,
                "mappingCount": len(mappings),
                "actionCount": len(action_bindings),
                "targets": sorted(targets),
                "namespaces": sorted({_namespace(item) for item in targets}),
                "status": bundle.online_validation,
            }
        )
    return {"sources": sources}


def load_draft(engine: Engine, tenant: str, draft_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT revision, payload
                FROM studio_draft
                WHERE tenant_id = :tenant_id AND draft_id = :draft_id
                """
            ),
            {"tenant_id": tenant, "draft_id": draft_id},
        ).first()
    if row is None:
        return {"draftId": draft_id, "revision": 0, "payload": {}, "exists": False}
    payload = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
    return {
        "draftId": draft_id,
        "revision": int(row.revision),
        "payload": payload,
        "exists": True,
    }


def save_draft(
    engine: Engine,
    tenant: str,
    draft_id: str,
    payload: dict[str, Any],
    expected_revision: int,
) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                WITH updated AS (
                    UPDATE studio_draft
                    SET revision = revision + 1,
                        payload = CAST(:payload AS jsonb)
                    WHERE tenant_id = :tenant_id
                      AND draft_id = :draft_id
                      AND revision = :expected_revision
                    RETURNING revision
                ),
                inserted AS (
                    INSERT INTO studio_draft(tenant_id, draft_id, revision, payload)
                    SELECT :tenant_id, :draft_id, 1, CAST(:payload AS jsonb)
                    WHERE :expected_revision = 0
                      AND NOT EXISTS (
                          SELECT 1
                          FROM studio_draft
                          WHERE tenant_id = :tenant_id AND draft_id = :draft_id
                      )
                    ON CONFLICT (tenant_id, draft_id) DO NOTHING
                    RETURNING revision
                )
                SELECT revision FROM updated
                UNION ALL
                SELECT revision FROM inserted
                """
            ),
            {
                "tenant_id": tenant,
                "draft_id": draft_id,
                "payload": json.dumps(payload),
                "expected_revision": expected_revision,
            },
        ).first()
        if row is None:
            raise ValueError("REVISION_CONFLICT")
        return int(row.revision)

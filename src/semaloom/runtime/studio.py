"""Studio projections from a compiled bundle. No domain special cases."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import MappingDef
from semaloom.core.provider import IdentityScalar, IdentityValue, ReadProvider


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
    for key in ("valueColumn", "valuePointer"):
        value = physical.get(key)
        if isinstance(value, str):
            fields.add(value)
    for key in (
        "grainColumns",
        "propertyColumns",
        "grainPointers",
        "propertyPointers",
    ):
        value = physical.get(key)
        if isinstance(value, dict):
            fields.update(str(item) for item in value.values())
    return len(fields)


def _field_bindings(mapping: MappingDef) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    pairs = (
        ("grainColumns", "identity"),
        ("propertyColumns", "property"),
        ("grainPointers", "identity"),
        ("propertyPointers", "property"),
    )
    seen: set[tuple[str, str, str]] = set()
    for key, role in pairs:
        value = mapping.physical.get(key)
        if isinstance(value, dict):
            for semantic, physical in value.items():
                item = (str(semantic), str(physical), role)
                if item in seen:
                    continue
                seen.add(item)
                fields.append(
                    {
                        "semanticField": item[0],
                        "physicalField": item[1],
                        "role": item[2],
                    }
                )
    value_field = mapping.physical.get("valueColumn") or mapping.physical.get("valuePointer")
    if isinstance(value_field, str):
        fields.append(
            {"semanticField": mapping.target, "physicalField": value_field, "role": "value"}
        )
    return sorted(fields, key=lambda item: (item["role"], item["semanticField"]))


def mapping_summary(mapping: MappingDef, metric_ids: set[str] | None = None) -> dict[str, Any]:
    targets = metric_ids or set()
    identity_fields = list(mapping.identity_fields)
    return {
        "id": mapping.id,
        "label": mapping.label or mapping.id,
        "target": mapping.target,
        "objectType": mapping.object_type,
        "sourceId": mapping.source_id,
        "provider": mapping.provider,
        "resource": _resource(mapping),
        "fieldCount": _field_count(mapping),
        "fields": _field_bindings(mapping),
        "completeness": mapping.completeness,
        "expectedCardinality": mapping.expected_cardinality,
        "perspective": mapping.perspective,
        "capabilities": list(mapping.capabilities),
        "targetKind": "metric" if mapping.target in targets else "object",
        "identityFields": identity_fields,
        "requiredBindings": _required_preview_bindings(mapping, identity_fields),
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
        actions = [action for action in bundle.actions if action.target_object == item.id]
        nodes.append(
            {
                "id": item.id,
                "label": item.label or item.id.rpartition(".")[2],
                "namespace": _namespace(item.id),
                "kind": "ObjectType",
                "properties": [prop.id for prop in item.properties],
                "metricCount": len(metric_ids),
                "ruleCount": len(rules),
                "actionCount": len(actions),
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
            "sourceKey": " + ".join(pair.source for pair in item.identity),
            "targetKey": " + ".join(pair.target for pair in item.identity),
        }
        for item in bundle.links
    ]
    return {
        "meta": {
            "releaseDigest": bundle.digest,
            "onlineValidation": bundle.online_validation,
            "packs": [
                {
                    "id": item.id,
                    "namespace": item.namespace,
                    "label": item.label or item.id,
                    "version": item.version,
                }
                for item in bundle.packs
            ],
            "counts": {
                "objects": len(bundle.object_types),
                "links": len(bundle.links),
                "mappings": len(bundle.mappings),
                "sources": len({item.source_id for item in bundle.integration_bindings}),
                "rules": len(bundle.rules),
                "actions": len(bundle.actions),
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
    object_metric_ids = {item.id for item in metrics}
    metric_ids = {item.id for item in bundle.metrics}
    actions = [item for item in bundle.actions if item.target_object == object_id]
    bindings_by_action = {
        item.id: [binding for binding in bundle.action_bindings if binding.action == item.id]
        for item in actions
    }
    rules = [
        item
        for item in bundle.rules
        if any(
            spec.metric in object_metric_ids or spec.object_type == object_id
            for spec in item.inputs
        )
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
        "mappings": [mapping_summary(item, metric_ids) for item in object_mappings],
        "rules": [
            {
                "id": item.id,
                "label": item.label or item.id.rpartition(".")[2],
                "claim": item.claim,
            }
            for item in rules
        ],
        "actions": [
            {
                "id": item.id,
                "label": item.label or item.id.rpartition(".")[2],
                "effect": item.effect,
                "preconditions": list(item.preconditions),
                "parameters": [
                    {
                        "name": param.name,
                        "valueType": param.value_type,
                        "required": param.required,
                    }
                    for param in item.parameters
                ],
                "bindings": [
                    {
                        "id": binding.id,
                        "sourceId": binding.source_id,
                        "provider": binding.provider,
                    }
                    for binding in bindings_by_action[item.id]
                ],
            }
            for item in actions
        ],
        "relations": relations,
    }


def studio_mappings(bundle: CompiledBundle) -> dict[str, Any]:
    metric_ids = {item.id for item in bundle.metrics}
    return {
        "mappings": [mapping_summary(item, metric_ids) for item in bundle.mappings],
        "onlineValidation": bundle.online_validation,
    }


def studio_mapping_preview(
    bundle: CompiledBundle,
    provider: ReadProvider,
    *,
    mapping_id: str,
    tenant: str,
    identity: IdentityValue,
    bindings: dict[str, IdentityScalar] | None = None,
) -> dict[str, Any] | None:
    mapping = next((item for item in bundle.mappings if item.id == mapping_id), None)
    if mapping is None:
        return None
    object_type = next(
        (item for item in bundle.object_types if item.id == mapping.object_type), None
    )
    if object_type is None or set(identity) != set(object_type.identity_keys):
        raise ValueError("INVALID_IDENTITY")
    identity_value: IdentityValue = {key: identity[key] for key in object_type.identity_keys}
    supplied = dict(bindings or {})
    metric_ids = {item.id for item in bundle.metrics}
    extra = {
        key: value
        for key, value in supplied.items()
        if key in mapping.grain_fields and key not in identity_value
    }
    fields = _field_bindings(mapping)
    if mapping.target in metric_ids:
        observation = provider.fetch_metric(
            mapping, tenant=tenant, identity_value=identity_value, bindings=extra or None
        )
        values = {mapping.target: observation.value} if observation.kind == "PRESENT" else {}
        kind = observation.kind
        reason = observation.reason
        observed_at = observation.observed_at
    else:
        result = provider.fetch_object(mapping, tenant=tenant, identity_value=identity_value)
        values = result.values if result.kind == "PRESENT" else {}
        kind = result.kind
        reason = result.reason
        observed_at = result.observed_at
    preview_values = {**identity_value, **supplied, **values}
    return {
        "preview": True,
        "mappingId": mapping.id,
        "target": mapping.target,
        "objectType": mapping.object_type,
        "sourceId": mapping.source_id,
        "provider": mapping.provider,
        "resource": _resource(mapping),
        "identity": identity_value,
        "kind": kind,
        "reason": reason,
        "observedAt": observed_at,
        "fields": [
            {
                **field,
                "value": _preview_value(preview_values.get(field["semanticField"])),
            }
            for field in fields
        ],
    }


def _required_preview_bindings(
    mapping: MappingDef, identity_fields: list[str] | None = None
) -> list[str]:
    identity = set(identity_fields or mapping.identity_fields)
    return [field for field in mapping.grain_fields if field not in identity]


def _preview_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


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
                "status": "DECLARED",
            }
        )
    return {"sources": sources}

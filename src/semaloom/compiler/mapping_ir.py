"""Compile provider-specific Mapping physical config into neutral runtime metadata."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from semaloom.core.diagnostics import Diagnostic
from semaloom.core.model import MappingDef, MetricDef, ObjectTypeDef

_POSTGRES_FIELDS = ("grainColumns", "propertyColumns")
_OPENAPI_FIELDS = ("grainPointers", "propertyPointers")
_LEGACY_IDENTITY_FIELDS = frozenset(
    {
        "identityColumn",
        "identityColumns",
        "identityParameter",
        "identity" + "Parameters",
        "identityPointer",
        "identityPointers",
    }
)


def compile_mapping_ir(
    objects: Sequence[ObjectTypeDef],
    mappings: Sequence[MappingDef],
    diagnostics: list[Diagnostic],
) -> list[MappingDef]:
    object_index = {item.id: item for item in objects}
    compiled: list[MappingDef] = []
    for mapping in mappings:
        obj = object_index.get(mapping.object_type)
        if obj is None:
            compiled.append(mapping)
            continue
        legacy = sorted(_LEGACY_IDENTITY_FIELDS & set(mapping.physical))
        if legacy:
            diagnostics.append(
                Diagnostic(
                    code="LEGACY_MAPPING_FIELD",
                    path=f"{mapping.id}.physical",
                    message=f"remove legacy identity fields: {', '.join(legacy)}",
                )
            )
        try:
            grain, properties, capabilities = _provider_contract(mapping, obj.identity_keys)
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(code="INVALID_MAPPING", path=mapping.id, message=str(exc))
            )
            compiled.append(mapping)
            continue
        missing = [key for key in obj.identity_keys if key not in grain]
        if missing:
            diagnostics.append(
                Diagnostic(
                    code="INVALID_MAPPING",
                    path=f"{mapping.id}.physical",
                    message=f"identity keys must be mapped in grain: {', '.join(missing)}",
                )
            )
        compiled.append(
            mapping.model_copy(
                update={
                    "identity_fields": tuple(obj.identity_keys),
                    "grain_fields": tuple(
                        key
                        for key in dict.fromkeys((*obj.identity_keys, *sorted(grain)))
                        if key in grain
                    ),
                    "property_fields": tuple(sorted(properties)),
                    "capabilities": capabilities,
                }
            )
        )
    return compiled


def derive_metric_mapping(source: MappingDef, metric: MetricDef, mapping_id: str) -> MappingDef:
    """Derive a metric mapping at the provider boundary, not in the common compiler."""
    if metric.property is None:
        raise ValueError("metric property is required")
    physical = deepcopy(dict(source.physical))
    slots = _physical_slots(source)
    value_slot = slots[metric.property]
    if source.provider == "postgres":
        physical["valueColumn"] = value_slot
        filters = dict(physical.get("filters") or {})
        for key, value in metric.select.items():
            selected = slots.get(key)
            if selected is not None:
                filters[selected] = value
        if metric.perspective:
            selected = slots.get("perspective")
            if selected is not None:
                filters.setdefault(selected, metric.perspective)
        if filters:
            physical["filters"] = filters
    elif source.provider == "openapi":
        physical["valuePointer"] = value_slot
        fixed = dict(physical.get("fixedParameters") or {})
        params = _string_map(physical, "parameterBindings")
        for key, value in metric.select.items():
            parameter = params.get(key)
            if parameter is not None:
                fixed[parameter] = value
        if metric.perspective:
            parameter = params.get("perspective")
            if parameter is not None:
                fixed.setdefault(parameter, metric.perspective)
        if fixed:
            physical["fixedParameters"] = fixed
    else:
        raise ValueError(f"unsupported mapping provider {source.provider!r}")
    return MappingDef.model_validate(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Mapping",
            "id": mapping_id,
            "version": source.version,
            "label": metric.label or metric.id,
            "target": metric.id,
            "sourceId": source.source_id,
            "provider": source.provider,
            "objectType": metric.object_type,
            "perspective": metric.perspective,
            "expectedCardinality": source.expected_cardinality,
            "completeness": source.completeness,
            "identityFields": list(source.identity_fields),
            "grainFields": list(source.grain_fields),
            "propertyFields": list(source.property_fields),
            "capabilities": list(source.capabilities),
            "physical": physical,
        }
    )


def _provider_contract(
    mapping: MappingDef,
    identity_fields: Sequence[str],
) -> tuple[dict[str, str], dict[str, str], tuple[str, ...]]:
    if mapping.provider == "postgres":
        grain = _string_map(mapping.physical, "grainColumns")
        properties = _string_map(mapping.physical, "propertyColumns")
        if not isinstance(mapping.physical.get("table"), str):
            raise ValueError("postgres mapping requires table")
        return grain, properties, ("POINT_READ", "COLLECTION_READ", "EQUI_JOIN")
    if mapping.provider == "openapi":
        grain = _string_map(mapping.physical, "grainPointers")
        properties = _string_map(mapping.physical, "propertyPointers")
        parameters = _string_map(mapping.physical, "parameterBindings")
        if str(mapping.physical.get("method", "GET")).upper() != "GET":
            raise ValueError("read mapping requires GET")
        missing_parameters = [key for key in identity_fields if key not in parameters]
        if missing_parameters:
            raise ValueError(f"identity parameters missing: {', '.join(missing_parameters)}")
        return grain, properties, ("POINT_READ",)
    raise ValueError(f"unsupported mapping provider {mapping.provider!r}")


def _physical_slots(mapping: MappingDef) -> dict[str, str]:
    fields = _POSTGRES_FIELDS if mapping.provider == "postgres" else _OPENAPI_FIELDS
    slots: dict[str, str] = {}
    for field in fields:
        slots.update(_string_map(mapping.physical, field))
    return slots


def _string_map(value: dict[str, Any], key: str) -> dict[str, str]:
    raw = value.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{key} must be an object")
    result = {str(name): str(target) for name, target in raw.items() if str(target)}
    if len(result) != len(raw):
        raise ValueError(f"{key} contains an empty binding")
    return result

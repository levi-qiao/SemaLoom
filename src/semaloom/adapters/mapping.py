"""Built-in PostgreSQL/OpenAPI mapping compilation, owned by the integration layer."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from semaloom.adapters.identifiers import require_ident
from semaloom.core.diagnostics import Diagnostic
from semaloom.core.model import MappingDef, MetricDef, ObjectTypeDef

_POSTGRES_FIELDS = ("grainColumns", "propertyColumns")
_OPENAPI_FIELDS = ("grainPointers", "propertyPointers")
_LEGACY_IDENTITY_FIELDS = frozenset(
    {
        "identityColumn",
        "identityColumns",
        "identityParameter",
        "identityParameters",
        "identityPointer",
        "identityPointers",
    }
)


class BuiltinMappingCompiler:
    """Trusted physical compiler for the two shipped read-provider profiles."""

    def compile_mappings(
        self,
        objects: Sequence[ObjectTypeDef],
        mappings: Sequence[MappingDef],
        diagnostics: list[Diagnostic],
    ) -> list[MappingDef]:
        return compile_mapping_ir(objects, mappings, diagnostics)

    def derive_metric(self, source: MappingDef, metric: MetricDef, mapping_id: str) -> MappingDef:
        return derive_metric_mapping(source, metric, mapping_id)


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
            if selected is None:
                raise ValueError(f"metric selector {key!r} has no mapped column")
            if selected in filters and filters[selected] != value:
                raise ValueError(f"metric selector {key!r} conflicts with the source filter")
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
            if parameter is None:
                raise ValueError(f"metric selector {key!r} has no bound API parameter")
            if parameter in fixed and fixed[parameter] != value:
                raise ValueError(f"metric selector {key!r} conflicts with the source filter")
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
        require_ident(mapping.physical.get("table"), field="table")
        require_ident(mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn")
        for semantic, column in {**grain, **properties}.items():
            require_ident(semantic, field="semantic field")
            require_ident(column, field=f"binding {semantic}")
        value_column = mapping.physical.get("valueColumn")
        if value_column is not None:
            require_ident(value_column, field="valueColumn")
        filters = mapping.physical.get("filters")
        if filters is not None:
            if not isinstance(filters, dict):
                raise ValueError("filters must be an object")
            for column in filters:
                require_ident(column, field="filter")
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
    result: dict[str, str] = {}
    for name, target in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"{key} contains an invalid semantic field")
        if not isinstance(target, str) or not target:
            raise ValueError(f"{key}.{name} must be a non-empty string")
        result[name] = target
    return result

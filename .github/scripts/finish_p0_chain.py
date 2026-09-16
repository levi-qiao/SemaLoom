from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    text = read(path)
    actual = text.count(old)
    if actual < count:
        raise SystemExit(f"{path}: expected >= {count} occurrences, found {actual}: {old[:120]!r}")
    write(path, text.replace(old, new, count))


def regex(path: str, pattern: str, replacement: str, *, count: int = 1, flags: int = 0) -> None:
    text = read(path)
    updated, actual = re.subn(pattern, replacement, text, count=count, flags=flags)
    if actual != count:
        raise SystemExit(f"{path}: expected {count} regex replacements, found {actual}: {pattern[:120]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Core contract: compiled mappings expose protocol-neutral semantic capability
# and field metadata. Physical protocol details stay in compiler/adapters.
# ---------------------------------------------------------------------------
replace(
    "src/semaloom/core/model.py",
    '''class MappingDef(_Doc):
    kind: Literal["Mapping"] = "Mapping"
    target: str
    source_id: str
    provider: str
    object_type: str
    perspective: str | None = None
    expected_cardinality: Cardinality
    completeness: Literal["AUTHORITATIVE", "PARTIAL"] = "PARTIAL"
    capabilities: tuple[MappingCapability, ...] = ("POINT_READ",)
    physical: dict[str, Any]
''',
    '''class MappingDef(_Doc):
    kind: Literal["Mapping"] = "Mapping"
    target: str
    source_id: str
    provider: str
    object_type: str
    perspective: str | None = None
    expected_cardinality: Cardinality
    completeness: Literal["AUTHORITATIVE", "PARTIAL"] = "PARTIAL"
    identity_fields: tuple[str, ...] = ()
    grain_fields: tuple[str, ...] = ()
    property_fields: tuple[str, ...] = ()
    capabilities: tuple[MappingCapability, ...] = ()
    physical: dict[str, Any]
''',
)

write(
    "src/semaloom/core/provider.py",
    '''"""Protocol-neutral read-provider contract used by the runtime."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from semaloom.core.model import MappingDef
from semaloom.core.results import Observation

IdentityScalar = str | int | bool
IdentityValue = dict[str, IdentityScalar]


class ObjectRead(BaseModel):
    """Normalized outcome of reading one business object from a source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["PRESENT", "MISSING", "UNAVAILABLE"]
    values: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    mapping_id: str
    source_id: str
    observed_at: str


class ObjectSearch(BaseModel):
    """A bounded page of source objects; has_more is never a completeness claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["PRESENT", "UNAVAILABLE"]
    rows: tuple[dict[str, Any], ...] = ()
    has_more: bool = False
    reason: str | None = None
    observed_at: str = ""


class ReadProvider(Protocol):
    """Runtime seam. All keys are semantic; adapters own physical translation."""

    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
        bindings: dict[str, IdentityScalar] | None = None,
    ) -> Observation: ...

    def fetch_object(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
    ) -> ObjectRead: ...

    def search_objects(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        filters: dict[str, Any],
        properties: tuple[str, ...],
        limit: int,
    ) -> ObjectSearch: ...
''',
)

write(
    "src/semaloom/compiler/mapping_ir.py",
    '''"""Compile provider-specific Mapping physical config into neutral runtime metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Sequence

from semaloom.core.diagnostics import Diagnostic
from semaloom.core.model import MappingDef, MetricDef, ObjectTypeDef

_POSTGRES_FIELDS = ("grainColumns", "propertyColumns")
_OPENAPI_FIELDS = ("grainPointers", "propertyPointers")
_LEGACY_IDENTITY_FIELDS = frozenset(
    {
        "identityColumn",
        "identityColumns",
        "identityParameter",
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
            grain, properties, capabilities = _provider_contract(mapping)
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
                    "grain_fields": tuple(grain),
                    "property_fields": tuple(properties),
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
        missing_parameters = [key for key in grain if key not in parameters]
        identity_like = [key for key in missing_parameters if key in mapping.identity_fields]
        if identity_like:
            raise ValueError(f"identity parameters missing: {', '.join(identity_like)}")
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
''',
)

# Common compiler consumes only neutral mapping metadata. Provider-specific metric
# materialization is delegated to mapping_ir.py.
replace("src/semaloom/compiler/api.py", "from copy import deepcopy\n", "")
replace(
    "src/semaloom/compiler/api.py",
    "from semaloom.compiler.digest import canonical_json, physical_digest, sha256_digest\n",
    "from semaloom.compiler.digest import canonical_json, physical_digest, sha256_digest\n"
    "from semaloom.compiler.mapping_ir import compile_mapping_ir, derive_metric_mapping\n",
)
replace(
    "src/semaloom/compiler/api.py",
    '''    bindings = [item for item in parsed if isinstance(item, ActionBindingDef)]

    metrics = _metrics_from_properties(objects, metrics, mappings)
''',
    '''    bindings = [item for item in parsed if isinstance(item, ActionBindingDef)]

    mappings = compile_mapping_ir(objects, mappings, diagnostics)
    metrics = _metrics_from_properties(objects, metrics, mappings)
''',
)
regex(
    "src/semaloom/compiler/api.py",
    r'def _physical_slots\(mapping: MappingDef\) -> dict\[str, str\]:\n(?:    .*\n)+?    return slots\n\n\ndef _grain_slots\(mapping: MappingDef\) -> dict\[str, str\]:\n(?:    .*\n)+?    return slots\n',
    '''def _physical_slots(mapping: MappingDef) -> dict[str, str]:
    return {key: key for key in (*mapping.grain_fields, *mapping.property_fields)}


def _grain_slots(mapping: MappingDef) -> dict[str, str]:
    return {key: key for key in mapping.grain_fields}
''',
    flags=re.MULTILINE,
)
regex(
    "src/semaloom/compiler/api.py",
    r'''            physical = deepcopy\(dict\(source\.physical\)\)\n            slots = _physical_slots\(source\)\n            column = slots\[metric\.property\]\n            if source\.physical\.get\("propertyPointers"\).*?            owners\[mapping_id\] = source\.id\n''',
    '''            extra.append(derive_metric_mapping(source, metric, mapping_id))
            owners[mapping_id] = source.id
''',
    flags=re.DOTALL,
)
regex(
    "src/semaloom/compiler/api.py",
    r'''def _object_mapping_properties_are_disjoint\(mappings: Sequence\[MappingDef\]\) -> bool:\n    seen: set\[str\] = set\(\)\n    for mapping in mappings:\n        current: set\[str\] = set\(\)\n        for field in \("propertyColumns", "propertyPointers"\):\n            value = mapping\.physical\.get\(field\)\n            if isinstance\(value, dict\):\n                current\.update\(str\(key\) for key in value\)\n        if not current or seen & current:\n            return False\n        seen\.update\(current\)\n    return True\n''',
    '''def _object_mapping_properties_are_disjoint(mappings: Sequence[MappingDef]) -> bool:
    seen: set[str] = set()
    for mapping in mappings:
        current = set(mapping.property_fields)
        if not current or seen & current:
            return False
        seen.update(current)
    return True
''',
    flags=re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Adapter boundary: translate semantic identity/bindings to physical protocol.
# No scalar identity path remains.
# ---------------------------------------------------------------------------
replace(
    "src/semaloom/adapters/postgres.py",
    "from semaloom.core.provider import IdentityValue, ObjectRead, ObjectSearch\n",
    "from semaloom.core.provider import IdentityScalar, IdentityValue, ObjectRead, ObjectSearch\n",
)
replace(
    "src/semaloom/adapters/postgres.py",
    "        extra_filters: dict[str, str] | None = None,\n",
    "        bindings: dict[str, IdentityScalar] | None = None,\n",
)
replace(
    "src/semaloom/adapters/postgres.py",
    '''            if extra_filters:
                for key, value in extra_filters.items():
                    column = require_ident(key, field=f"binding.{key}")
                    pname = f"b_{column}"
                    clauses.append(f"{column} = :{pname}")
                    params[pname] = value
''',
    '''            if bindings:
                grain = mapping.physical.get("grainColumns")
                if not isinstance(grain, dict):
                    raise ValueError("grainColumns must be an object")
                for index, (semantic, value) in enumerate(bindings.items()):
                    column = require_ident(grain.get(semantic), field=f"binding.{semantic}")
                    pname = f"b_{index}"
                    clauses.append(f"{column} = :{pname}")
                    params[pname] = value
''',
)
replace(
    "src/semaloom/adapters/postgres.py",
    '''            order_columns = list(dict.fromkeys(projection[key] for key in properties))
            order_by = ", ".join(order_columns)
''',
    '''            order_columns = [projection[key] for key in mapping.identity_fields]
            order_by = ", ".join(order_columns)
''',
)
regex(
    "src/semaloom/adapters/postgres.py",
    r'''def _identity_columns\(mapping: MappingDef, identity_value: IdentityValue\) -> dict\[str, str\]:\n.*?    return columns\n''',
    '''def _identity_columns(mapping: MappingDef, identity_value: IdentityValue) -> dict[str, str]:
    if set(identity_value) != set(mapping.identity_fields):
        raise ValueError("identity does not match compiled mapping")
    grain = mapping.physical.get("grainColumns")
    if not isinstance(grain, dict):
        raise ValueError("grainColumns must be an object")
    columns = {
        semantic: require_ident(grain.get(semantic), field=f"identity.{semantic}")
        for semantic in mapping.identity_fields
    }
    if len(set(columns.values())) != len(columns):
        raise ValueError("identity keys must map to distinct physical columns")
    return columns
''',
    flags=re.DOTALL,
)

replace(
    "src/semaloom/adapters/composite.py",
    "from semaloom.core.provider import ObjectRead, ObjectSearch, ReadProvider\n",
    "from semaloom.core.provider import IdentityScalar, IdentityValue, ObjectRead, ObjectSearch, ReadProvider\n",
)
replace(
    "src/semaloom/adapters/composite.py",
    "        identity_value: str,\n        extra_filters: dict[str, str] | None = None,\n",
    "        identity_value: IdentityValue,\n        bindings: dict[str, IdentityScalar] | None = None,\n",
)
replace(
    "src/semaloom/adapters/composite.py",
    "            identity_value=identity_value,\n            extra_filters=extra_filters,\n",
    "            identity_value=identity_value,\n            bindings=bindings,\n",
)
replace(
    "src/semaloom/adapters/composite.py",
    "        identity_value: str,\n    ) -> ObjectRead:\n",
    "        identity_value: IdentityValue,\n    ) -> ObjectRead:\n",
)

# OpenAPI keeps one plural parameter map and response grain pointers. Singular
# identity parameter/pointer fields are removed entirely.
replace(
    "src/semaloom/adapters/openapi.py",
    "from semaloom.core.provider import IdentityValue, ObjectRead\n",
    "from semaloom.core.provider import IdentityScalar, IdentityValue, ObjectRead, ObjectSearch\n",
)
replace(
    "src/semaloom/adapters/openapi.py",
    "        extra_filters: dict[str, str] | None = None,\n",
    "        bindings: dict[str, IdentityScalar] | None = None,\n",
)
replace(
    "src/semaloom/adapters/openapi.py",
    "            extra_filters=extra_filters,\n",
    "            bindings=bindings,\n",
)
replace(
    "src/semaloom/adapters/openapi.py",
    "        extra_filters: dict[str, str] | None = None,\n    ) -> Any | str:\n",
    "        bindings: dict[str, IdentityScalar] | None = None,\n    ) -> Any | str:\n",
)
regex(
    "src/semaloom/adapters/openapi.py",
    r'''        try:\n            identity_parameters = _identity_parameters\(mapping, identity_value\)\n        except ValueError:\n            return "INVALID_MAPPING"\n        if "tenant" in identity_parameters.values\(\):\n            return "INVALID_MAPPING"\n        params: dict\[str, Any\] = \{\*\*\(extra_filters or \{\}\), "tenant": tenant\}\n        for semantic, value in identity_value.items\(\):\n            parameter = identity_parameters\[semantic\]\n            if parameter == "tenant" or parameter in params and parameter != semantic:\n                return "INVALID_MAPPING"\n            params\[parameter\] = value\n''',
    '''        parameter_bindings = mapping.physical.get("parameterBindings")
        if not isinstance(parameter_bindings, dict):
            return "INVALID_MAPPING"
        params: dict[str, Any] = {**dict(mapping.physical.get("fixedParameters") or {}), "tenant": tenant}
        semantic_values: dict[str, IdentityScalar] = {**identity_value, **(bindings or {})}
        for semantic, value in semantic_values.items():
            parameter = parameter_bindings.get(semantic)
            if not isinstance(parameter, str) or not parameter or parameter == "tenant" or parameter in params:
                return "INVALID_MAPPING"
            params[parameter] = value
''',
)
regex(
    "src/semaloom/adapters/openapi.py",
    r'''def _identity_parameters\(mapping: MappingDef, identity_value: IdentityValue\) -> dict\[str, str\]:\n.*?\n\ndef _identity_pointers''',
    '''def _identity_pointers''',
    flags=re.DOTALL,
)
regex(
    "src/semaloom/adapters/openapi.py",
    r'''def _identity_pointers\(mapping: MappingDef, identity_value: IdentityValue\) -> dict\[str, str\]:\n.*?    return pointers\n''',
    '''def _identity_pointers(mapping: MappingDef, identity_value: IdentityValue) -> dict[str, str]:
    if set(identity_value) != set(mapping.identity_fields):
        raise ValueError("identity does not match compiled mapping")
    grain = mapping.physical.get("grainPointers")
    if not isinstance(grain, dict):
        raise ValueError("grainPointers must be an object")
    pointers: dict[str, str] = {}
    for semantic in mapping.identity_fields:
        pointer = grain.get(semantic)
        if not isinstance(pointer, str) or not pointer:
            raise ValueError("invalid identity pointer")
        pointers[semantic] = pointer
    return pointers
''',
    flags=re.DOTALL,
)
# OpenAPI collection search is an explicit capability miss, not duck-typed absence.
replace(
    "src/semaloom/adapters/openapi.py",
    "    def close(self) -> None:\n",
    '''    def search_objects(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        filters: dict[str, Any],
        properties: tuple[str, ...],
        limit: int,
    ) -> ObjectSearch:
        return ObjectSearch(kind="UNAVAILABLE", reason="SEARCH_NOT_SUPPORTED", observed_at=_now())

    def close(self) -> None:
''',
)

# ---------------------------------------------------------------------------
# Runtime: semantic fields only. No physical Mapping inspection and no alias
# normalization. Exact canonical identity is required at every point-read gate.
# ---------------------------------------------------------------------------
regex(
    "src/semaloom/runtime/query.py",
    r'''            if isinstance\(item, MetricSelect\):\n                try:\n                    item = item\.model_copy\(update=\{"bindings": self\.normalize_bindings\(item\)\}\)\n                except ValueError:\n.*?                    continue\n                metric = ''',
    '''            if isinstance(item, MetricSelect):
                metric = ''',
    flags=re.DOTALL,
)
regex(
    "src/semaloom/runtime/query.py",
    r'''    def normalize_bindings\(self, item: MetricSelect\) -> dict\[str, str \| int\]:\n.*?\n    def _check_metric_period''',
    "    def _check_metric_period",
    flags=re.DOTALL,
)
replace(
    "src/semaloom/runtime/query.py",
    "        source_identity: str | dict[str, str],\n",
    "        source_identity: IdentityValue,\n",
)
regex(
    "src/semaloom/runtime/query.py",
    r'''        source_obj = next\(item for item in self\.bundle\.object_types if item\.id == link\.source\)\n        target_obj = next\(item for item in self\.bundle\.object_types if item\.id == link\.target\)\n        if isinstance\(source_identity, dict\):\n.*?                status="FAILED",\n            \)\n        source_mapping, source_error = ''',
    '''        source_obj = next(item for item in self.bundle.object_types if item.id == link.source)
        target_obj = next(item for item in self.bundle.object_types if item.id == link.target)
        if set(source_identity) != set(source_obj.identity_keys):
            return EvidenceEnvelope(
                request_id=request_id,
                release_digest=self.bundle.digest,
                observations=(),
                diagnostics=(
                    Diagnostic(
                        code="INVALID_BINDINGS",
                        path=link_id,
                        message="source identity must contain every declared identity component",
                    ),
                ),
                status="FAILED",
            )
        source_identity_value: IdentityValue = {
            key: source_identity[key] for key in source_obj.identity_keys
        }
        source_mapping, source_error = ''',
    flags=re.DOTALL,
)
replace(
    "src/semaloom/runtime/query.py",
    '''        allowed = set(metric_def.grain)
        grain = _grain_columns(mapping)
        identity_columns = {grain[key] for key in identity_value if key in grain}
        extra = {
            grain[key]: str(value)
            for key, value in item.bindings.items()
            if key in allowed and key in grain and grain[key] not in identity_columns
        }
        observation = self.provider.fetch_metric(
            mapping,
            tenant=tenant,
            identity_value=identity_value,
            extra_filters=extra or None,
        )
''',
    '''        bindings = {
            key: value
            for key, value in item.bindings.items()
            if key in metric_def.grain and key not in identity_value
        }
        observation = self.provider.fetch_metric(
            mapping,
            tenant=tenant,
            identity_value=identity_value,
            bindings=bindings or None,
        )
''',
)
regex(
    "src/semaloom/runtime/query.py",
    r'''def _grain_columns\(mapping: MappingDef\) -> dict\[str, str\]:\n.*?\n\ndef _descriptive_object_fields''',
    '''def _descriptive_object_fields''',
    flags=re.DOTALL,
)
regex(
    "src/semaloom/runtime/query.py",
    r'''def _descriptive_object_fields\(\n    mapping: MappingDef, measure_ids: set\[str\], identity: set\[str\]\n\) -> set\[str\]:\n.*?    return fields - measure_ids - identity\n''',
    '''def _descriptive_object_fields(
    mapping: MappingDef, measure_ids: set[str], identity: set[str]
) -> set[str]:
    return set(mapping.property_fields) - measure_ids - identity
''',
    flags=re.DOTALL,
)
regex(
    "src/semaloom/runtime/query.py",
    r'''def _mapped_object_fields\(mapping: MappingDef\) -> set\[str\]:\n.*?    return fields\n''',
    '''def _mapped_object_fields(mapping: MappingDef) -> set[str]:
    return set(mapping.grain_fields) | set(mapping.property_fields)
''',
    flags=re.DOTALL,
)

replace(
    "src/semaloom/app/chat/tools.py",
    "            bindings = self.query.normalize_bindings(item)\n",
    "            bindings = dict(item.bindings)\n",
)
replace(
    "src/semaloom/app/chat/tools.py",
    "        self._identity(metric.object_type, self.query.normalize_bindings(selection))\n",
    "        self._identity(metric.object_type, selection.bindings)\n",
)

# Studio preview accepts one exact identity object. Extra metric bindings remain
# semantic until the adapter boundary.
replace(
    "src/semaloom/runtime/studio.py",
    '''    for key in ("identityColumn", "valueColumn", "identityPointer", "valuePointer"):
        value = physical.get(key)
        if isinstance(value, str):
            fields.add(value)
    for key in (
        "identityColumns",
        "identityPointers",
        "grainColumns",
''',
    '''    for key in ("valueColumn", "valuePointer"):
        value = physical.get(key)
        if isinstance(value, str):
            fields.add(value)
    for key in (
        "grainColumns",
''',
)
replace(
    "src/semaloom/runtime/studio.py",
    "    identity_fields = _identity_fields(mapping)\n",
    "    identity_fields = list(mapping.identity_fields)\n",
)
replace(
    "src/semaloom/runtime/studio.py",
    "    identity: str,\n",
    "    identity: IdentityValue,\n",
)
regex(
    "src/semaloom/runtime/studio.py",
    r'''    object_type = next\(\(item for item in bundle\.object_types if item\.id == mapping\.object_type\), None\)\n    if object_type is None or not object_type\.identity_keys:\n        return None\n    supplied = dict\(bindings or \{\}\)\n    identity_value: IdentityValue = \{object_type\.identity_keys\[0\]: identity\}\n    for key in object_type\.identity_keys\[1:\]:\n.*?        identity_value\[key\] = value\n''',
    '''    object_type = next((item for item in bundle.object_types if item.id == mapping.object_type), None)
    if object_type is None or set(identity) != set(object_type.identity_keys):
        raise ValueError("INVALID_IDENTITY")
    identity_value: IdentityValue = {key: identity[key] for key in object_type.identity_keys}
    supplied = dict(bindings or {})
''',
    flags=re.DOTALL,
)
replace(
    "src/semaloom/runtime/studio.py",
    "    extra = _preview_extra_filters(mapping, supplied, set(object_type.identity_keys))\n",
    '''    extra = {
        key: value
        for key, value in supplied.items()
        if key in mapping.grain_fields and key not in identity_value
    }
''',
)
replace(
    "src/semaloom/runtime/studio.py",
    "            mapping, tenant=tenant, identity_value=identity_value, extra_filters=extra or None\n",
    "            mapping, tenant=tenant, identity_value=identity_value, bindings=extra or None\n",
)
regex(
    "src/semaloom/runtime/studio.py",
    r'''\ndef _identity_fields\(mapping: MappingDef\) -> list\[str\]:\n.*?\n\ndef _required_preview_bindings''',
    "\ndef _required_preview_bindings",
    flags=re.DOTALL,
)
regex(
    "src/semaloom/runtime/studio.py",
    r'''def _required_preview_bindings\(\n    mapping: MappingDef, identity_fields: list\[str\] \| None = None\n\) -> list\[str\]:\n.*?    return required\n\n\ndef _preview_extra_filters\(.*?    return extra\n''',
    '''def _required_preview_bindings(
    mapping: MappingDef, identity_fields: list[str] | None = None
) -> list[str]:
    identity = set(identity_fields or mapping.identity_fields)
    return [field for field in mapping.grain_fields if field not in identity]
''',
    flags=re.DOTALL,
)

replace(
    "src/semaloom/app/http.py",
    "    identity: str\n",
    "    identity: dict[str, str | int | bool]\n",
)
replace(
    "src/semaloom/app/http.py",
    '''                ObjectSelect(
                    object_type=object_id,
                    identity={object_type.identity_keys[0]: body.identity},
                    properties=tuple(body.properties),
                ),
''',
    '''                ObjectSelect(
                    object_type=object_id,
                    identity={key: str(body.identity[key]) for key in object_type.identity_keys},
                    properties=tuple(body.properties),
                ),
''',
)
replace(
    "src/semaloom/app/http.py",
    "    envelope = QueryService(bundle, request.app.state.services.provider).execute(\n",
    '''    if set(body.identity) != set(object_type.identity_keys):
        raise HTTPException(status_code=422, detail="INVALID_IDENTITY")
    envelope = QueryService(bundle, request.app.state.services.provider).execute(
''',
)

# ---------------------------------------------------------------------------
# Source mappings: compiler owns capabilities; canonical identity lives in the
# semantic grain. OpenAPI uses plural identityParameters only.
# ---------------------------------------------------------------------------
for path in (ROOT / "examples").rglob("*.yaml"):
    text = path.read_text()
    text = re.sub(r"(?m)^\s*capabilities:\s*\[[^\n]*\]\n", "", text)
    text = re.sub(r"(?m)^\s*identityColumn:\s*[^\n]+\n", "", text)
    text = re.sub(
        r"(?m)^(\s*)identityParameter:\s*([^\s#]+)\n\1identityPointer:\s*[^\n]+\n",
        lambda match: f"{match.group(1)}identityParameters:\n{match.group(1)}  {match.group(2)}: {match.group(2)}\n",
        text,
    )
    path.write_text(text)

# Remove the redundant tax alias that existed only to support scalar legacy binding.
tax_binding = "examples/tax/integration/bindings.yaml"
text = read(tax_binding)
text = text.replace("      taxpayer: taxpayer_id\n", "")
write(tax_binding, text)

# ---------------------------------------------------------------------------
# Frontend draft contract: all identity components are edited and previewed as
# one object. No source-authored capabilities and no singular identity fields.
# ---------------------------------------------------------------------------
regex(
    "frontend/src/doc.ts",
    r'''export function defaultMappingCapabilities\(provider: string\): string\[\] \{.*?\nexport function metricById''',
    '''function identityList(identityKeys: string[]): string[] {
  return identityKeys.map(String).filter(Boolean);
}

export function emptyMappingPhysical(
  provider: string,
  identityKeys: string[],
): Record<string, unknown> {
  const identities = identityList(identityKeys);
  if (provider === "openapi") {
    return {
      method: "GET",
      path: "",
      operationId: "",
      identityParameters: Object.fromEntries(identities.map((key) => [key, key])),
      grainPointers: Object.fromEntries(identities.map((key) => [key, `/${key}`])),
      propertyPointers: {},
    };
  }
  return {
    table: "",
    tenantColumn: "tenant_id",
    grainColumns: Object.fromEntries(identities.map((key) => [key, ""])),
    propertyColumns: {},
  };
}

export function emptyMetricPhysical(
  provider: string,
  identityKeys: string[],
  grain: string[],
): Record<string, unknown> {
  const identities = identityList(identityKeys);
  const dims = grain.length ? grain : identities;
  if (provider === "openapi") {
    const grainPointers = Object.fromEntries(dims.map((dim) => [dim, `/${dim}`]));
    return {
      method: "GET",
      path: "",
      operationId: "",
      identityParameters: Object.fromEntries(identities.map((key) => [key, key])),
      valuePointer: "/value",
      grainPointers,
    };
  }
  return {
    table: "",
    tenantColumn: "tenant_id",
    valueColumn: "",
    grainColumns: Object.fromEntries(dims.map((dim) => [dim, ""])),
    filters: {},
  };
}

export function metricById''',
    flags=re.DOTALL,
)
replace(
    "frontend/src/types.ts",
    "  identityField: string;\n  requiredBindings: string[];\n",
    "  identityField: string;\n  identityFields: string[];\n  capabilities: string[];\n  requiredBindings: string[];\n",
)

# MappingEditor is already composite-state capable on this branch; remove its
# compatibility physical fields and compiler-owned capability authoring.
text = read("frontend/src/MappingEditor.tsx")
text = text.replace("  defaultMappingCapabilities,\n", "")
text = text.replace("      capabilities: defaultMappingCapabilities(provider),\n", "")
text = text.replace("    if (text(physical.identityColumn)) found.add(text(physical.identityColumn));\n", "")
text = text.replace("    for (const value of Object.values(object(physical.identityColumns))) {\n      if (value) found.add(String(value));\n    }\n", "")
text = text.replace(
    '''    const parameter = resource?.parameters?.[0]?.name || text(physical.identityParameter) || identityKey;
    const previous = object(physical.identityParameters);
''',
    '''    const previous = object(physical.identityParameters);
''',
)
text = text.replace("        identityParameter: parameter,\n", "")
text = text.replace(
    '''            identityPointer: identityField && semantic === identityKeys[0] ? value : physical.identityPointer,
            identityPointers: identityField
              ? { ...object(physical.identityPointers), [semantic]: value }
              : object(physical.identityPointers),
            grainPointers,
''',
    '''            grainPointers,
''',
)
text = text.replace(
    '''          identityColumn: identityField && semantic === identityKeys[0] ? value : physical.identityColumn,
          identityColumns: identityField
            ? { ...object(physical.identityColumns), [semantic]: value }
            : object(physical.identityColumns),
          grainColumns: { ...grain, [semantic]: value },
''',
    '''          grainColumns: { ...grain, [semantic]: value },
''',
)
text = text.replace(
    '''    const next: Record<string, string> = {};
    for (const key of identityKeys) {
      const column = text(grain[key]) || text(object(physical.identityColumns)[key]) || (key === identityKeys[0] ? text(physical.identityColumn) : "");
      if (column && row[column] != null) next[key] = String(row[column]);
    }
''',
    '''    const next: Record<string, string> = {};
    for (const key of identityKeys) {
      const column = text(grain[key]);
      if (column && row[column] != null) next[key] = String(row[column]);
    }
''',
)
text = re.sub(
    r'''          \{!compact && api \? \(\n            <label className="form-field">\n              <span>身份参数</span>.*?            </label>\n          \) : null\}\n''',
    '''          {!compact && api ? identityKeys.map((key) => (
            <label className="form-field" key={key}>
              <span>身份参数 {key}</span>
              <select
                aria-label={`身份参数 ${key}`}
                value={text(object(physical.identityParameters)[key])}
                onChange={(event) => setPhysical(openApiPhysical(physical, {
                  identityParameters: { ...object(physical.identityParameters), [key]: event.target.value },
                }, metricMode))}
              >
                {(parameters.length ? parameters : [{ name: key }]).map((item) => (
                  <option key={item.name} value={item.name}>{item.name}</option>
                ))}
              </select>
            </label>
          )) : null}
''',
    text,
    count=1,
    flags=re.DOTALL,
)
text = text.replace(
    '''          identityPointer: identityField ? column : physical.identityPointer,
          grainPointers,
''',
    '''          grainPointers,
''',
)
text = text.replace(
    '''        identityColumn: identityField ? column : physical.identityColumn,
        grainColumns,
''',
    '''        grainColumns,
''',
)
text = text.replace(
    '''    identityColumn: patch.identityColumn !== undefined ? patch.identityColumn : physical.identityColumn,
    identityColumns: patch.identityColumns !== undefined ? patch.identityColumns : object(physical.identityColumns),
    grainColumns:''',
    '''    grainColumns:''',
)
text = text.replace(
    '''    identityPointer: patch.identityPointer !== undefined ? patch.identityPointer : physical.identityPointer,
    identityParameters: patch.identityParameters !== undefined ? patch.identityParameters : object(physical.identityParameters),
    identityPointers: patch.identityPointers !== undefined ? patch.identityPointers : object(physical.identityPointers),
    grainPointers:''',
    '''    identityParameters: patch.identityParameters !== undefined ? patch.identityParameters : object(physical.identityParameters),
    grainPointers:''',
)
text = text.replace("    capabilities: defaultMappingCapabilities(provider),\n", "")
text = text.replace("    const identityKey = identityKeys[0] ?? \"id\";\n", "")
text = text.replace("emptyMappingPhysical(provider, identityKey)", "emptyMappingPhysical(provider, identityKeys)")
text = text.replace("emptyMetricPhysical(provider, identityKey, grain)", "emptyMetricPhysical(provider, identityKeys, grain)")
# Required metric preview bindings are semantic; identity fields are excluded directly.
text = text.replace("  const identityCol = text(physical.identityColumn);\n", "")
text = text.replace(
    "    if (identityKeys.includes(semantic) || String(column) === identityCol || locked.has(semantic) || locked.has(String(column))) {\n",
    "    if (identityKeys.includes(semantic) || locked.has(semantic) || locked.has(String(column))) {\n",
)
write("frontend/src/MappingEditor.tsx", text)

# PropertyMappingSheet: exact composite preview identity and plural API parameters.
text = read("frontend/src/PropertyMappingSheet.tsx")
text = text.replace("  const [identity, setIdentity] = useState(\"\");\n", "  const [identity, setIdentity] = useState<Record<string, string>>({});\n")
text = text.replace("    setIdentity(\"\");\n", "    setIdentity({});\n")
text = text.replace("  const canPreview = saved && Boolean(identity.trim()) && hasResource;\n", "  const canPreview = saved && identityKeys.length > 0 && identityKeys.every((key) => Boolean(text(identity[key]).trim())) && hasResource;\n")
text = text.replace("    const identityKey = identityKeys[0] ?? \"id\";\n", "")
text = text.replace("      physical: emptyMappingPhysical(provider, identityKey),\n", "      physical: emptyMappingPhysical(provider, identityKeys),\n")
text = text.replace(
    '''    const identityCol = text(focusedPhysical.identityColumn) || focusedColumns[0]?.name;
    if (identityCol && row[identityCol]) setIdentity(String(row[identityCol]));
''',
    '''    const next: Record<string, string> = {};
    for (const key of identityKeys) {
      const column = focused ? columnOf(focused, key, identityKeys) : "";
      if (column && row[column] != null) next[key] = String(row[column]);
    }
    if (Object.keys(next).length) setIdentity(next);
''',
)
text = text.replace(
    '''    const identity = text(focusedPhysical.identityColumn) || text(focusedPhysical.identityPointer);
    if (identity) names.add(identity);
''',
    "",
)
text = re.sub(
    r'''            \{focusedApi \? \(\n              <label className="form-field"><span>身份参数</span>.*?              </label>\n            \) : null\}\n''',
    '''            {focusedApi ? identityKeys.map((key) => (
              <label className="form-field" key={key}><span>身份参数 {key}</span>
                <select
                  aria-label={`身份参数 ${key}`}
                  value={text(object(focusedPhysical.identityParameters)[key])}
                  onChange={(event) => patchFocused({
                    ...focused,
                    physical: {
                      ...focusedPhysical,
                      identityParameters: { ...object(focusedPhysical.identityParameters), [key]: event.target.value },
                    },
                  })}
                >
                  {(parameters.length ? parameters : [{ name: key }]).map((item) => (
                    <option key={item.name} value={item.name}>{item.name}</option>
                  ))}
                </select>
              </label>
            )) : null}
''',
    text,
    count=1,
    flags=re.DOTALL,
)
text = re.sub(
    r'''              <label className="form-field">\n                <span>试读业务键</span>\n                <input value=\{identity\} placeholder="例如 PO-001" onChange=\{\(event\) => setIdentity\(event\.target\.value\)\} />\n              </label>''',
    '''              {identityKeys.map((key) => (
                <label className="form-field" key={key}>
                  <span>试读业务键 {key}</span>
                  <input
                    value={text(identity[key])}
                    placeholder={key}
                    onChange={(event) => setIdentity((current) => ({ ...current, [key]: event.target.value }))}
                  />
                </label>
              ))}''',
    text,
    count=1,
)
text = text.replace(
    '''  if (identityKeys[0] === propertyId) {
    return text(physical.identityColumn) || text(physical.identityPointer);
  }
''',
    "",
)
write("frontend/src/PropertyMappingSheet.tsx", text)

# MappingEditor helper functions still carried compatibility fields from the first pass.
for path in ("frontend/src/MappingEditor.tsx", "frontend/src/PropertyMappingSheet.tsx"):
    text = read(path)
    for forbidden in ("identityColumn", "identityColumns", "identityPointer", "identityPointers", "identityParameter"):
        if forbidden in text:
            print(f"NOTE: {path} still contains {forbidden}; boundary assertion will catch it")

# ---------------------------------------------------------------------------
# Canonical identity name migration in tests. `taxpayer` remains valid prose;
# only machine binding keys move to taxpayerId.
# ---------------------------------------------------------------------------
for path in (ROOT / "tests").rglob("*.py"):
    text = path.read_text()
    text = text.replace("taxpayer=\"TAXPAYER-", "taxpayerId=\"TAXPAYER-")
    text = text.replace('"taxpayer": "TAXPAYER-', '"taxpayerId": "TAXPAYER-')
    text = text.replace('"taxpayer": taxpayer,', '"taxpayerId": taxpayer,')
    text = text.replace("source_identity=\"PO-001\"", 'source_identity={"orderId": "PO-001"}')
    text = text.replace("identity_value: str", "identity_value: IdentityValue")
    path.write_text(text)

# Provider test stubs use the same protocol type.
provider_test = "tests/test_provider_contract.py"
text = read(provider_test)
text = text.replace("from semaloom.core.provider import ObjectRead\n", "from semaloom.core.provider import IdentityValue, ObjectRead\n")
write(provider_test, text)

write(
    "tests/test_composite_identity_chain.py",
    '''from __future__ import annotations

import pytest

from semaloom.app.chat.tools import SemanticTools
from semaloom.compiler.api import compile_documents
from semaloom.core.model import MappingDef
from semaloom.core.provider import IdentityScalar, IdentityValue, ObjectRead, ObjectSearch
from semaloom.core.results import ObjectSelect, Observation, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService
from semaloom.runtime.studio import studio_mapping_preview

ACTOR = RequestActor(tenant="tenant-a", subject="reader", roles=("analyst",))


class FakeProvider:
    def __init__(self) -> None:
        self.last_identity: IdentityValue | None = None

    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
        bindings: dict[str, IdentityScalar] | None = None,
    ) -> Observation:
        raise AssertionError("metric read not expected")

    def fetch_object(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
    ) -> ObjectRead:
        self.last_identity = dict(identity_value)
        return ObjectRead(
            kind="PRESENT",
            values={**identity_value, "name": "Journal entry"},
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            observed_at="2026-09-16T00:00:00Z",
        )

    def search_objects(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        filters: dict[str, object],
        properties: tuple[str, ...],
        limit: int,
    ) -> ObjectSearch:
        return ObjectSearch(
            kind="PRESENT",
            rows=({"ledger": "0L", "entryId": "E-1", "name": "Journal entry"},),
            observed_at="2026-09-16T00:00:00Z",
        )


def _documents() -> list[dict[str, object]]:
    return [
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "DomainPack",
            "id": "demo",
            "version": "1.0.0",
            "contractVersion": "v0.1",
            "namespace": "demo",
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "ObjectType",
            "id": "demo.Entry",
            "version": "1.0.0",
            "identityKeys": ["ledger", "entryId"],
            "properties": [
                {"id": "ledger", "valueType": "STRING", "required": True},
                {"id": "entryId", "valueType": "STRING", "required": True},
                {"id": "name", "valueType": "STRING"},
            ],
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Mapping",
            "id": "demo.Entry.pg",
            "version": "1.0.0",
            "target": "demo.Entry",
            "sourceId": "demo_pg",
            "provider": "postgres",
            "objectType": "demo.Entry",
            "expectedCardinality": "ONE",
            "physical": {
                "table": "entry",
                "grainColumns": {"ledger": "ledger", "entryId": "entry_id"},
                "propertyColumns": {"name": "name"},
            },
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "IntegrationBinding",
            "id": "demo.postgres",
            "version": "1.0.0",
            "provider": "postgres",
            "sourceId": "demo_pg",
            "mappings": ["demo.Entry.pg"],
        },
    ]


def _bundle():
    result = compile_documents(_documents())
    assert result.ok, result.diagnostics
    assert result.bundle is not None
    return result.bundle


def test_compiler_emits_neutral_mapping_ir() -> None:
    mapping = _bundle().mappings[0]
    assert mapping.identity_fields == ("ledger", "entryId")
    assert mapping.grain_fields == ("ledger", "entryId")
    assert mapping.property_fields == ("name",)
    assert mapping.capabilities == ("POINT_READ", "COLLECTION_READ", "EQUI_JOIN")


def test_compiler_rejects_legacy_scalar_identity_mapping_fields() -> None:
    docs = _documents()
    mapping = next(item for item in docs if item.get("kind") == "Mapping")
    physical = dict(mapping["physical"])
    physical["identityColumn"] = "entry_id"
    mapping["physical"] = physical
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "LEGACY_MAPPING_FIELD" for item in result.diagnostics)


def test_query_studio_and_ai_share_exact_composite_identity() -> None:
    bundle = _bundle()
    provider = FakeProvider()
    query = QueryService(bundle, provider)
    identity = {"ledger": "0L", "entryId": "E-1"}
    envelope = query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(ObjectSelect(object_type="demo.Entry", identity=identity, properties=("name",)),),
            context=QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"}),
        ),
        ACTOR,
    )
    assert envelope.status == "SUCCEEDED"
    assert provider.last_identity == identity

    preview = studio_mapping_preview(
        bundle,
        provider,
        mapping_id="demo.Entry.pg",
        tenant="tenant-a",
        identity=identity,
    )
    assert preview is not None
    assert preview["kind"] == "PRESENT"
    assert preview["identity"] == identity

    tools = SemanticTools(query, ACTOR)
    found = tools.call(
        "find_objects",
        {"objectType": "demo.Entry", "filters": {"name": "Journal entry"}, "properties": ["name"]},
    )
    assert found["objects"][0]["identity"] == identity
    tools.call(
        "semantic_query",
        {
            "apiVersion": "semaloom/v0.1",
            "select": [{"objectType": "demo.Entry", "identity": identity, "properties": ["name"]}],
            "context": {"businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"}},
        },
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_IDENTITY"):
        tools.call(
            "semantic_query",
            {
                "apiVersion": "semaloom/v0.1",
                "select": [
                    {"objectType": "demo.Entry", "identity": {"entryId": "E-1"}, "properties": ["name"]}
                ],
                "context": {"businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"}},
            },
        )
''',
)

# Public docs: identity is an exact business-key object; capabilities are compiled.
text = read("README.md")
text = text.replace(
    "MCP SDK transport (`GET /v0.1/mcp/tools` is a static name list), composite-key query, BOOLEAN /",
    "MCP SDK transport (`GET /v0.1/mcp/tools` is a static name list), composite-key Link traversal, BOOLEAN /",
)
write("README.md", text)

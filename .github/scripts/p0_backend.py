from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def edit(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"missing replacement in {path}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1))


def append_before(path: str, marker: str, block: str) -> None:
    edit(path, marker, block + marker)


# --- semantic model: explicit identity + provider-neutral capabilities ---
edit(
    "src/semaloom/core/model.py",
    'Aggregation = Literal["NONE", "SUM", "MAX", "MIN"]\nPolicyEnd = str | None\n',
    'Aggregation = Literal["NONE", "SUM", "MAX", "MIN"]\n'
    'IdentityNormalization = Literal["NONE", "TRIM", "CASEFOLD"]\n'
    'MappingCapability = Literal[\n'
    '    "POINT_READ",\n'
    '    "OBJECT_SEARCH",\n'
    '    "COLLECTION_QUERY",\n'
    '    "RELATIONAL_JOIN",\n'
    '    "BATCH_KEY_LOOKUP",\n'
    ']\n'
    'PolicyEnd = str | None\n',
)
edit(
    "src/semaloom/core/model.py",
    'class EmbeddedProperty(BaseModel):\n',
    'class IdentityComponent(BaseModel):\n'
    '    model_config = wire_config()\n\n'
    '    property: str\n'
    '    normalization: IdentityNormalization = "NONE"\n\n\n'
    'class ObjectIdentityDef(BaseModel):\n'
    '    """Stable business identity; components are ordered and tenant-scoped by default."""\n\n'
    '    model_config = wire_config()\n\n'
    '    components: tuple[IdentityComponent, ...]\n'
    '    scope: Literal["TENANT"] = "TENANT"\n\n\n'
    'class EmbeddedProperty(BaseModel):\n',
)
edit(
    "src/semaloom/core/model.py",
    'class ObjectTypeDef(_Doc):\n    kind: Literal["ObjectType"] = "ObjectType"\n    identity_keys: tuple[str, ...]\n    properties: tuple[EmbeddedProperty, ...]\n',
    'class ObjectTypeDef(_Doc):\n    kind: Literal["ObjectType"] = "ObjectType"\n    identity_keys: tuple[str, ...]\n    identity: ObjectIdentityDef | None = None\n    properties: tuple[EmbeddedProperty, ...]\n',
)
edit(
    "src/semaloom/core/model.py",
    'class MappingDef(_Doc):\n    kind: Literal["Mapping"] = "Mapping"\n    target: str\n    source_id: str\n    provider: str\n    object_type: str\n    perspective: str | None = None\n    expected_cardinality: Cardinality\n    completeness: Literal["AUTHORITATIVE", "PARTIAL"] = "PARTIAL"\n    physical: dict[str, Any]\n',
    'class MappingDef(_Doc):\n    kind: Literal["Mapping"] = "Mapping"\n    target: str\n    source_id: str\n    provider: str\n    object_type: str\n    perspective: str | None = None\n    expected_cardinality: Cardinality\n    completeness: Literal["AUTHORITATIVE", "PARTIAL"] = "PARTIAL"\n    identity_fields: tuple[str, ...] = ()\n    capabilities: tuple[MappingCapability, ...] = ()\n    physical: dict[str, Any]\n',
)

# --- compiler materializes a neutral runtime contract (legacy DSL remains accepted) ---
edit(
    "src/semaloom/compiler/api.py",
    '    metrics = _metrics_from_properties(objects, metrics, mappings)\n',
    '    mappings = _materialize_mapping_contracts(objects, mappings)\n'
    '    metrics = _metrics_from_properties(objects, metrics, mappings)\n',
)
append_before(
    "src/semaloom/compiler/api.py",
    'def _metrics_from_properties(\n',
    '''def _materialize_mapping_contracts(\n    objects: Sequence[ObjectTypeDef], mappings: Sequence[MappingDef]\n) -> list[MappingDef]:\n    """Compile legacy physical declarations into an explicit, provider-neutral capability IR.\n\n    v0.1 still accepts existing mapping YAML. Runtime and AI discovery consume only the\n    materialized identity/capability contract, so new adapters do not require runtime branches.\n    """\n    object_index = _index(objects)\n    materialized: list[MappingDef] = []\n    for mapping in mappings:\n        updates: dict[str, Any] = {}\n        obj = object_index.get(mapping.object_type)\n        if not mapping.identity_fields and obj is not None:\n            updates["identity_fields"] = tuple(obj.identity_keys)\n        if not mapping.capabilities:\n            physical = mapping.physical\n            # This is a compatibility compiler for existing v0.1 declarations. New provider\n            # validators may emit the same neutral capabilities without changing Runtime.\n            if isinstance(physical.get("table"), str):\n                updates["capabilities"] = (\n                    "POINT_READ",\n                    "OBJECT_SEARCH",\n                    "COLLECTION_QUERY",\n                    "RELATIONAL_JOIN",\n                    "BATCH_KEY_LOOKUP",\n                )\n            else:\n                updates["capabilities"] = ("POINT_READ",)\n        materialized.append(mapping.model_copy(update=updates) if updates else mapping)\n    return materialized\n\n\n''',
)
edit(
    "src/semaloom/compiler/api.py",
    '                        "completeness": source.completeness,\n                        "physical": physical,\n',
    '                        "completeness": source.completeness,\n'
    '                        "identityFields": list(source.identity_fields),\n'
    '                        "capabilities": list(source.capabilities),\n'
    '                        "physical": physical,\n',
)
edit(
    "src/semaloom/compiler/api.py",
    '    for obj in objects:\n        prop_ids = [prop.id for prop in obj.properties]\n',
    '    for obj in objects:\n'
    '        prop_ids = [prop.id for prop in obj.properties]\n'
    '        if not obj.identity_keys:\n'
    '            diagnostics.append(\n'
    '                Diagnostic(code="INVALID_IDENTITY", path=obj.id, message="identityKeys must not be empty")\n'
    '            )\n'
    '        if obj.identity is not None:\n'
    '            components = tuple(item.property for item in obj.identity.components)\n'
    '            if components != obj.identity_keys:\n'
    '                diagnostics.append(\n'
    '                    Diagnostic(\n'
    '                        code="INVALID_IDENTITY",\n'
    '                        path=f"{obj.id}.identity",\n'
    '                        message="identity components must match identityKeys in declared order",\n'
    '                    )\n'
    '                )\n'
    '            property_types = {prop.id: prop.value_type for prop in obj.properties}\n'
    '            for component in obj.identity.components:\n'
    '                if component.normalization != "NONE" and property_types.get(component.property) != "STRING":\n'
    '                    diagnostics.append(\n'
    '                        Diagnostic(\n'
    '                            code="TYPE_MISMATCH",\n'
    '                            path=f"{obj.id}.identity.{component.property}",\n'
    '                            message="identity normalization is only valid for STRING properties",\n'
    '                        )\n'
    '                    )\n',
)

# --- provider contract: identity is an ordered semantic map, not one scalar ---
edit(
    "src/semaloom/core/provider.py",
    'from semaloom.core.results import Observation\n',
    'from semaloom.core.results import Observation\n\n'
    'IdentityValue = str | int | bool\n'
    'ObjectIdentity = dict[str, IdentityValue]\n',
)
edit(
    "src/semaloom/core/provider.py",
    '        tenant: str,\n        identity_value: str,\n        extra_filters: dict[str, str] | None = None,\n',
    '        tenant: str,\n        identity: ObjectIdentity,\n        extra_filters: dict[str, str] | None = None,\n',
)
edit(
    "src/semaloom/core/provider.py",
    '        tenant: str,\n        identity_value: str,\n    ) -> ObjectRead: ...\n',
    '        tenant: str,\n        identity: ObjectIdentity,\n    ) -> ObjectRead: ...\n',
)

# --- PostgreSQL provider: composite predicates, legacy scalar keyword remains accepted ---
edit(
    "src/semaloom/adapters/postgres.py",
    'from semaloom.core.provider import ObjectRead, ObjectSearch\n',
    'from semaloom.core.provider import ObjectIdentity, ObjectRead, ObjectSearch\n',
)
edit(
    "src/semaloom/adapters/postgres.py",
    '        tenant: str,\n        identity_value: str,\n        extra_filters: dict[str, str] | None = None,\n    ) -> Observation:\n',
    '        tenant: str,\n        identity: ObjectIdentity | None = None,\n        identity_value: str | None = None,\n        extra_filters: dict[str, str] | None = None,\n    ) -> Observation:\n',
)
edit(
    "src/semaloom/adapters/postgres.py",
    '            identity_col = require_ident(physical.get("identityColumn"), field="identityColumn")\n            value_col = require_ident(physical.get("valueColumn"), field="valueColumn")\n',
    '            resolved_identity = _coerce_identity(mapping, identity, identity_value)\n'
    '            identity_clauses, identity_params = _identity_predicates(mapping, resolved_identity)\n'
    '            value_col = require_ident(physical.get("valueColumn"), field="valueColumn")\n',
)
edit(
    "src/semaloom/adapters/postgres.py",
    '            params: dict[str, Any] = {"tenant": tenant, "identity": identity_value}\n            clauses = [f"{identity_col} = :identity", f"{tenant_col} = :tenant"]\n',
    '            params: dict[str, Any] = {"tenant": tenant, **identity_params}\n'
    '            clauses = [*identity_clauses, f"{tenant_col} = :tenant"]\n',
)
edit(
    "src/semaloom/adapters/postgres.py",
    '        tenant: str,\n        identity_value: str,\n    ) -> ObjectRead:\n',
    '        tenant: str,\n        identity: ObjectIdentity | None = None,\n        identity_value: str | None = None,\n    ) -> ObjectRead:\n',
)
edit(
    "src/semaloom/adapters/postgres.py",
    '            identity_col = require_ident(\n                mapping.physical.get("identityColumn"), field="identityColumn"\n            )\n            tenant_col = require_ident(\n',
    '            resolved_identity = _coerce_identity(mapping, identity, identity_value)\n'
    '            identity_clauses, identity_params = _identity_predicates(mapping, resolved_identity)\n'
    '            tenant_col = require_ident(\n',
)
edit(
    "src/semaloom/adapters/postgres.py",
    '            sql = text(\n                f"SELECT {selected} FROM {table} WHERE {identity_col} = :identity "\n                f"AND {tenant_col} = :tenant LIMIT 2"\n            )\n            with _read_transaction(engine) as conn:\n                rows = (\n                    conn.execute(sql, {"identity": identity_value, "tenant": tenant})\n',
    '            sql = text(\n'
    '                f"SELECT {selected} FROM {table} WHERE {\' AND \'.join(identity_clauses)} "\n'
    '                f"AND {tenant_col} = :tenant LIMIT 2"\n'
    '            )\n'
    '            with _read_transaction(engine) as conn:\n'
    '                rows = (\n'
    '                    conn.execute(sql, {"tenant": tenant, **identity_params})\n',
)
edit(
    "src/semaloom/adapters/postgres.py",
    '            identity_col = require_ident(\n                mapping.physical.get("identityColumn"), field="identityColumn"\n            )\n            if not properties or (set(properties) | set(filters)) - set(projection):\n',
    '            identity_order = _identity_columns(mapping)\n'
    '            if not identity_order:\n'
    '                legacy = require_ident(\n'
    '                    mapping.physical.get("identityColumn"), field="identityColumn"\n'
    '                )\n'
    '                identity_order = (legacy,)\n'
    '            if not properties or (set(properties) | set(filters)) - set(projection):\n',
)
edit(
    "src/semaloom/adapters/postgres.py",
    '                f"ORDER BY {identity_col} LIMIT :limit"\n',
    '                f"ORDER BY {\', \'.join(identity_order)} LIMIT :limit"\n',
)
append_before(
    "src/semaloom/adapters/postgres.py",
    'class _AnalysisConnection:\n',
    '''def _grain_projection(mapping: MappingDef) -> dict[str, str]:\n    raw = mapping.physical.get("grainColumns")\n    if not isinstance(raw, dict):\n        return {}\n    return {\n        require_ident(str(semantic), field="grainColumns.semantic"): require_ident(\n            str(column), field=f"grainColumns.{semantic}"\n        )\n        for semantic, column in raw.items()\n    }\n\n\ndef _identity_columns(mapping: MappingDef) -> tuple[str, ...]:\n    grain = _grain_projection(mapping)\n    return tuple(grain[field] for field in mapping.identity_fields if field in grain)\n\n\ndef _coerce_identity(\n    mapping: MappingDef, identity: ObjectIdentity | None, identity_value: str | None\n) -> ObjectIdentity:\n    if identity:\n        return dict(identity)\n    if identity_value is None:\n        raise ValueError("identity is required")\n    fields = mapping.identity_fields\n    if not fields:\n        identity_col = mapping.physical.get("identityColumn")\n        grain = _grain_projection(mapping)\n        fields = tuple(key for key, column in grain.items() if column == identity_col)\n    if len(fields) != 1:\n        raise ValueError("composite identity requires an identity map")\n    return {fields[0]: identity_value}\n\n\ndef _identity_predicates(\n    mapping: MappingDef, identity: ObjectIdentity\n) -> tuple[list[str], dict[str, Any]]:\n    grain = _grain_projection(mapping)\n    required = tuple(mapping.identity_fields) or tuple(identity)\n    if not required or set(identity) != set(required):\n        raise ValueError("identity does not match mapping contract")\n    clauses: list[str] = []\n    params: dict[str, Any] = {}\n    for index, semantic in enumerate(required):\n        column = grain.get(semantic)\n        if column is None and len(required) == 1:\n            column = require_ident(mapping.physical.get("identityColumn"), field="identityColumn")\n        if column is None:\n            raise ValueError(f"identity field {semantic} is not mapped")\n        name = f"identity_{index}"\n        clauses.append(f"{column} = :{name}")\n        params[name] = identity[semantic]\n    return clauses, params\n\n\n''',
)

# --- OpenAPI provider: multiple identity query params + response pointers ---
edit(
    "src/semaloom/adapters/openapi.py",
    'from semaloom.core.provider import ObjectRead\n',
    'from semaloom.core.provider import ObjectIdentity, ObjectRead\n',
)
edit(
    "src/semaloom/adapters/openapi.py",
    '        tenant: str,\n        identity_value: str,\n    ) -> ObjectRead:\n        observed = _now()\n        outcome = self._get(mapping, tenant=tenant, identity_value=identity_value)\n',
    '        tenant: str,\n        identity: ObjectIdentity | None = None,\n        identity_value: str | None = None,\n    ) -> ObjectRead:\n'
    '        observed = _now()\n'
    '        resolved_identity = _coerce_identity(mapping, identity, identity_value)\n'
    '        outcome = self._get(mapping, tenant=tenant, identity=resolved_identity)\n',
)
edit(
    "src/semaloom/adapters/openapi.py",
    '        identity_pointer = str(mapping.physical.get("identityPointer", "/id"))\n        if str(_pointer(record, identity_pointer)) != identity_value:\n',
    '        if not _identity_matches(record, mapping, resolved_identity):\n',
)
edit(
    "src/semaloom/adapters/openapi.py",
    '        tenant: str,\n        identity_value: str,\n        extra_filters: dict[str, str] | None = None,\n    ) -> Observation:\n        observed = _now()\n        outcome = self._get(\n            mapping,\n            tenant=tenant,\n            identity_value=identity_value,\n            extra_filters=extra_filters,\n        )\n',
    '        tenant: str,\n        identity: ObjectIdentity | None = None,\n        identity_value: str | None = None,\n        extra_filters: dict[str, str] | None = None,\n    ) -> Observation:\n'
    '        observed = _now()\n'
    '        resolved_identity = _coerce_identity(mapping, identity, identity_value)\n'
    '        outcome = self._get(\n'
    '            mapping,\n'
    '            tenant=tenant,\n'
    '            identity=resolved_identity,\n'
    '            extra_filters=extra_filters,\n'
    '        )\n',
)
edit(
    "src/semaloom/adapters/openapi.py",
    '        identity = _pointer(record, str(mapping.physical.get("identityPointer", "/id")))\n        if str(identity) != identity_value:\n',
    '        if not _identity_matches(record, mapping, resolved_identity):\n',
)
edit(
    "src/semaloom/adapters/openapi.py",
    '        tenant: str,\n        identity_value: str,\n        extra_filters: dict[str, str] | None = None,\n    ) -> Any | str:\n',
    '        tenant: str,\n        identity: ObjectIdentity,\n        extra_filters: dict[str, str] | None = None,\n    ) -> Any | str:\n',
)
edit(
    "src/semaloom/adapters/openapi.py",
    '        identity_parameter = str(mapping.physical.get("identityParameter", "id"))\n        if identity_parameter == "tenant":\n            return "INVALID_MAPPING"\n        params = {**(extra_filters or {}), identity_parameter: identity_value, "tenant": tenant}\n',
    '        identity_parameters = _identity_parameters(mapping, identity)\n'
    '        if "tenant" in identity_parameters.values():\n'
    '            return "INVALID_MAPPING"\n'
    '        params = {**(extra_filters or {}), "tenant": tenant}\n'
    '        for semantic, value in identity.items():\n'
    '            parameter = identity_parameters.get(semantic)\n'
    '            if parameter is None:\n'
    '                return "INVALID_MAPPING"\n'
    '            params[parameter] = value\n',
)
append_before(
    "src/semaloom/adapters/openapi.py",
    'def _single_record(\n',
    '''def _coerce_identity(\n    mapping: MappingDef, identity: ObjectIdentity | None, identity_value: str | None\n) -> ObjectIdentity:\n    if identity:\n        return dict(identity)\n    if identity_value is None:\n        raise ValueError("identity is required")\n    fields = tuple(mapping.identity_fields)\n    if not fields:\n        grain = mapping.physical.get("grainPointers")\n        pointer = mapping.physical.get("identityPointer")\n        if isinstance(grain, dict):\n            fields = tuple(str(k) for k, v in grain.items() if v == pointer)\n    if len(fields) != 1:\n        raise ValueError("composite identity requires an identity map")\n    return {fields[0]: identity_value}\n\n\ndef _identity_parameters(mapping: MappingDef, identity: ObjectIdentity) -> dict[str, str]:\n    raw = mapping.physical.get("identityParameters")\n    if isinstance(raw, dict):\n        return {str(k): str(v) for k, v in raw.items()}\n    if len(identity) == 1:\n        key = next(iter(identity))\n        return {key: str(mapping.physical.get("identityParameter", key))}\n    return {key: key for key in identity}\n\n\ndef _identity_pointers(mapping: MappingDef, identity: ObjectIdentity) -> dict[str, str]:\n    raw = mapping.physical.get("identityPointers")\n    if isinstance(raw, dict):\n        return {str(k): str(v) for k, v in raw.items()}\n    grain = mapping.physical.get("grainPointers")\n    if isinstance(grain, dict) and set(identity) <= {str(k) for k in grain}:\n        return {key: str(grain[key]) for key in identity}\n    if len(identity) == 1:\n        key = next(iter(identity))\n        return {key: str(mapping.physical.get("identityPointer", f"/{key}"))}\n    return {}\n\n\ndef _identity_matches(record: dict[str, Any], mapping: MappingDef, identity: ObjectIdentity) -> bool:\n    pointers = _identity_pointers(mapping, identity)\n    return bool(pointers) and all(\n        str(_pointer(record, pointers[key])) == str(value) for key, value in identity.items()\n    )\n\n\n''',
)

# --- runtime query: all point reads carry complete semantic identities ---
edit(
    "src/semaloom/runtime/query.py",
    '        if obj is None or len(obj.identity_keys) != 1:\n            raise ValueError("UNKNOWN_OR_UNSUPPORTED_OBJECT")\n',
    '        if obj is None or not obj.identity_keys:\n            raise ValueError("UNKNOWN_OR_UNSUPPORTED_OBJECT")\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '                    for row in page.rows:\n                        id_key = str(row.get(obj.identity_keys[0]))\n                        sec_res = self.provider.fetch_object(\n                            sec_m, tenant=actor.tenant, identity_value=id_key\n                        )\n',
    '                    for row in page.rows:\n'
    '                        identity = {key: row.get(key) for key in obj.identity_keys}\n'
    '                        if any(value is None for value in identity.values()):\n'
    '                            raise ValueError("CARDINALITY_VIOLATION")\n'
    '                        sec_res = self.provider.fetch_object(\n'
    '                            sec_m, tenant=actor.tenant, identity=identity\n'
    '                        )\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '        records = []\n        seen: set[str] = set()\n        for row in page.rows:\n            key = str(row.get(obj.identity_keys[0]))\n            if key in seen or row.get(obj.identity_keys[0]) is None:\n                raise ValueError("CARDINALITY_VIOLATION")\n            seen.add(key)\n            records.append(\n                {\n                    "identity": {obj.identity_keys[0]: key},\n                    "properties": {k: None if row.get(k) is None else str(row[k]) for k in fields},\n                }\n            )\n',
    '        records = []\n'
    '        seen: set[tuple[str, ...]] = set()\n'
    '        for row in page.rows:\n'
    '            identity = {key: row.get(key) for key in obj.identity_keys}\n'
    '            if any(value is None for value in identity.values()):\n'
    '                raise ValueError("CARDINALITY_VIOLATION")\n'
    '            identity_key = tuple(str(identity[key]) for key in obj.identity_keys)\n'
    '            if identity_key in seen:\n'
    '                raise ValueError("CARDINALITY_VIOLATION")\n'
    '            seen.add(identity_key)\n'
    '            records.append(\n'
    '                {\n'
    '                    "identity": {key: str(value) for key, value in identity.items()},\n'
    '                    "properties": {k: None if row.get(k) is None else str(row[k]) for k in fields},\n'
    '                }\n'
    '            )\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '        source_identity: str,\n',
    '        source_identity: str | dict[str, str],\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '        source_read = self.provider.fetch_object(\n            source_mapping, tenant=actor.tenant, identity_value=source_identity\n        )\n',
    '        source_obj = next(item for item in self.bundle.object_types if item.id == link.source)\n'
    '        if isinstance(source_identity, str):\n'
    '            if len(source_obj.identity_keys) != 1:\n'
    '                return EvidenceEnvelope(\n'
    '                    request_id=request_id,\n'
    '                    release_digest=self.bundle.digest,\n'
    '                    observations=(),\n'
    '                    diagnostics=(Diagnostic(code="INVALID_BINDINGS", path=link_id, message="composite source identity requires all components"),),\n'
    '                    status="FAILED",\n'
    '                )\n'
    '            resolved_source_identity = {source_obj.identity_keys[0]: source_identity}\n'
    '        else:\n'
    '            resolved_source_identity = dict(source_identity)\n'
    '            if set(resolved_source_identity) != set(source_obj.identity_keys):\n'
    '                return EvidenceEnvelope(\n'
    '                    request_id=request_id,\n'
    '                    release_digest=self.bundle.digest,\n'
    '                    observations=(),\n'
    '                    diagnostics=(Diagnostic(code="INVALID_BINDINGS", path=link_id, message="source identity does not match semantic definition"),),\n'
    '                    status="FAILED",\n'
    '                )\n'
    '        source_read = self.provider.fetch_object(\n'
    '            source_mapping, tenant=actor.tenant, identity=resolved_source_identity\n'
    '        )\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '{"link": link_id, "sourceIdentity": source_identity, "tenant": actor.tenant}\n',
    '{"link": link_id, "sourceIdentity": resolved_source_identity, "tenant": actor.tenant}\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '        for key in keys:\n            target_read = self.provider.fetch_object(\n                target_mapping, tenant=actor.tenant, identity_value=key\n            )\n',
    '        target_obj = next(item for item in self.bundle.object_types if item.id == link.target)\n'
    '        if set(target_obj.identity_keys) != {link.identity.target}:\n'
    '            return EvidenceEnvelope(\n'
    '                request_id=request_id,\n'
    '                release_digest=self.bundle.digest,\n'
    '                observations=(),\n'
    '                source_activities=tuple(activities),\n'
    '                diagnostics=(Diagnostic(code="COMPOSITE_LINK_IDENTITY_UNRESOLVED", path=link_id, message="Link identity does not cover every target identity component"),),\n'
    '                status="FAILED",\n'
    '            )\n'
    '        for key in keys:\n'
    '            target_identity = {link.identity.target: key}\n'
    '            target_read = self.provider.fetch_object(\n'
    '                target_mapping, tenant=actor.tenant, identity=target_identity\n'
    '            )\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '        try:\n            identity_key = _identity_binding(item.bindings, mapping)\n        except ValueError:\n',
    '        metric_def = next((entry for entry in self.bundle.metrics if entry.id == item.metric), None)\n'
    '        object_type = next(\n'
    '            (entry for entry in self.bundle.object_types if metric_def and entry.id == metric_def.object_type),\n'
    '            None,\n'
    '        )\n'
    '        try:\n'
    '            identity = _identity_bindings(item.bindings, object_type.identity_keys if object_type else ())\n'
    '        except ValueError:\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '        metric_def = next((entry for entry in self.bundle.metrics if entry.id == item.metric), None)\n        allowed = set(metric_def.grain) if metric_def is not None else set(item.bindings)\n',
    '        allowed = set(metric_def.grain) if metric_def is not None else set(item.bindings)\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '            if key in allowed\n            and key in grain\n            and grain[key] != mapping.physical.get("identityColumn")\n',
    '            if key in allowed\n            and key in grain\n            and key not in identity\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '            identity_value=identity_key,\n',
    '            identity=identity,\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '        if len(object_type.identity_keys) != 1:\n            return (\n                Observation(\n                    kind="UNAVAILABLE",\n                    target=item.object_type,\n                    reason="COMPOSITE_IDENTITY_NOT_SUPPORTED",\n                ),\n                (),\n                (\n                    Diagnostic(\n                        code="COMPOSITE_IDENTITY_NOT_SUPPORTED",\n                        path=item.object_type,\n                        message="use a declared stable scalar identity",\n                    ),\n                ),\n            )\n',
    '',
)
edit(
    "src/semaloom/runtime/query.py",
    '        identity_value = item.identity[object_type.identity_keys[0]]\n        values: dict[str, Any] = dict(item.identity)\n',
    '        values: dict[str, Any] = dict(item.identity)\n',
)
edit(
    "src/semaloom/runtime/query.py",
    '            result = self.provider.fetch_object(\n                mapping, tenant=tenant, identity_value=identity_value\n            )\n',
    '            result = self.provider.fetch_object(\n                mapping, tenant=tenant, identity=dict(item.identity)\n            )\n',
)
edit(
    "src/semaloom/runtime/query.py",
    'def _identity_binding(bindings: dict[str, str | int], mapping: MappingDef) -> str:\n    identity_col = mapping.physical.get("identityColumn")\n    for key, column in _grain_columns(mapping).items():\n        if column == identity_col and key in bindings:\n            return str(bindings[key])\n    raise ValueError("identity binding is required")\n',
    'def _identity_bindings(\n'
    '    bindings: dict[str, str | int], identity_keys: tuple[str, ...]\n'
    ') -> dict[str, str | int]:\n'
    '    if not identity_keys or not set(identity_keys) <= set(bindings):\n'
    '        raise ValueError("identity binding is required")\n'
    '    return {key: bindings[key] for key in identity_keys}\n',
)

# result wire type can carry typed composite identity values.
edit(
    "src/semaloom/core/results.py",
    'class ObjectSelect(_Frozen):\n    object_type: str\n    identity: dict[str, str]\n',
    'class ObjectSelect(_Frozen):\n    object_type: str\n    identity: dict[str, str | int | bool]\n',
)

# --- runtime discovery consumes explicit capabilities, never provider names ---
old_discovery = '''def _postgres_object_mapping(bundle: CompiledBundle, object_type_id: str) -> Any:\n    matches = [\n        item\n        for item in bundle.mappings\n        if item.target == object_type_id and item.provider == "postgres"\n    ]\n    if len(matches) != 1:\n        return None\n    return matches[0]\n\n\ndef _link_collection_join(\n    bundle: CompiledBundle, source: str, target: str, cardinality: str\n) -> bool:\n    if cardinality != "ONE":\n        return False\n    source_mapping = _postgres_object_mapping(bundle, source)\n    target_mapping = _postgres_object_mapping(bundle, target)\n    return source_mapping is not None and target_mapping is not None\n'''
new_discovery = '''def _object_mapping_with_capability(\n    bundle: CompiledBundle, object_type_id: str, capability: str\n) -> Any:\n    matches = [\n        item\n        for item in bundle.mappings\n        if item.target == object_type_id and capability in item.capabilities\n    ]\n    if len(matches) != 1:\n        return None\n    return matches[0]\n\n\ndef _link_collection_join_mode(\n    bundle: CompiledBundle, source: str, target: str, cardinality: str\n) -> str | None:\n    if cardinality != "ONE":\n        return None\n    source_mapping = _object_mapping_with_capability(bundle, source, "COLLECTION_QUERY")\n    target_mapping = _object_mapping_with_capability(bundle, target, "COLLECTION_QUERY")\n    if source_mapping is None or target_mapping is None:\n        return None\n    if (\n        source_mapping.source_id == target_mapping.source_id\n        and "RELATIONAL_JOIN" in source_mapping.capabilities\n        and "RELATIONAL_JOIN" in target_mapping.capabilities\n    ):\n        return "RELATIONAL"\n    if "BATCH_KEY_LOOKUP" in target_mapping.capabilities:\n        return "BIND"\n    return None\n'''
edit("src/semaloom/runtime/discovery.py", old_discovery, new_discovery)
edit(
    "src/semaloom/runtime/discovery.py",
    '    if kind == "Link":\n        return {\n            **document,\n            "analysisCapabilities": {\n                "pointLookup": True,\n                "keyedFind": True,\n                "collectionJoin": _link_collection_join(\n                    bundle,\n                    str(document.get("source") or ""),\n                    str(document.get("target") or ""),\n                    str(document.get("cardinality") or ""),\n                ),\n            },\n        }\n',
    '    if kind == "Link":\n'
    '        join_mode = _link_collection_join_mode(\n'
    '            bundle,\n'
    '            str(document.get("source") or ""),\n'
    '            str(document.get("target") or ""),\n'
    '            str(document.get("cardinality") or ""),\n'
    '        )\n'
    '        return {\n'
    '            **document,\n'
    '            "analysisCapabilities": {\n'
    '                "pointLookup": True,\n'
    '                "keyedFind": True,\n'
    '                "collectionJoin": join_mode is not None,\n'
    '                "collectionJoinMode": join_mode,\n'
    '            },\n'
    '        }\n',
)
edit(
    "src/semaloom/runtime/discovery.py",
    '                "collectionJoin": any(\n                    _link_collection_join(bundle, link.source, link.target, link.cardinality)\n                    for link in bundle.links\n                    if link.source == object_type\n                ),\n',
    '                "collectionJoin": any(\n'
    '                    _link_collection_join_mode(bundle, link.source, link.target, link.cardinality)\n'
    '                    is not None\n'
    '                    for link in bundle.links\n'
    '                    if link.source == object_type\n'
    '                ),\n',
)

# --- Studio preview & projections: composite identity is visible and executable ---
edit(
    "src/semaloom/runtime/studio.py",
    '        "identityField": _identity_field(mapping),\n        "requiredBindings": _required_preview_bindings(mapping),\n',
    '        "identityField": _identity_field(mapping),\n'
    '        "identityFields": _identity_fields(mapping),\n'
    '        "capabilities": list(mapping.capabilities),\n'
    '        "requiredBindings": _required_preview_bindings(mapping),\n',
)
edit(
    "src/semaloom/runtime/studio.py",
    '        "identityKeys": list(obj.identity_keys),\n        "properties": [prop.model_dump(mode="json", by_alias=True) for prop in obj.properties],\n',
    '        "identityKeys": list(obj.identity_keys),\n'
    '        "identity": (\n'
    '            obj.identity.model_dump(mode="json", by_alias=True)\n'
    '            if obj.identity is not None\n'
    '            else {\n'
    '                "scope": "TENANT",\n'
    '                "components": [\n'
    '                    {"property": key, "normalization": "NONE"} for key in obj.identity_keys\n'
    '                ],\n'
    '            }\n'
    '        ),\n'
    '        "properties": [prop.model_dump(mode="json", by_alias=True) for prop in obj.properties],\n',
)
edit(
    "src/semaloom/runtime/studio.py",
    '    identity: str,\n',
    '    identity: dict[str, str] | str,\n',
)
edit(
    "src/semaloom/runtime/studio.py",
    '    metric_ids = {item.id for item in bundle.metrics}\n    extra = _preview_extra_filters(mapping, bindings or {})\n',
    '    metric_ids = {item.id for item in bundle.metrics}\n'
    '    identity_fields = _identity_fields(mapping)\n'
    '    if isinstance(identity, str):\n'
    '        if len(identity_fields) != 1:\n'
    '            raise ValueError("COMPOSITE_IDENTITY_REQUIRED")\n'
    '        resolved_identity = {identity_fields[0]: identity}\n'
    '    else:\n'
    '        resolved_identity = dict(identity)\n'
    '    if set(resolved_identity) != set(identity_fields) or any(\n'
    '        not str(value).strip() for value in resolved_identity.values()\n'
    '    ):\n'
    '        raise ValueError("INVALID_IDENTITY")\n'
    '    extra = _preview_extra_filters(mapping, bindings or {})\n',
)
edit(
    "src/semaloom/runtime/studio.py",
    '            mapping, tenant=tenant, identity_value=identity, extra_filters=extra or None\n',
    '            mapping, tenant=tenant, identity=resolved_identity, extra_filters=extra or None\n',
)
edit(
    "src/semaloom/runtime/studio.py",
    '        result = provider.fetch_object(mapping, tenant=tenant, identity_value=identity)\n',
    '        result = provider.fetch_object(mapping, tenant=tenant, identity=resolved_identity)\n',
)
edit(
    "src/semaloom/runtime/studio.py",
    '    identity_field = _identity_field(mapping)\n    preview_values = {identity_field: identity, **(bindings or {}), **values}\n',
    '    preview_values = {**resolved_identity, **(bindings or {}), **values}\n',
)
edit(
    "src/semaloom/runtime/studio.py",
    '        "identity": identity,\n',
    '        "identity": resolved_identity,\n',
)
append_before(
    "src/semaloom/runtime/studio.py",
    'def _required_preview_bindings(mapping: MappingDef) -> list[str]:\n',
    '''def _identity_fields(mapping: MappingDef) -> list[str]:\n    if mapping.identity_fields:\n        return list(mapping.identity_fields)\n    physical = mapping.physical\n    identity_columns = physical.get("identityColumns")\n    if isinstance(identity_columns, dict) and identity_columns:\n        return [str(key) for key in identity_columns]\n    identity_pointers = physical.get("identityPointers")\n    if isinstance(identity_pointers, dict) and identity_pointers:\n        return [str(key) for key in identity_pointers]\n    field = _identity_field(mapping)\n    return [field] if field else []\n\n\n''',
)
edit(
    "src/semaloom/runtime/studio.py",
    '    identity_col = physical.get("identityColumn")\n    grain = physical.get("grainColumns")\n',
    '    identity_col = physical.get("identityColumn")\n'
    '    identity_fields = set(_identity_fields(mapping))\n'
    '    grain = physical.get("grainColumns")\n',
)
edit(
    "src/semaloom/runtime/studio.py",
    '        if column == identity_col or semantic in locked or column in locked:\n',
    '        if semantic in identity_fields or column == identity_col or semantic in locked or column in locked:\n',
)

# HTTP preview accepts new identity map while retaining old scalar payload.
edit(
    "src/semaloom/app/http.py",
    '    identity: str\n',
    '    identity: dict[str, str] | str\n',
)

# --- AI gateway: exact composite identity cache + capability-neutral instructions ---
edit(
    "src/semaloom/app/chat/tools.py",
    '        self.identities: set[tuple[str, str, str]] = set()\n',
    '        self.identities: set[tuple[str, str]] = set()\n',
)
edit(
    "src/semaloom/app/chat/tools.py",
    '                "Link and Metric documents include analysisCapabilities: collectionJoin is true "\n                "only for declared ONE links on the same PostgreSQL source (group/filter by the "\n                "related object\'s attributes). Otherwise Links are for point lookup and keyed "\n                "find.",\n',
    '                "Link and Metric documents include analysisCapabilities. collectionJoin is true "\n'
    '                "only when the approved Mapping capabilities support it; collectionJoinMode is "\n'
    '                "RELATIONAL or BIND. Otherwise Links are for point lookup and keyed find.",\n',
)
edit(
    "src/semaloom/app/chat/tools.py",
    '            for obj in result["objects"]:\n                for key, value in obj["identity"].items():\n                    self.identities.add((request.object_type, key, str(value)))\n',
    '            for obj in result["objects"]:\n'
    '                identity = {str(key): str(value) for key, value in obj["identity"].items()}\n'
    '                self.identities.add((request.object_type, _identity_token(identity)))\n',
)
edit(
    "src/semaloom/app/chat/tools.py",
    '    def _identity(self, object_type: str, bindings: dict[str, Any]) -> None:\n        obj = next((o for o in self.query.bundle.object_types if o.id == object_type), None)\n        if obj is None or len(obj.identity_keys) != 1:\n            raise ValueError("UNSUPPORTED_IDENTITY")\n        for key in obj.identity_keys:\n            if (object_type, key, str(bindings.get(key))) not in self.identities:\n                raise ValueError("RESOLVE_IDENTITY_WITH_FIND_OBJECTS_FIRST")\n\n\nSYSTEM_PROMPT',
    '    def _identity(self, object_type: str, bindings: dict[str, Any]) -> None:\n'
    '        obj = next((o for o in self.query.bundle.object_types if o.id == object_type), None)\n'
    '        if obj is None or not obj.identity_keys:\n'
    '            raise ValueError("UNSUPPORTED_IDENTITY")\n'
    '        if not set(obj.identity_keys) <= set(bindings):\n'
    '            raise ValueError("RESOLVE_IDENTITY_WITH_FIND_OBJECTS_FIRST")\n'
    '        identity = {key: str(bindings[key]) for key in obj.identity_keys}\n'
    '        if (object_type, _identity_token(identity)) not in self.identities:\n'
    '            raise ValueError("RESOLVE_IDENTITY_WITH_FIND_OBJECTS_FIRST")\n\n\n'
    'def _identity_token(identity: dict[str, str]) -> str:\n'
    '    return json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)\n\n\n'
    'SYSTEM_PROMPT',
)

# --- docs accurately describe the new contract ---
edit(
    "README.md",
    '- In-process links across databases using declared business identities (first identity key only).\n',
    '- In-process links and point reads use declared business identities, including composite identities.\n',
)
edit(
    "README.md",
    'MCP SDK transport (`GET /v0.1/mcp/tools` is a static name list), composite-key query, BOOLEAN /\n',
    'MCP SDK transport (`GET /v0.1/mcp/tools` is a static name list), composite-key relation traversal, BOOLEAN /\n',
)
edit(
    "docs/architecture.md",
    'Core 选择语义合法路径、执行预算和授权约束；接入 adapter 编译物理查询，执行协议并返回规范化观测/操作结果。物理字段和 operation 只存在于受审核接入产物；core 持有其标识与摘要，不解释协议专属结构。当前 `Mapping.physical` 仍为按 provider 约定的字典（成熟度项：后续按 provider 分型校验）；依赖关系与验证见',
    'Core 选择语义合法路径、执行预算和授权约束；接入 adapter 编译物理查询，执行协议并返回规范化观测/操作结果。物理字段和 operation 只存在于受审核接入产物；core 持有其标识与摘要，不解释协议专属结构。Compiler 会把 v0.1 物理声明物化为 `Mapping.identityFields` 与 provider-neutral `capabilities`，Runtime/Discovery/AI 只按该能力契约决策；`Mapping.physical` 仍为兼容现有 DSL 的 adapter 配置（后续按 provider 分型校验）。复合业务身份以完整 identity map 贯穿 Query、Provider、Studio 与 AI identity gate；依赖关系与验证见',
)

# --- regression tests for the full backend/AI contract ---
(ROOT / "tests/test_p0_capability_identity.py").write_text(r'''from __future__ import annotations

from typing import Any

import pytest

from semaloom.app.chat.tools import SemanticTools, _identity_token
from semaloom.compiler.api import compile_documents
from semaloom.core.provider import ObjectRead
from semaloom.core.results import ObjectSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.discovery import SemanticDiscovery
from semaloom.runtime.query import QueryService
from semaloom.runtime.studio import studio_mapping_preview


def _documents(provider: str = "postgres") -> list[dict[str, Any]]:
    physical: dict[str, Any]
    if provider == "postgres":
        physical = {
            "table": "ledger_rows",
            "tenantColumn": "tenant_id",
            "identityColumn": "company_id",
            "grainColumns": {"companyId": "company_id", "ledger": "ledger"},
            "propertyColumns": {"name": "name"},
        }
    else:
        physical = {
            "path": "/company",
            "method": "GET",
            "identityParameters": {"companyId": "company", "ledger": "ledger"},
            "identityPointers": {"companyId": "/company", "ledger": "/ledger"},
            "grainPointers": {"companyId": "/company", "ledger": "/ledger"},
            "propertyPointers": {"name": "/name"},
        }
    return [
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "DomainPack",
            "id": "finance.pack",
            "version": "1.0.0",
            "contractVersion": "v0.1",
            "namespace": "finance",
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "ObjectType",
            "id": "finance.CompanyLedger",
            "version": "1.0.0",
            "identityKeys": ["companyId", "ledger"],
            "identity": {
                "scope": "TENANT",
                "components": [
                    {"property": "companyId", "normalization": "NONE"},
                    {"property": "ledger", "normalization": "NONE"},
                ],
            },
            "properties": [
                {"id": "companyId", "valueType": "STRING", "required": True},
                {"id": "ledger", "valueType": "STRING", "required": True},
                {"id": "name", "valueType": "STRING"},
            ],
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Mapping",
            "id": "finance.CompanyLedger.main",
            "version": "1.0.0",
            "target": "finance.CompanyLedger",
            "sourceId": "source-a",
            "provider": provider,
            "objectType": "finance.CompanyLedger",
            "expectedCardinality": "ONE",
            "completeness": "AUTHORITATIVE",
            "physical": physical,
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "IntegrationBinding",
            "id": "integration.source-a",
            "version": "1.0.0",
            "provider": provider,
            "sourceId": "source-a",
            "mappings": ["finance.CompanyLedger.main"],
        },
    ]


def _bundle(provider: str = "postgres"):
    result = compile_documents(_documents(provider))
    assert result.ok, result.diagnostics
    assert result.bundle is not None
    return result.bundle


def test_compile_materializes_neutral_capability_and_identity_contract() -> None:
    mapping = _bundle().mappings[0]
    assert mapping.identity_fields == ("companyId", "ledger")
    assert "POINT_READ" in mapping.capabilities
    assert "OBJECT_SEARCH" in mapping.capabilities
    assert "COLLECTION_QUERY" in mapping.capabilities
    assert "RELATIONAL_JOIN" in mapping.capabilities


def test_discovery_does_not_require_postgres_provider_name() -> None:
    docs = _documents("warehouse")
    docs[2]["capabilities"] = ["POINT_READ", "COLLECTION_QUERY", "RELATIONAL_JOIN"]
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "ObjectType",
            "id": "finance.Owner",
            "version": "1.0.0",
            "identityKeys": ["ownerId"],
            "properties": [{"id": "ownerId", "valueType": "STRING", "required": True}],
        }
    )
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Mapping",
            "id": "finance.Owner.main",
            "version": "1.0.0",
            "target": "finance.Owner",
            "sourceId": "source-a",
            "provider": "warehouse",
            "objectType": "finance.Owner",
            "expectedCardinality": "ONE",
            "capabilities": ["POINT_READ", "COLLECTION_QUERY", "RELATIONAL_JOIN"],
            "physical": {"resource": "owner"},
        }
    )
    docs[3]["mappings"].append("finance.Owner.main")
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Link",
            "id": "finance.companyOwner",
            "version": "1.0.0",
            "source": "finance.CompanyLedger",
            "target": "finance.Owner",
            "identity": {"source": "companyId", "target": "ownerId"},
            "cardinality": "ONE",
            "traversal": "FORWARD",
        }
    )
    result = compile_documents(docs)
    assert result.ok, result.diagnostics
    bundle = result.bundle
    assert bundle is not None
    actor = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
    link = SemanticDiscovery(bundle).describe("finance.companyOwner", actor)
    assert link["analysisCapabilities"]["collectionJoin"] is True
    assert link["analysisCapabilities"]["collectionJoinMode"] == "RELATIONAL"


class _Provider:
    def __init__(self) -> None:
        self.identities: list[dict[str, Any]] = []

    def fetch_object(self, mapping: Any, *, tenant: str, identity: dict[str, Any]) -> ObjectRead:
        self.identities.append(dict(identity))
        return ObjectRead(
            kind="PRESENT",
            values={**identity, "name": "ACME"},
            mappingId=mapping.id,
            sourceId=mapping.source_id,
            observedAt="2026-01-01T00:00:00Z",
        )


def test_query_service_passes_the_complete_composite_identity() -> None:
    provider = _Provider()
    service = QueryService(_bundle(), provider)  # type: ignore[arg-type]
    actor = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
    result = service.execute(
        QueryRequest(
            apiVersion="semaloom/v0.1",
            select=(
                ObjectSelect(
                    objectType="finance.CompanyLedger",
                    identity={"companyId": "C1", "ledger": "LOCAL"},
                    properties=("name",),
                ),
            ),
            context=QueryContext(businessPeriod={"from": "2026-01-01", "to": "2027-01-01"}),
        ),
        actor,
    )
    assert result.status == "SUCCEEDED"
    assert provider.identities == [{"companyId": "C1", "ledger": "LOCAL"}]


def test_studio_preview_passes_the_same_composite_identity() -> None:
    provider = _Provider()
    preview = studio_mapping_preview(
        _bundle(),
        provider,  # type: ignore[arg-type]
        mapping_id="finance.CompanyLedger.main",
        tenant="tenant-a",
        identity={"companyId": "C1", "ledger": "LOCAL"},
    )
    assert preview is not None
    assert preview["identity"] == {"companyId": "C1", "ledger": "LOCAL"}
    assert provider.identities == [{"companyId": "C1", "ledger": "LOCAL"}]


def test_ai_identity_gate_matches_the_whole_identity_tuple() -> None:
    provider = _Provider()
    service = QueryService(_bundle(), provider)  # type: ignore[arg-type]
    actor = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
    tools = SemanticTools(service, actor)
    resolved = {"companyId": "C1", "ledger": "LOCAL"}
    tools.identities.add(("finance.CompanyLedger", _identity_token(resolved)))
    tools._identity("finance.CompanyLedger", resolved)
    with pytest.raises(ValueError, match="RESOLVE_IDENTITY_WITH_FIND_OBJECTS_FIRST"):
        tools._identity("finance.CompanyLedger", {"companyId": "C1", "ledger": "IFRS"})
''')

print("backend P0 refactor applied")

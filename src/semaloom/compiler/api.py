"""Compile domain packs and integration bindings into an immutable bundle."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from graphlib import CycleError, TopologicalSorter
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from semaloom import __version__
from semaloom.compiler.digest import canonical_json, physical_digest, sha256_digest
from semaloom.compiler.mapping_ir import compile_mapping_ir, derive_metric_mapping
from semaloom.compiler.yaml_load import load_yaml_documents
from semaloom.core.bundle import CompiledBundle
from semaloom.core.diagnostics import Diagnostic
from semaloom.core.expr import collect_refs, expression_type
from semaloom.core.ids import (
    API_VERSION,
    BUNDLE_FORMAT,
    CONTRACT_VERSION,
    IR_VERSION,
    is_pack_id,
    is_semantic_id,
    namespace_of,
)
from semaloom.core.model import (
    ActionBindingDef,
    ActionDef,
    AuthorizationProfileDef,
    DomainPackDef,
    IntegrationBindingDef,
    LinkDef,
    MappingDef,
    MetricDef,
    ObjectTypeDef,
    PolicyDef,
    RuleDef,
)

KNOWN_KINDS = frozenset(
    {
        "DomainPack",
        "ObjectType",
        "Metric",
        "Link",
        "Rule",
        "Policy",
        "Action",
        "AuthorizationProfile",
        "Mapping",
        "ActionBinding",
        "IntegrationBinding",
    }
)


def _parse_kind(kind: str, raw: dict[str, Any]) -> Any:
    if kind == "DomainPack":
        return DomainPackDef.model_validate(raw)
    if kind == "ObjectType":
        return ObjectTypeDef.model_validate(raw)
    if kind == "Metric":
        return MetricDef.model_validate(raw)
    if kind == "Link":
        return LinkDef.model_validate(raw)
    if kind == "Rule":
        return RuleDef.from_document(raw)
    if kind == "Policy":
        return PolicyDef.model_validate(raw)
    if kind == "Action":
        return ActionDef.model_validate(raw)
    if kind == "AuthorizationProfile":
        return AuthorizationProfileDef.model_validate(raw)
    if kind == "Mapping":
        return MappingDef.model_validate(raw)
    if kind == "ActionBinding":
        return ActionBindingDef.model_validate(raw)
    if kind == "IntegrationBinding":
        return IntegrationBindingDef.model_validate(raw)
    raise ValueError(kind)


RESERVED_APPROVAL_FIELDS = frozenset({"approvedBy", "approved_by", "status"})


class CompileResult:
    def __init__(
        self,
        *,
        ok: bool,
        bundle: CompiledBundle | None,
        diagnostics: tuple[Diagnostic, ...],
        online_validation: Literal["NOT_RUN", "PASSED", "FAILED"],
    ) -> None:
        self.ok = ok
        self.bundle = bundle
        self.diagnostics = diagnostics
        self.online_validation = online_validation


def compile_paths(
    roots: Sequence[Path],
    *,
    catalog_snapshot: Mapping[str, Any] | None = None,
) -> CompileResult:
    documents: list[tuple[str, dict[str, Any]]] = []
    for root in roots:
        for path, data in load_yaml_documents(root):
            documents.append((str(path), data))
    return compile_documents(documents, catalog_snapshot=catalog_snapshot)


def compile_documents(
    documents: Sequence[object],
    *,
    catalog_snapshot: Mapping[str, Any] | None = None,
) -> CompileResult:
    diagnostics: list[Diagnostic] = []
    parsed: list[Any] = []
    normalized: list[tuple[str, dict[str, Any]]] = _normalize_input(documents)

    for path, raw in normalized:
        _reject_approval_fields(path, raw, diagnostics)
        kind = raw.get("kind")
        if kind not in KNOWN_KINDS:
            diagnostics.append(
                Diagnostic(
                    code="UNKNOWN_KIND",
                    path=path,
                    message=f"unknown kind {kind!r}",
                )
            )
            continue
        try:
            parsed.append(_parse_kind(str(kind), raw))
        except ValidationError as exc:
            diagnostics.extend(_validation_diagnostics(path, exc))
        except ValueError as exc:
            diagnostics.append(Diagnostic(code="INVALID_DEFINITION", path=path, message=str(exc)))

    # Offline compile never forges an online contract pass (A05 T01).
    online: Literal["NOT_RUN", "PASSED", "FAILED"] = "NOT_RUN"
    if catalog_snapshot is not None:
        diagnostics.append(
            Diagnostic(
                code="ONLINE_VALIDATION_NOT_RUN",
                path="<catalog>",
                message="catalog snapshot ignored until T02 source validation",
                severity="warning",
            )
        )

    if any(item.severity == "error" for item in diagnostics):
        return CompileResult(
            ok=False, bundle=None, diagnostics=tuple(diagnostics), online_validation=online
        )

    packs = [item for item in parsed if isinstance(item, DomainPackDef)]
    objects = [item for item in parsed if isinstance(item, ObjectTypeDef)]
    metrics = [item for item in parsed if isinstance(item, MetricDef)]
    links = [item for item in parsed if isinstance(item, LinkDef)]
    rules = [item for item in parsed if isinstance(item, RuleDef)]
    policies = [item for item in parsed if isinstance(item, PolicyDef)]
    actions = [item for item in parsed if isinstance(item, ActionDef)]
    profiles = [item for item in parsed if isinstance(item, AuthorizationProfileDef)]
    integrations = [item for item in parsed if isinstance(item, IntegrationBindingDef)]
    mappings = [item for item in parsed if isinstance(item, MappingDef)]
    bindings = [item for item in parsed if isinstance(item, ActionBindingDef)]

    mappings = compile_mapping_ir(objects, mappings, diagnostics)
    metrics = _metrics_from_properties(objects, metrics, mappings)
    metrics = _materialize_metrics(objects, metrics, mappings, diagnostics)
    mappings, integrations = _bind_metric_mappings(metrics, mappings, integrations)

    compiled_docs = [
        *packs,
        *objects,
        *metrics,
        *links,
        *rules,
        *policies,
        *actions,
        *profiles,
        *integrations,
        *mappings,
        *bindings,
    ]
    _check_ids(compiled_docs, diagnostics)
    _check_packs(packs, compiled_docs, diagnostics)
    _check_object_metrics(objects, metrics, packs, diagnostics)
    _check_links(objects, links, diagnostics)
    _check_rules(metrics, objects, rules, diagnostics)
    _check_policies(rules, policies, diagnostics)
    _check_actions(objects, rules, actions, diagnostics)
    _check_action_bindings(actions, bindings, diagnostics)
    _check_mappings(metrics, objects, mappings, diagnostics)
    _check_integration_bindings(integrations, mappings, bindings, diagnostics)

    errors = tuple(item for item in diagnostics if item.severity == "error")
    if errors:
        return CompileResult(
            ok=False, bundle=None, diagnostics=tuple(diagnostics), online_validation=online
        )

    physical: dict[str, str] = {}
    for mapping in mappings:
        physical[mapping.id] = physical_digest(mapping.physical)
    for binding in bindings:
        physical[binding.id] = physical_digest(binding.physical)
    payload = {
        "apiVersion": API_VERSION,
        "formatVersion": BUNDLE_FORMAT,
        "compilerVersion": __version__,
        "irVersion": IR_VERSION,
        "onlineValidation": online,
        "packs": [_dump(item) for item in _sorted(packs)],
        "objectTypes": [_dump(item) for item in _sorted(objects)],
        "metrics": [_dump(item) for item in _sorted(metrics)],
        "links": [_dump(item) for item in _sorted(links)],
        "rules": [_dump(item) for item in _sorted(rules)],
        "policies": [_dump(item) for item in _sorted(policies)],
        "actions": [_dump(item) for item in _sorted(actions)],
        "authorizationProfiles": [_dump(item) for item in _sorted(profiles)],
        "integrationBindings": [_dump(item) for item in _sorted(integrations)],
        "mappings": [_dump(item) for item in _sorted(mappings)],
        "actionBindings": [_dump(item) for item in _sorted(bindings)],
        "physicalDigests": dict(sorted(physical.items())),
    }
    provisional = CompiledBundle.model_validate({**payload, "digest": ""})
    normalized_payload = provisional.model_dump(mode="json", by_alias=True, exclude_none=True)
    normalized_payload.pop("digest", None)
    digest = sha256_digest(normalized_payload)
    bundle = provisional.model_copy(update={"digest": digest})
    return CompileResult(
        ok=True, bundle=bundle, diagnostics=tuple(diagnostics), online_validation=online
    )


def bundle_canonical_text(bundle: CompiledBundle) -> str:
    payload = bundle.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload.pop("digest", None)
    return canonical_json(payload)


def _normalize_input(documents: Sequence[object]) -> list[tuple[str, dict[str, Any]]]:
    normalized: list[tuple[str, dict[str, Any]]] = []
    for index, item in enumerate(documents):
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], dict):
            normalized.append((str(item[0]), dict(item[1])))
            continue
        if isinstance(item, dict):
            normalized.append((f"<document:{index}>", dict(item)))
            continue
        raise TypeError(f"unsupported compile document: {type(item)!r}")
    return normalized


def _dump(model: Any) -> dict[str, Any]:
    dumped = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    if not isinstance(dumped, dict):
        raise TypeError("model dump must be a mapping")
    return dumped


def _sorted(items: Iterable[Any]) -> list[Any]:
    return sorted(items, key=lambda item: (item.kind, item.id, item.version))


def _physical_slots(mapping: MappingDef) -> dict[str, str]:
    return {key: key for key in (*mapping.grain_fields, *mapping.property_fields)}


def _grain_slots(mapping: MappingDef) -> dict[str, str]:
    return {key: key for key in mapping.grain_fields}


def _metrics_from_properties(
    objects: Sequence[ObjectTypeDef],
    metrics: Sequence[MetricDef],
    mappings: Sequence[MappingDef],
) -> list[MetricDef]:
    """Numeric properties with a unit are queryable; do not make users declare Metric docs."""
    claimed = {(item.object_type, item.property) for item in metrics if item.property}
    ids = {item.id for item in metrics}
    extra: list[MetricDef] = []
    for obj in objects:
        mapped = {
            slot
            for mapping in mappings
            if mapping.target == obj.id
            for slot in _physical_slots(mapping)
        }
        for prop in obj.properties:
            if not prop.unit or prop.value_type not in {"DECIMAL", "INTEGER"}:
                continue
            if (obj.id, prop.id) in claimed or prop.id not in mapped:
                continue
            metric_id = f"{obj.id}.{prop.id}"
            if metric_id in ids:
                continue
            extra.append(
                MetricDef.model_validate(
                    {
                        "apiVersion": "semaloom/v0.1",
                        "kind": "Metric",
                        "id": metric_id,
                        "version": obj.version,
                        "label": prop.label or prop.id,
                        "objectType": obj.id,
                        "property": prop.id,
                        "valueType": prop.value_type,
                        "unit": prop.unit,
                        "aggregation": prop.aggregation or "NONE",
                        "aliases": list(prop.aliases),
                    }
                )
            )
            claimed.add((obj.id, prop.id))
            ids.add(metric_id)
    return [*metrics, *extra]


def _covering_mappings(metric: MetricDef, mappings: Sequence[MappingDef]) -> list[MappingDef]:
    if not metric.property:
        return []
    return [
        mapping
        for mapping in mappings
        if mapping.target == metric.object_type and metric.property in _physical_slots(mapping)
    ]


def _materialize_metrics(
    objects: Sequence[ObjectTypeDef],
    metrics: Sequence[MetricDef],
    mappings: Sequence[MappingDef],
    diagnostics: list[Diagnostic],
) -> list[MetricDef]:
    object_index = _index(objects)
    filled: list[MetricDef] = []
    for metric in metrics:
        obj = object_index.get(metric.object_type)
        updates: dict[str, Any] = {}
        prop = None
        if metric.property:
            if obj is None:
                filled.append(metric)
                continue
            prop = next((item for item in obj.properties if item.id == metric.property), None)
            if prop is None:
                diagnostics.append(
                    Diagnostic(
                        code="DANGLING_REF",
                        path=f"{metric.id}.property",
                        message=metric.property,
                    )
                )
                filled.append(metric)
                continue
            if prop.value_type not in {"DECIMAL", "INTEGER"}:
                diagnostics.append(
                    Diagnostic(
                        code="TYPE_MISMATCH",
                        path=f"{metric.id}.property",
                        message="measure property must be DECIMAL or INTEGER",
                    )
                )
            if metric.value_type is None:
                updates["value_type"] = prop.value_type
            if not metric.unit:
                updates["unit"] = prop.unit
            if metric.aggregation == "NONE" and prop.aggregation:
                updates["aggregation"] = prop.aggregation
            if prop.aliases:
                updates["aliases"] = tuple(dict.fromkeys((*prop.aliases, *metric.aliases)))
        if metric.population is None and obj is not None and obj.population is not None:
            updates["population"] = obj.population
        if not metric.grain:
            select_keys = set(metric.select)
            if metric.perspective:
                select_keys.add("perspective")
            covering = _covering_mappings(metric, mappings)
            dims: list[str] = []
            if covering:
                dims = [
                    key
                    for key in _grain_slots(covering[0])
                    if key not in select_keys and key != metric.property
                ]
            if not dims and obj is not None and metric.property:
                dims = [key for key in obj.identity_keys if key not in select_keys]
            if dims:
                identity = [
                    key for key in (obj.identity_keys if obj is not None else ()) if key in dims
                ]
                rest = sorted(key for key in dims if key not in identity)
                updates["grain"] = tuple([*identity, *rest])
        if metric.value_type is None and not metric.property and metric.derived_from:
            updates["value_type"] = "DECIMAL"
        filled.append(metric.model_copy(update=updates) if updates else metric)
    return filled


def _bind_metric_mappings(
    metrics: Sequence[MetricDef],
    mappings: Sequence[MappingDef],
    integrations: Sequence[IntegrationBindingDef],
) -> tuple[list[MappingDef], list[IntegrationBindingDef]]:
    existing_ids = {item.id for item in mappings}
    mapped_targets = {item.target for item in mappings}
    extra: list[MappingDef] = []
    owners: dict[str, str] = {}
    for metric in metrics:
        if metric.id in mapped_targets or not metric.property:
            continue
        for source in _covering_mappings(metric, mappings):
            suffix = source.id.rsplit(".", 1)[-1]
            mapping_id = f"{metric.id}.{suffix}"
            if mapping_id in existing_ids or mapping_id in owners:
                mapping_id = f"{metric.id}.via_{source.id.rpartition('.')[-1]}"
            if mapping_id in existing_ids or mapping_id in owners:
                continue
            extra.append(derive_metric_mapping(source, metric, mapping_id))
            owners[mapping_id] = source.id
            existing_ids.add(mapping_id)
    if not extra:
        return list(mappings), list(integrations)
    next_mappings = [*mappings, *extra]
    next_integrations: list[IntegrationBindingDef] = []
    source_owner = {
        mapping_id: integration.id
        for integration in integrations
        for mapping_id in integration.mappings
    }
    attached: dict[str, list[str]] = defaultdict(list)
    for mapping_id, source_id in owners.items():
        integration_id = source_owner.get(source_id)
        if integration_id is not None:
            attached[integration_id].append(mapping_id)
    for integration in integrations:
        added = attached.get(integration.id)
        if not added:
            next_integrations.append(integration)
            continue
        next_integrations.append(
            integration.model_copy(update={"mappings": (*integration.mappings, *added)})
        )
    return next_mappings, next_integrations


def _reject_approval_fields(
    path: str, raw: Mapping[str, Any], diagnostics: list[Diagnostic]
) -> None:
    for field in RESERVED_APPROVAL_FIELDS:
        if field in raw:
            diagnostics.append(
                Diagnostic(
                    code="APPROVAL_IN_DSL",
                    path=f"{path}:{field}",
                    message="DSL cannot grant publish approval",
                )
            )


def _validation_diagnostics(path: str, exc: ValidationError) -> list[Diagnostic]:
    items: list[Diagnostic] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ()))
        code = (
            "UNKNOWN_CORE_FIELD" if error.get("type") == "extra_forbidden" else "INVALID_DEFINITION"
        )
        if error.get("type") == "literal_error" and loc.endswith("apiVersion"):
            code = "UNSUPPORTED_CONTRACT"
        items.append(
            Diagnostic(
                code=code,
                path=f"{path}:{loc}" if loc else path,
                message=error.get("msg", "invalid definition"),
            )
        )
    return items


def _check_ids(parsed: Sequence[Any], diagnostics: list[Diagnostic]) -> None:
    seen: dict[tuple[str, str], str] = {}
    for item in parsed:
        key = (item.kind, item.id)
        if key in seen:
            diagnostics.append(
                Diagnostic(
                    code="DUPLICATE_ID",
                    path=item.id,
                    message=f"duplicate ({item.kind}, {item.id})",
                )
            )
        seen[key] = item.id
        if item.kind == "DomainPack":
            if not is_pack_id(item.id):
                diagnostics.append(
                    Diagnostic(code="INVALID_ID", path=item.id, message="invalid pack id")
                )
        elif item.kind != "IntegrationBinding" and not is_semantic_id(item.id):
            diagnostics.append(
                Diagnostic(code="INVALID_ID", path=item.id, message="invalid semantic id")
            )


def _check_packs(
    packs: Sequence[DomainPackDef], parsed: Sequence[Any], diagnostics: list[Diagnostic]
) -> None:
    by_id = {pack.id: pack for pack in packs}
    namespaces: dict[str, str] = {}
    for pack in packs:
        if pack.contract_version != CONTRACT_VERSION:
            diagnostics.append(
                Diagnostic(
                    code="UNSUPPORTED_CONTRACT",
                    path=pack.id,
                    message="unsupported contract version",
                )
            )
        if pack.namespace in namespaces:
            diagnostics.append(
                Diagnostic(
                    code="NAMESPACE_CONFLICT",
                    path=pack.id,
                    message=f"namespace {pack.namespace} owned by {namespaces[pack.namespace]}",
                )
            )
        namespaces[pack.namespace] = pack.id
        for dep in pack.dependencies:
            if dep.id not in by_id:
                diagnostics.append(
                    Diagnostic(
                        code="MISSING_DEPENDENCY",
                        path=pack.id,
                        message=f"missing dependency {dep.id}",
                    )
                )
    sorter: TopologicalSorter[str] = TopologicalSorter()
    for pack in packs:
        sorter.add(pack.id, *[dep.id for dep in pack.dependencies if dep.id in by_id])
    try:
        sorter.prepare()
        while sorter.is_active():
            ready = sorter.get_ready()
            sorter.done(*ready)
    except CycleError:
        diagnostics.append(
            Diagnostic(
                code="PACK_DEPENDENCY_CYCLE", path="<packs>", message="domain pack dependency cycle"
            )
        )

    owned = {pack.namespace: pack for pack in packs}
    for item in parsed:
        if isinstance(item, DomainPackDef | IntegrationBindingDef):
            continue
        ns = namespace_of(item.id)
        owner = owned.get(ns)
        if owner is None:
            diagnostics.append(
                Diagnostic(
                    code="UNDECLARED_CROSS_PACK_REF",
                    path=item.id,
                    message=f"no pack owns namespace {ns}",
                )
            )


def _index(items: Sequence[Any]) -> dict[str, Any]:
    return {item.id: item for item in items}


def _check_object_metrics(
    objects: Sequence[ObjectTypeDef],
    metrics: Sequence[MetricDef],
    packs: Sequence[DomainPackDef],
    diagnostics: list[Diagnostic],
) -> None:
    object_index = _index(objects)
    for obj in objects:
        prop_ids = [prop.id for prop in obj.properties]
        if obj.period is not None:
            types = {prop.id: prop.value_type for prop in obj.properties}
            if any(
                types.get(key) != "DATE"
                for key in (obj.period.from_property, obj.period.to_property)
            ):
                diagnostics.append(
                    Diagnostic(
                        code="TYPE_MISMATCH", path=obj.id, message="period requires DATE properties"
                    )
                )
        if len(prop_ids) != len(set(prop_ids)):
            diagnostics.append(
                Diagnostic(code="DUPLICATE_ID", path=obj.id, message="duplicate property id")
            )
        for key in obj.identity_keys:
            if key not in prop_ids:
                diagnostics.append(
                    Diagnostic(
                        code="DANGLING_REF",
                        path=f"{obj.id}.identityKeys",
                        message=f"missing property {key}",
                    )
                )
    for metric in metrics:
        if metric.object_type not in object_index:
            diagnostics.append(
                Diagnostic(
                    code="DANGLING_REF", path=f"{metric.id}.objectType", message=metric.object_type
                )
            )
            continue
        obj = object_index[metric.object_type]
        property_ids = {prop.id for prop in obj.properties}
        if metric.population:
            spec = metric.population
            types = {prop.id: prop.value_type for prop in obj.properties}
            if (
                spec.unit_property not in property_ids
                or types.get(spec.year_property) != "INTEGER"
                or len(obj.identity_keys) != 1
                or set(metric.grain) - {*obj.identity_keys, spec.year_property, "perspective"}
            ):
                diagnostics.append(
                    Diagnostic(
                        code="INVALID_POPULATION",
                        path=metric.id,
                        message="population needs unit, integer year and scalar object grain",
                    )
                )
        if not metric.grain:
            diagnostics.append(
                Diagnostic(code="INCOMPLETE_GRAIN", path=metric.id, message="grain is required")
            )
        if not metric.unit:
            diagnostics.append(
                Diagnostic(code="MISSING_UNIT", path=metric.id, message="unit is required")
            )
        if metric.value_type is None:
            diagnostics.append(
                Diagnostic(
                    code="INVALID_DEFINITION",
                    path=metric.id,
                    message="valueType is required unless inherited from a measure property",
                )
            )
        pack = next(
            (item for item in packs if namespace_of(metric.id) == item.namespace),
            None,
        )
        context_ids = {dim.id for dim in pack.context_dimensions} if pack is not None else set()
        for key in metric.select:
            if key in property_ids or key in obj.identity_keys or key in context_ids:
                continue
            diagnostics.append(
                Diagnostic(
                    code="INVALID_DIMENSION_TYPE",
                    path=f"{metric.id}.select",
                    message=f"unknown select dimension {key}",
                )
            )
        for dim in metric.grain:
            if dim in property_ids or dim in obj.identity_keys or dim in context_ids:
                continue
            diagnostics.append(
                Diagnostic(
                    code="INVALID_DIMENSION_TYPE",
                    path=f"{metric.id}.grain",
                    message=f"unknown grain dimension {dim}",
                )
            )
        for dep in metric.derived_from:
            if dep not in {other.id for other in metrics}:
                diagnostics.append(
                    Diagnostic(code="DANGLING_REF", path=f"{metric.id}.derivedFrom", message=dep)
                )
    _reject_metric_cycles(metrics, diagnostics)


def _reject_metric_cycles(metrics: Sequence[MetricDef], diagnostics: list[Diagnostic]) -> None:
    sorter: TopologicalSorter[str] = TopologicalSorter()
    ids = {metric.id for metric in metrics}
    for metric in metrics:
        sorter.add(metric.id, *[dep for dep in metric.derived_from if dep in ids])
    try:
        sorter.prepare()
        while sorter.is_active():
            sorter.done(*sorter.get_ready())
    except CycleError:
        diagnostics.append(
            Diagnostic(code="RULE_CYCLE", path="<metrics>", message="derived metric cycle")
        )


def _check_links(
    objects: Sequence[ObjectTypeDef],
    links: Sequence[LinkDef],
    diagnostics: list[Diagnostic],
) -> None:
    object_index = _index(objects)
    for link in links:
        if link.source not in object_index:
            diagnostics.append(
                Diagnostic(code="DANGLING_REF", path=f"{link.id}.source", message=link.source)
            )
        if link.target not in object_index:
            diagnostics.append(
                Diagnostic(code="DANGLING_REF", path=f"{link.id}.target", message=link.target)
            )
        if not link.identity.source or not link.identity.target:
            diagnostics.append(
                Diagnostic(
                    code="MISSING_LINK_IDENTITY",
                    path=link.id,
                    message="link identity keys are required",
                )
            )
            continue
        source = object_index.get(link.source)
        target = object_index.get(link.target)
        if source is not None and link.identity.source not in {
            prop.id for prop in source.properties
        }:
            diagnostics.append(
                Diagnostic(
                    code="MISSING_LINK_IDENTITY",
                    path=f"{link.id}.identity.source",
                    message=link.identity.source,
                )
            )
        if target is not None and link.identity.target not in {
            prop.id for prop in target.properties
        }:
            diagnostics.append(
                Diagnostic(
                    code="MISSING_LINK_IDENTITY",
                    path=f"{link.id}.identity.target",
                    message=link.identity.target,
                )
            )


def _check_rules(
    metrics: Sequence[MetricDef],
    objects: Sequence[ObjectTypeDef],
    rules: Sequence[RuleDef],
    diagnostics: list[Diagnostic],
) -> None:
    metric_ids = {item.id for item in metrics}
    object_ids = {item.id for item in objects}
    rule_deps: dict[str, set[str]] = {}
    outputs: set[tuple[str, str]] = set()
    for rule in rules:
        for kind, output in (("claim", rule.claim), ("metric", rule.output_metric)):
            if output is not None:
                if (kind, output) in outputs:
                    diagnostics.append(
                        Diagnostic(
                            code="AMBIGUOUS_RULE",
                            path=rule.id,
                            message="each output must have one defining rule",
                        )
                    )
                outputs.add((kind, output))
        deps: set[str] = set()
        input_names = {item.name for item in rule.inputs}
        input_types: dict[str, str] = {}
        if len(input_names) != len(rule.inputs):
            diagnostics.append(
                Diagnostic(
                    code="INVALID_DEFINITION",
                    path=f"{rule.id}.inputs",
                    message="duplicate input name",
                )
            )
        for spec in rule.inputs:
            if spec.metric is not None and (
                spec.property is not None or spec.object_type is not None
            ):
                diagnostics.append(
                    Diagnostic(
                        code="INVALID_DEFINITION",
                        path=f"{rule.id}.inputs.{spec.name}",
                        message="input must select exactly one metric or object property",
                    )
                )
            if spec.metric is not None:
                definition = next((m for m in metrics if m.id == spec.metric), None)
                if definition is not None:
                    input_types[spec.name] = definition.value_type or "DECIMAL"
            if spec.property is not None:
                obj = next((o for o in objects if o.id == spec.object_type), None)
                prop = (
                    next((p for p in obj.properties if p.id == spec.property), None)
                    if obj
                    else None
                )
                if prop is None:
                    diagnostics.append(
                        Diagnostic(
                            code="DANGLING_REF",
                            path=f"{rule.id}.inputs.{spec.name}.property",
                            message="unknown object property",
                        )
                    )
                else:
                    input_types[spec.name] = prop.value_type
            if spec.metric is None and spec.property is None:
                diagnostics.append(
                    Diagnostic(
                        code="INVALID_DEFINITION",
                        path=f"{rule.id}.inputs.{spec.name}",
                        message="input needs metric or property",
                    )
                )
            if spec.metric is not None:
                if spec.metric not in metric_ids:
                    diagnostics.append(
                        Diagnostic(
                            code="DANGLING_REF",
                            path=f"{rule.id}.inputs.{spec.name}",
                            message=spec.metric,
                        )
                    )
                deps.add(spec.metric)
            if spec.object_type is not None and spec.object_type not in object_ids:
                diagnostics.append(
                    Diagnostic(
                        code="DANGLING_REF",
                        path=f"{rule.id}.inputs.{spec.name}",
                        message=spec.object_type,
                    )
                )
        for ref in collect_refs(rule.expression):
            if ref not in input_names:
                diagnostics.append(
                    Diagnostic(
                        code="DANGLING_REF",
                        path=f"{rule.id}.expression",
                        message=f"unknown input {ref}",
                    )
                )
        if rule.output_metric is not None:
            deps.add(rule.output_metric)
            if rule.output_metric not in metric_ids:
                diagnostics.append(
                    Diagnostic(
                        code="DANGLING_REF",
                        path=f"{rule.id}.outputMetric",
                        message=rule.output_metric,
                    )
                )
        if rule.claim is not None and not is_semantic_id(rule.claim):
            diagnostics.append(
                Diagnostic(code="INVALID_ID", path=f"{rule.id}.claim", message=rule.claim)
            )
        if rule.claim is not None and rule.output_metric is not None:
            diagnostics.append(
                Diagnostic(
                    code="INVALID_DEFINITION",
                    path=rule.id,
                    message="rule must not produce both a Claim and a Metric",
                )
            )
        try:
            result_type = expression_type(rule.expression, input_types)
            if rule.claim is not None and result_type != "BOOLEAN":
                raise ValueError("Claim expression must return BOOLEAN")
            if rule.output_metric is not None and result_type not in {"DECIMAL", "INTEGER"}:
                raise ValueError("Metric expression must return a number")
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(code="TYPE_MISMATCH", path=f"{rule.id}.expression", message=str(exc))
            )
        rule_deps[rule.id] = deps
    _reject_rule_cycles(rules, metrics, diagnostics)


def _reject_rule_cycles(
    rules: Sequence[RuleDef],
    metrics: Sequence[MetricDef],
    diagnostics: list[Diagnostic],
) -> None:
    metric_to_rule = {
        rule.output_metric: rule.id for rule in rules if rule.output_metric is not None
    }
    sorter: TopologicalSorter[str] = TopologicalSorter()
    known = {rule.id for rule in rules}
    for rule in rules:
        parents: list[str] = []
        for spec in rule.inputs:
            if spec.metric and spec.metric in metric_to_rule:
                parent = metric_to_rule[spec.metric]
                if parent in known:
                    parents.append(parent)
        sorter.add(rule.id, *parents)
    try:
        sorter.prepare()
        while sorter.is_active():
            sorter.done(*sorter.get_ready())
    except CycleError:
        diagnostics.append(
            Diagnostic(code="RULE_CYCLE", path="<rules>", message="rule dependency cycle")
        )


def _check_policies(
    rules: Sequence[RuleDef], policies: Sequence[PolicyDef], diagnostics: list[Diagnostic]
) -> None:
    rule_ids = {item.id for item in rules}
    grouped: dict[tuple[str, tuple[tuple[str, str], ...]], list[PolicyDef]] = defaultdict(list)
    for policy in policies:
        if policy.rule not in rule_ids:
            diagnostics.append(
                Diagnostic(code="DANGLING_REF", path=f"{policy.id}.rule", message=policy.rule)
            )
        if (
            policy.interval.effective_to is not None
            and policy.interval.effective_to <= policy.interval.effective_from
        ):
            diagnostics.append(
                Diagnostic(
                    code="INVALID_DEFINITION",
                    path=f"{policy.id}.interval",
                    message="effectiveTo must be after effectiveFrom",
                )
            )
        key = (policy.rule, tuple(sorted(policy.dimensions.items())))
        grouped[key].append(policy)
    for key, group in grouped.items():
        ordered = sorted(group, key=lambda item: item.interval.effective_from)
        for left, right in pairwise(ordered):
            left_end = left.interval.effective_to
            if left_end is None or right.interval.effective_from < left_end:
                diagnostics.append(
                    Diagnostic(
                        code="POLICY_OVERLAP",
                        path=right.id,
                        message=f"overlaps {left.id} for {key[0]}",
                    )
                )
        if len(ordered) >= 2:
            for left, right in pairwise(ordered):
                if (
                    left.interval.effective_to is not None
                    and left.interval.effective_to < right.interval.effective_from
                ):
                    diagnostics.append(
                        Diagnostic(
                            code="POLICY_GAP",
                            path=right.id,
                            message=f"gap after {left.id}",
                        )
                    )


def _check_actions(
    objects: Sequence[ObjectTypeDef],
    rules: Sequence[RuleDef],
    actions: Sequence[ActionDef],
    diagnostics: list[Diagnostic],
) -> None:
    object_ids = {item.id for item in objects}
    rule_ids = {item.id for item in rules}
    claim_ids = {item.claim for item in rules if item.claim}
    for action in actions:
        if action.target_object not in object_ids:
            diagnostics.append(
                Diagnostic(
                    code="DANGLING_REF",
                    path=f"{action.id}.targetObject",
                    message=action.target_object,
                )
            )
        for pre in action.preconditions:
            if pre not in rule_ids and pre not in claim_ids:
                diagnostics.append(
                    Diagnostic(code="DANGLING_REF", path=f"{action.id}.preconditions", message=pre)
                )


def _check_action_bindings(
    actions: Sequence[ActionDef],
    bindings: Sequence[ActionBindingDef],
    diagnostics: list[Diagnostic],
) -> None:
    action_ids = {item.id for item in actions}
    for binding in bindings:
        if binding.action not in action_ids:
            diagnostics.append(
                Diagnostic(code="DANGLING_REF", path=f"{binding.id}.action", message=binding.action)
            )


def _check_mappings(
    metrics: Sequence[MetricDef],
    objects: Sequence[ObjectTypeDef],
    mappings: Sequence[MappingDef],
    diagnostics: list[Diagnostic],
) -> None:
    metric_ids = {item.id for item in metrics}
    object_ids = {item.id for item in objects}
    groups: dict[tuple[str, str | None], list[MappingDef]] = defaultdict(list)
    for mapping in mappings:
        if mapping.target not in metric_ids and mapping.target not in object_ids:
            diagnostics.append(
                Diagnostic(code="DANGLING_REF", path=f"{mapping.id}.target", message=mapping.target)
            )
        if mapping.object_type not in object_ids:
            diagnostics.append(
                Diagnostic(
                    code="DANGLING_REF",
                    path=f"{mapping.id}.objectType",
                    message=mapping.object_type,
                )
            )
        groups[(mapping.target, mapping.perspective)].append(mapping)
    for (target, perspective), group in groups.items():
        if len(group) > 1:
            if target in object_ids and _object_mapping_properties_are_disjoint(group):
                continue
            diagnostics.append(
                Diagnostic(
                    code="AMBIGUOUS_MAPPING",
                    path=group[1].id,
                    message=f"multiple mappings for {target} perspective={perspective}",
                )
            )


def _object_mapping_properties_are_disjoint(mappings: Sequence[MappingDef]) -> bool:
    seen: set[str] = set()
    for mapping in mappings:
        current = set(mapping.property_fields)
        if not current or seen & current:
            return False
        seen.update(current)
    return True


def _check_integration_bindings(
    integrations: Sequence[IntegrationBindingDef],
    mappings: Sequence[MappingDef],
    action_bindings: Sequence[ActionBindingDef],
    diagnostics: list[Diagnostic],
) -> None:
    available: dict[str, MappingDef | ActionBindingDef] = {item.id: item for item in mappings}
    available.update({item.id: item for item in action_bindings})
    owners: dict[str, str] = {}
    for integration in integrations:
        references = (*integration.mappings, *integration.action_bindings)
        for reference in references:
            item = available.get(reference)
            if item is None:
                diagnostics.append(
                    Diagnostic(
                        code="DANGLING_REF",
                        path=f"{integration.id}.bindings",
                        message=reference,
                    )
                )
                continue
            if item.provider != integration.provider or item.source_id != integration.source_id:
                diagnostics.append(
                    Diagnostic(
                        code="INVALID_DEFINITION",
                        path=f"{integration.id}.bindings",
                        message=f"{reference} does not match provider/source",
                    )
                )
            previous = owners.get(reference)
            if previous is not None:
                diagnostics.append(
                    Diagnostic(
                        code="INVALID_DEFINITION",
                        path=f"{integration.id}.bindings",
                        message=f"{reference} is already owned by {previous}",
                    )
                )
            owners[reference] = integration.id
    for reference in available.keys() - owners.keys():
        diagnostics.append(
            Diagnostic(
                code="INVALID_DEFINITION",
                path=reference,
                message="binding is not owned by an IntegrationBinding",
            )
        )

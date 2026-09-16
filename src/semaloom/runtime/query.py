"""Authorized point query and in-process link composition."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from semaloom.core.bundle import CompiledBundle
from semaloom.core.diagnostics import Diagnostic
from semaloom.core.model import MappingDef
from semaloom.core.provider import ReadProvider
from semaloom.core.results import (
    EvidenceEnvelope,
    MetricSelect,
    ObjectSearchRequest,
    ObjectSelect,
    Observation,
    QueryContext,
    QueryRequest,
    SourceActivity,
)
from semaloom.core.values import scalar_value
from semaloom.runtime.auth import RequestActor, authorize_query


class QueryService:
    def __init__(self, bundle: CompiledBundle, provider: ReadProvider) -> None:
        self.bundle = bundle
        self.provider = provider

    def execute(self, request: QueryRequest, actor: RequestActor) -> EvidenceEnvelope:
        request_id = uuid.uuid4().hex
        decision = authorize_query(actor, "query")
        if not decision.allowed:
            forbidden = tuple(
                Observation(kind="FORBIDDEN", target=_select_target(item), reason=decision.reason)
                for item in request.select
            )
            return EvidenceEnvelope(
                request_id=request_id,
                release_digest=self.bundle.digest,
                observations=forbidden,
                diagnostics=(Diagnostic(code="FORBIDDEN", path="query", message=decision.reason),),
                status="FAILED",
                extras={"decisionId": decision.decision_id},
            )
        observations: list[Observation] = []
        activities: list[SourceActivity] = []
        diagnostics: list[Diagnostic] = []
        for item in request.select:
            if isinstance(item, MetricSelect):
                try:
                    item = item.model_copy(update={"bindings": self.normalize_bindings(item)})
                except ValueError:
                    observations.append(
                        Observation(
                            kind="UNAVAILABLE", target=item.metric, reason="INVALID_BINDINGS"
                        )
                    )
                    diagnostics.append(
                        Diagnostic(
                            code="INVALID_BINDINGS",
                            path=item.metric,
                            message="conflicting identity aliases",
                        )
                    )
                    continue
                metric = next((m for m in self.bundle.metrics if m.id == item.metric), None)
                if metric is not None:
                    mapping_perspectives = {
                        m.perspective for m in self.bundle.mappings if m.target == metric.id
                    }
                    needs_perspective = (
                        "perspective" in metric.grain and not metric.perspective
                    ) or len(mapping_perspectives - {None}) > 1
                    if "perspective" not in item.bindings and needs_perspective:
                        observations.append(
                            Observation(
                                kind="UNAVAILABLE", target=item.metric, reason="AMBIGUOUS_MAPPING"
                            )
                        )
                        diagnostics.append(
                            Diagnostic(
                                code="AMBIGUOUS_MAPPING",
                                path=item.metric,
                                message="select a business perspective",
                            )
                        )
                        continue
                    required = set(metric.grain) - (
                        {"perspective"} if metric.perspective else set()
                    )
                    allowed = set(metric.grain) | {"perspective"}
                    if not required <= set(item.bindings) or set(item.bindings) - allowed:
                        observations.append(
                            Observation(
                                kind="UNAVAILABLE", target=item.metric, reason="INVALID_BINDINGS"
                            )
                        )
                        diagnostics.append(
                            Diagnostic(
                                code="INVALID_BINDINGS",
                                path=item.metric,
                                message="provide the declared grain and optional perspective",
                            )
                        )
                        continue
                    period_error, period_activities = self._check_metric_period(
                        metric.object_type,
                        item,
                        request.context,
                        actor.tenant,
                        decision.decision_id,
                    )
                    activities.extend(period_activities)
                    if period_error is not None:
                        observations.append(period_error)
                        diagnostics.append(
                            Diagnostic(
                                code=period_error.reason or "PERIOD_MISMATCH",
                                path=item.metric,
                                message="requested period must match the selected object's period",
                            )
                        )
                        continue
                if any(rule.output_metric == item.metric for rule in self.bundle.rules):
                    from semaloom.runtime.eval import evaluate_derived_metric

                    obs, derived_activities, derived_diagnostics = evaluate_derived_metric(
                        self, actor, item, request.context
                    )
                    observations.append(obs)
                    activities.extend(derived_activities)
                    diagnostics.extend(derived_diagnostics)
                    continue
                obs, activity, error = self._metric(item, actor.tenant, decision.decision_id)
                if activity is not None:
                    activities.append(activity)
                if error is not None:
                    diagnostics.append(error)
            else:
                obs, object_activities, object_diagnostics = self._object(
                    item, actor.tenant, decision.decision_id
                )
                activities.extend(object_activities)
                diagnostics.extend(object_diagnostics)
            observations.append(obs)
        status = (
            "FAILED" if any(item.kind == "UNAVAILABLE" for item in observations) else "SUCCEEDED"
        )
        if diagnostics and status != "FAILED":
            status = (
                "FAILED"
                if any(item.code in {"NO_MAPPING", "INVALID_BINDINGS"} for item in diagnostics)
                else status
            )
        return EvidenceEnvelope(
            request_id=request_id,
            release_digest=self.bundle.digest,
            observations=tuple(observations),
            source_activities=tuple(activities),
            diagnostics=tuple(diagnostics),
            status=status,
            extras={"decisionId": decision.decision_id, "tenant": actor.tenant},
        )

    def normalize_bindings(self, item: MetricSelect) -> dict[str, str | int]:
        """Accept legacy identity aliases only when approved mappings prove their meaning."""
        bindings = dict(item.bindings)
        metric = next((m for m in self.bundle.metrics if m.id == item.metric), None)
        if metric is None:
            return bindings
        obj = next(o for o in self.bundle.object_types if o.id == metric.object_type)
        if len(obj.identity_keys) != 1:
            return bindings
        canonical = obj.identity_keys[0]
        for mapping in self.bundle.mappings:
            if mapping.object_type != obj.id:
                continue
            for alias, column in _grain_columns(mapping).items():
                if alias == canonical or column != mapping.physical.get("identityColumn"):
                    continue
                if alias in bindings and alias not in metric.grain:
                    value = bindings[alias]
                    if canonical in bindings and str(bindings[canonical]) != str(value):
                        raise ValueError("conflicting identity aliases")
                    bindings[canonical] = bindings.pop(alias)
        return bindings

    def _check_metric_period(
        self,
        object_id: str,
        item: MetricSelect,
        context: QueryContext,
        tenant: str,
        authorization_ref: str,
    ) -> tuple[Observation | None, tuple[SourceActivity, ...]]:
        obj = next(o for o in self.bundle.object_types if o.id == object_id)
        if obj.period is None:
            return None, ()
        if not set(obj.identity_keys) <= set(item.bindings):
            return Observation(
                kind="UNAVAILABLE", target=item.metric, reason="INVALID_BINDINGS"
            ), ()
        observation, activities, _ = self._object(
            ObjectSelect(
                object_type=obj.id,
                identity={key: str(item.bindings[key]) for key in obj.identity_keys},
                properties=(obj.period.from_property, obj.period.to_property),
            ),
            tenant,
            authorization_ref,
        )
        if observation.kind != "PRESENT":
            return observation.model_copy(update={"target": item.metric}), activities
        values = json.loads(observation.value or "{}")
        if (
            values.get(obj.period.from_property) != context.business_period["from"]
            or values.get(obj.period.to_property) != context.business_period["to"]
        ):
            return Observation(
                kind="UNAVAILABLE", target=item.metric, reason="PERIOD_MISMATCH"
            ), activities
        return None, activities

    def find_objects(self, request: ObjectSearchRequest, actor: RequestActor) -> dict[str, Any]:
        decision = authorize_query(actor, "query")
        if not decision.allowed:
            raise PermissionError("FORBIDDEN")
        obj = next((o for o in self.bundle.object_types if o.id == request.object_type), None)
        if obj is None or len(obj.identity_keys) != 1:
            raise ValueError("UNKNOWN_OR_UNSUPPORTED_OBJECT")
        definitions = {p.id: p for p in obj.properties}
        fields = set(request.properties) | set(request.filters) | set(obj.identity_keys)
        if fields - set(definitions) or len(fields) > 30:
            raise ValueError("INVALID_PROPERTIES")
        filters = {
            k: scalar_value(str(v), definitions[k].value_type) for k, v in request.filters.items()
        }
        candidates = [
            m
            for m in self.bundle.mappings
            if m.target == obj.id and fields <= _mapped_object_fields(m)
        ]
        if len(candidates) > 1:
            measure_ids = {prop.id for prop in obj.properties if prop.unit}
            identity = set(obj.identity_keys)
            requested = fields - identity
            if requested:
                candidates = [
                    item for item in candidates if requested <= _mapped_object_fields(item)
                ]
            else:
                descriptive = [
                    item
                    for item in candidates
                    if _descriptive_object_fields(item, measure_ids, identity)
                ]
                if descriptive:
                    candidates = descriptive
        if len(candidates) != 1:
            raise ValueError("AMBIGUOUS_MAPPING" if candidates else "NO_MAPPING")
        mapping = candidates[0]
        search = getattr(self.provider, "search_objects", None)
        if not callable(search):
            raise ValueError("SEARCH_NOT_SUPPORTED")
        page = search(
            mapping,
            tenant=actor.tenant,
            filters=filters,
            properties=tuple(sorted(fields)),
            limit=request.limit,
        )
        records = []
        seen: set[str] = set()
        for row in page.rows:
            key = str(row.get(obj.identity_keys[0]))
            if key in seen or row.get(obj.identity_keys[0]) is None:
                raise ValueError("CARDINALITY_VIOLATION")
            seen.add(key)
            records.append(
                {
                    "identity": {obj.identity_keys[0]: key},
                    "properties": {k: None if row.get(k) is None else str(row[k]) for k in fields},
                }
            )
        return {
            "objectType": obj.id,
            "objects": records,
            "hasMore": page.has_more,
            "requiresSelection": len(records) > 1 or page.has_more,
            "status": "SUCCEEDED" if page.kind == "PRESENT" else "FAILED",
            "reason": page.reason,
            "releaseDigest": self.bundle.digest,
            "sourceActivities": [
                {
                    "sourceId": mapping.source_id,
                    "mappingId": mapping.id,
                    "observedAt": page.observed_at,
                    "authorizationRef": decision.decision_id,
                    "queryDigest": _digest(request.model_dump()),
                }
            ],
        }

    def follow_link(
        self,
        *,
        link_id: str,
        source_identity: str,
        actor: RequestActor,
    ) -> EvidenceEnvelope:
        request_id = uuid.uuid4().hex
        decision = authorize_query(actor, "query")
        if not decision.allowed:
            return EvidenceEnvelope(
                request_id=request_id,
                release_digest=self.bundle.digest,
                observations=(
                    Observation(kind="FORBIDDEN", target=link_id, reason=decision.reason),
                ),
                diagnostics=(Diagnostic(code="FORBIDDEN", path=link_id, message=decision.reason),),
                status="FAILED",
            )
        link = next((item for item in self.bundle.links if item.id == link_id), None)
        if link is None:
            return EvidenceEnvelope(
                request_id=request_id,
                release_digest=self.bundle.digest,
                observations=(),
                diagnostics=(Diagnostic(code="NO_PATH", path=link_id, message="unknown link"),),
                status="FAILED",
            )
        source_mapping, source_error = self._object_mapping_for_property(
            link.source, link.identity.source
        )
        target_mapping, target_error = self._object_mapping_for_property(
            link.target, link.identity.target
        )
        if source_mapping is None or target_mapping is None:
            error = source_error or target_error or "NO_MAPPING"
            return EvidenceEnvelope(
                request_id=request_id,
                release_digest=self.bundle.digest,
                observations=(),
                diagnostics=(
                    Diagnostic(code=error, path=link_id, message="link mapping is not resolvable"),
                ),
                status="FAILED",
            )
        source_read = self.provider.fetch_object(
            source_mapping, tenant=actor.tenant, identity_value=source_identity
        )
        source_activity = SourceActivity(
            activity_id=uuid.uuid4().hex,
            mapping_id=source_mapping.id,
            source_id=source_mapping.source_id,
            query_digest=_digest(
                {"link": link_id, "sourceIdentity": source_identity, "tenant": actor.tenant}
            ),
            observed_at=source_read.observed_at,
            authorization_ref=decision.decision_id,
        )
        if source_read.kind == "UNAVAILABLE":
            reason = source_read.reason or "PROVIDER_ERROR"
            return EvidenceEnvelope(
                request_id=request_id,
                release_digest=self.bundle.digest,
                observations=(Observation(kind="UNAVAILABLE", target=link.target, reason=reason),),
                source_activities=(source_activity,),
                diagnostics=(Diagnostic(code=reason, path=link_id, message="source read failed"),),
                status="FAILED",
            )
        key = (
            source_read.values.get(link.identity.source) if source_read.kind == "PRESENT" else None
        )
        keys = [] if key is None else [str(key)]
        observations: list[Observation] = []
        activities: list[SourceActivity] = [source_activity]
        diagnostics: list[Diagnostic] = []
        for key in keys:
            target_read = self.provider.fetch_object(
                target_mapping, tenant=actor.tenant, identity_value=key
            )
            observed = Observation(
                kind=target_read.kind,
                target=link.target,
                bindings={"id": key},
                value=(
                    str(target_read.values.get("name") or key)
                    if target_read.kind == "PRESENT"
                    else None
                ),
                reason=target_read.reason,
                mapping_id=target_mapping.id,
                source_id=target_mapping.source_id,
                observed_at=target_read.observed_at,
            )
            observations.append(observed)
            if target_read.kind == "UNAVAILABLE":
                diagnostics.append(
                    Diagnostic(
                        code=target_read.reason or "PROVIDER_ERROR",
                        path=link_id,
                        message="target read failed",
                    )
                )
            activities.append(
                SourceActivity(
                    activity_id=uuid.uuid4().hex,
                    mapping_id=target_mapping.id,
                    source_id=target_mapping.source_id,
                    query_digest=_digest({"link": link_id, "key": key, "tenant": actor.tenant}),
                    observed_at=target_read.observed_at,
                    authorization_ref=decision.decision_id,
                )
            )
        return EvidenceEnvelope(
            request_id=request_id,
            release_digest=self.bundle.digest,
            observations=tuple(observations),
            source_activities=tuple(activities),
            diagnostics=tuple(diagnostics),
            status=(
                "FAILED"
                if any(item.kind == "UNAVAILABLE" for item in observations)
                else "SUCCEEDED"
            ),
            extras={
                "sourceSourceId": source_mapping.source_id,
                "targetSourceId": target_mapping.source_id,
                "keys": keys,
            },
        )

    def _metric(
        self, item: MetricSelect, tenant: str, authorization_ref: str
    ) -> tuple[Observation, SourceActivity | None, Diagnostic | None]:
        if any(key.lower() in {"sql", "url", "table", "column"} for key in item.bindings):
            return (
                Observation(kind="UNAVAILABLE", target=item.metric, reason="INVALID_BINDINGS"),
                None,
                Diagnostic(
                    code="INVALID_BINDINGS", path=item.metric, message="non-semantic binding"
                ),
            )
        perspective = item.bindings.get("perspective")
        mapping, mapping_error = self._mapping_for_target(
            item.metric, str(perspective) if perspective is not None else None
        )
        if mapping is None:
            reason = mapping_error or "NO_MAPPING"
            return (
                Observation(kind="UNAVAILABLE", target=item.metric, reason=reason),
                None,
                Diagnostic(code=reason, path=item.metric, message="mapping is not resolvable"),
            )
        try:
            identity_key = _identity_binding(item.bindings, mapping)
        except ValueError:
            return (
                Observation(kind="UNAVAILABLE", target=item.metric, reason="INVALID_BINDINGS"),
                None,
                Diagnostic(
                    code="INVALID_BINDINGS",
                    path=item.metric,
                    message="identity binding is required",
                ),
            )
        metric_def = next((entry for entry in self.bundle.metrics if entry.id == item.metric), None)
        allowed = set(metric_def.grain) if metric_def is not None else set(item.bindings)
        grain = _grain_columns(mapping)
        extra = {
            grain[key]: str(value)
            for key, value in item.bindings.items()
            if key in allowed
            and key in grain
            and grain[key] != mapping.physical.get("identityColumn")
        }
        observation = self.provider.fetch_metric(
            mapping,
            tenant=tenant,
            identity_value=identity_key,
            extra_filters=extra or None,
        )
        observation = observation.model_copy(
            update={
                "bindings": {str(k): v for k, v in item.bindings.items()},
                "unit": metric_def.unit if metric_def is not None else observation.unit,
                "value_type": (
                    metric_def.value_type if metric_def is not None else observation.value_type
                ),
            }
        )
        activity = SourceActivity(
            activity_id=uuid.uuid4().hex,
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            query_digest=_digest(
                {"metric": item.metric, "bindings": item.bindings, "tenant": tenant}
            ),
            authorization_ref=authorization_ref,
            observed_at=observation.observed_at,
            source_version=observation.source_version,
        )
        if observation.kind == "PRESENT" and metric_def is not None:
            try:
                scalar_value(observation.value or "", metric_def.value_type or "DECIMAL")
            except ValueError:
                return (
                    observation.model_copy(
                        update={"kind": "UNAVAILABLE", "value": None, "reason": "TYPE_MISMATCH"}
                    ),
                    activity,
                    Diagnostic(
                        code="TYPE_MISMATCH",
                        path=item.metric,
                        message="source value does not match the metric type",
                    ),
                )
        return observation, activity, None

    def _object(
        self, item: ObjectSelect, tenant: str, authorization_ref: str
    ) -> tuple[Observation, tuple[SourceActivity, ...], tuple[Diagnostic, ...]]:
        object_type = next(
            (entry for entry in self.bundle.object_types if entry.id == item.object_type), None
        )
        if object_type is None or set(item.identity) != set(object_type.identity_keys):
            return (
                Observation(kind="UNAVAILABLE", target=item.object_type, reason="INVALID_BINDINGS"),
                (),
                (
                    Diagnostic(
                        code="INVALID_BINDINGS",
                        path=item.object_type,
                        message="object identity does not match the semantic definition",
                    ),
                ),
            )
        allowed_properties = {entry.id for entry in object_type.properties}
        if set(item.properties) - allowed_properties:
            return (
                Observation(kind="UNAVAILABLE", target=item.object_type, reason="INVALID_BINDINGS"),
                (),
                (
                    Diagnostic(
                        code="INVALID_BINDINGS",
                        path=item.object_type,
                        message="unknown object property",
                    ),
                ),
            )
        descriptive = {entry.id for entry in object_type.properties if not entry.unit}
        requested = (set(item.properties) or descriptive) - set(object_type.identity_keys)
        if len(object_type.identity_keys) != 1:
            return (
                Observation(
                    kind="UNAVAILABLE",
                    target=item.object_type,
                    reason="COMPOSITE_IDENTITY_NOT_SUPPORTED",
                ),
                (),
                (
                    Diagnostic(
                        code="COMPOSITE_IDENTITY_NOT_SUPPORTED",
                        path=item.object_type,
                        message="use a declared stable scalar identity",
                    ),
                ),
            )
        if not requested:
            # Identity-only reads must establish that the object actually exists.
            requested = set(object_type.identity_keys)
        assignments: dict[str, set[str]] = {}
        mappings: dict[str, MappingDef] = {}
        for property_id in requested:
            mapping, mapping_error = self._object_mapping_for_property(
                item.object_type, property_id
            )
            if mapping is None:
                reason = mapping_error or "NO_MAPPING"
                return (
                    Observation(kind="UNAVAILABLE", target=item.object_type, reason=reason),
                    (),
                    (
                        Diagnostic(
                            code=reason,
                            path=f"{item.object_type}.{property_id}",
                            message="property mapping is not resolvable",
                        ),
                    ),
                )
            mappings[mapping.id] = mapping
            assignments.setdefault(mapping.id, set()).add(property_id)
        identity_value = item.identity[object_type.identity_keys[0]]
        values: dict[str, Any] = dict(item.identity)
        activities: list[SourceActivity] = []
        diagnostics: list[Diagnostic] = []
        failed = None
        for mapping_id, properties in assignments.items():
            mapping = mappings[mapping_id]
            result = self.provider.fetch_object(
                mapping, tenant=tenant, identity_value=identity_value
            )
            activities.append(
                SourceActivity(
                    activity_id=uuid.uuid4().hex,
                    mapping_id=mapping.id,
                    source_id=mapping.source_id,
                    query_digest=_digest(
                        {
                            "object": item.object_type,
                            "identity": item.identity,
                            "properties": sorted(properties),
                            "tenant": tenant,
                        }
                    ),
                    observed_at=result.observed_at,
                    authorization_ref=authorization_ref,
                )
            )
            if result.kind != "PRESENT":
                failed = result
                if result.kind == "UNAVAILABLE":
                    diagnostics.append(
                        Diagnostic(
                            code=result.reason or "PROVIDER_ERROR",
                            path=mapping.id,
                            message="object property read failed",
                        )
                    )
                break
            for key in properties:
                values[key] = result.values.get(key)
        if failed is not None:
            return (
                Observation(
                    kind=failed.kind,
                    target=item.object_type,
                    reason=failed.reason,
                    mapping_id=failed.mapping_id,
                    source_id=failed.source_id,
                    observed_at=failed.observed_at,
                ),
                tuple(activities),
                tuple(diagnostics),
            )
        visible = set(item.properties) if item.properties else allowed_properties
        return (
            Observation(
                kind="PRESENT",
                target=item.object_type,
                value=json.dumps(
                    {key: None if values.get(key) is None else str(values[key]) for key in visible},
                    sort_keys=True,
                ),
            ),
            tuple(activities),
            (),
        )

    def _object_mapping_for_property(
        self, object_type: str, property_id: str
    ) -> tuple[MappingDef | None, str | None]:
        candidates = [
            mapping
            for mapping in self.bundle.mappings
            if mapping.target == object_type and property_id in _mapped_object_fields(mapping)
        ]
        if len(candidates) == 1:
            return candidates[0], None
        if len(candidates) > 1:
            return None, "AMBIGUOUS_MAPPING"
        return None, "NO_MAPPING"

    def _mapping_for_target(
        self, target: str, perspective: str | None
    ) -> tuple[MappingDef | None, str | None]:
        candidates = [
            item
            for item in self.bundle.mappings
            if item.target == target
            and (perspective is None or item.perspective is None or item.perspective == perspective)
        ]
        if len(candidates) == 1:
            return candidates[0], None
        if len(candidates) > 1:
            return None, "AMBIGUOUS_MAPPING"
        return None, "NO_MAPPING"


def _select_target(item: MetricSelect | ObjectSelect) -> str:
    return item.metric if isinstance(item, MetricSelect) else item.object_type


def _grain_columns(mapping: MappingDef) -> dict[str, str]:
    raw = mapping.physical.get("grainColumns")
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _descriptive_object_fields(
    mapping: MappingDef, measure_ids: set[str], identity: set[str]
) -> set[str]:
    fields: set[str] = set()
    for key in ("propertyColumns", "propertyPointers"):
        raw = mapping.physical.get(key)
        if isinstance(raw, dict):
            fields.update(str(item) for item in raw)
    return fields - measure_ids - identity


def _mapped_object_fields(mapping: MappingDef) -> set[str]:
    fields: set[str] = set()
    for key in ("grainColumns", "propertyColumns", "grainPointers", "propertyPointers"):
        raw = mapping.physical.get(key)
        if isinstance(raw, dict):
            fields.update(str(item) for item in raw)
    return fields


def _identity_binding(bindings: dict[str, str | int], mapping: MappingDef) -> str:
    identity_col = mapping.physical.get("identityColumn")
    for key, column in _grain_columns(mapping).items():
        if column == identity_col and key in bindings:
            return str(bindings[key])
    raise ValueError("identity binding is required")


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()

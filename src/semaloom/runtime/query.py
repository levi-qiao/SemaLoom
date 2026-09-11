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
    ObjectSelect,
    Observation,
    QueryRequest,
    SourceActivity,
)
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
                obs, activity, error = self._metric(item, actor.tenant, decision.decision_id)
            else:
                obs, activity, error = self._object(item, actor.tenant, decision.decision_id)
            observations.append(obs)
            if activity is not None:
                activities.append(activity)
            if error is not None:
                diagnostics.append(error)
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
        source_mapping, source_error = self._mapping_for_target(link.source, None)
        target_mapping, target_error = self._mapping_for_target(link.target, None)
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
            update={"bindings": {str(k): v for k, v in item.bindings.items()}}
        )
        activity = SourceActivity(
            activity_id=uuid.uuid4().hex,
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            query_digest=_digest(
                {"metric": item.metric, "bindings": item.bindings, "tenant": tenant}
            ),
            authorization_ref=authorization_ref,
        )
        return observation, activity, None

    def _object(
        self, item: ObjectSelect, tenant: str, authorization_ref: str
    ) -> tuple[Observation, SourceActivity | None, Diagnostic | None]:
        mapping, mapping_error = self._mapping_for_target(item.object_type, None)
        if mapping is None:
            reason = mapping_error or "NO_MAPPING"
            return (
                Observation(kind="UNAVAILABLE", target=item.object_type, reason=reason),
                None,
                Diagnostic(code=reason, path=item.object_type, message="mapping is not resolvable"),
            )
        object_type = next(
            (entry for entry in self.bundle.object_types if entry.id == item.object_type), None
        )
        if object_type is None or set(item.identity) != set(object_type.identity_keys):
            return (
                Observation(kind="UNAVAILABLE", target=item.object_type, reason="INVALID_BINDINGS"),
                None,
                Diagnostic(
                    code="INVALID_BINDINGS",
                    path=item.object_type,
                    message="object identity does not match the semantic definition",
                ),
            )
        allowed_properties = {entry.id for entry in object_type.properties}
        if set(item.properties) - allowed_properties:
            return (
                Observation(kind="UNAVAILABLE", target=item.object_type, reason="INVALID_BINDINGS"),
                None,
                Diagnostic(
                    code="INVALID_BINDINGS",
                    path=item.object_type,
                    message="unknown object property",
                ),
            )
        identity_value = item.identity[object_type.identity_keys[0]]
        result = self.provider.fetch_object(mapping, tenant=tenant, identity_value=identity_value)
        if result.kind != "PRESENT":
            obs = Observation(
                kind=result.kind,
                target=item.object_type,
                reason=result.reason,
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=result.observed_at,
            )
        else:
            obs = Observation(
                kind="PRESENT",
                target=item.object_type,
                value=json.dumps(
                    {
                        key: (
                            None if result.values.get(key) is None else str(result.values.get(key))
                        )
                        for key in result.values
                        if key in item.properties or not item.properties
                    },
                    sort_keys=True,
                ),
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=result.observed_at,
            )
        activity = SourceActivity(
            activity_id=uuid.uuid4().hex,
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            query_digest=_digest(
                {"object": item.object_type, "identity": item.identity, "tenant": tenant}
            ),
            authorization_ref=authorization_ref,
        )
        diagnostic = (
            Diagnostic(
                code=result.reason or "PROVIDER_ERROR",
                path=item.object_type,
                message="object read failed",
            )
            if result.kind == "UNAVAILABLE"
            else None
        )
        return obs, activity, diagnostic

    def _mapping_for_target(
        self, target: str, perspective: str | None
    ) -> tuple[MappingDef | None, str | None]:
        candidates = [
            item
            for item in self.bundle.mappings
            if item.target == target and (perspective is None or item.perspective == perspective)
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


def _identity_binding(bindings: dict[str, str | int], mapping: MappingDef) -> str:
    identity_col = mapping.physical.get("identityColumn")
    for key, column in _grain_columns(mapping).items():
        if column == identity_col and key in bindings:
            return str(bindings[key])
    raise ValueError("identity binding is required")


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()

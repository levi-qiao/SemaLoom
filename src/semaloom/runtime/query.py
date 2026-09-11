"""Authorized point query and in-process link composition."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from semaloom.adapters.postgres import PostgresReadProvider
from semaloom.core.bundle import CompiledBundle
from semaloom.core.diagnostics import Diagnostic
from semaloom.core.model import MappingDef
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
    def __init__(self, bundle: CompiledBundle, provider: PostgresReadProvider) -> None:
        self.bundle = bundle
        self.provider = provider
        self._mappings = {item.id: item for item in bundle.mappings}

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
                obs, activity, error = self._metric(item, actor.tenant)
            else:
                obs, activity, error = self._object(item, actor.tenant)
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
        source_mapping = self._mapping_for_target(link.source, None)
        target_mapping = self._mapping_for_target(link.target, None)
        if source_mapping is None or target_mapping is None:
            return EvidenceEnvelope(
                request_id=request_id,
                release_digest=self.bundle.digest,
                observations=(),
                diagnostics=(
                    Diagnostic(code="NO_MAPPING", path=link_id, message="link mapping missing"),
                ),
                status="FAILED",
            )
        grain = _grain_columns(source_mapping)
        key_column = grain.get(link.identity.source) or str(
            source_mapping.physical.get("identityColumn") or link.identity.source
        )
        keys = self.provider.fetch_keys(
            source_mapping,
            tenant=actor.tenant,
            identity_value=source_identity,
            key_column=key_column,
        )
        observations: list[Observation] = []
        activities: list[SourceActivity] = []
        for key in keys:
            row = self.provider.fetch_object(
                target_mapping, tenant=actor.tenant, identity_value=key
            )
            observed = Observation(
                kind="PRESENT" if row else "MISSING",
                target=link.target,
                bindings={"id": key},
                value=None if row is None else str(row.get("name") or key),
                mapping_id=target_mapping.id,
                source_id=target_mapping.source_id,
            )
            observations.append(observed)
            activities.append(
                SourceActivity(
                    activity_id=uuid.uuid4().hex,
                    mapping_id=target_mapping.id,
                    source_id=target_mapping.source_id,
                    query_digest=_digest({"link": link_id, "key": key, "tenant": actor.tenant}),
                    authorization_ref=decision.decision_id,
                )
            )
        return EvidenceEnvelope(
            request_id=request_id,
            release_digest=self.bundle.digest,
            observations=tuple(observations),
            source_activities=tuple(activities),
            status="SUCCEEDED",
            extras={
                "sourceSourceId": source_mapping.source_id,
                "targetSourceId": target_mapping.source_id,
                "keys": keys,
            },
        )

    def _metric(
        self, item: MetricSelect, tenant: str
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
        mapping = self._mapping_for_target(
            item.metric, str(perspective) if perspective is not None else None
        )
        if mapping is None:
            return (
                Observation(kind="UNAVAILABLE", target=item.metric, reason="NO_MAPPING"),
                None,
                Diagnostic(code="NO_MAPPING", path=item.metric, message="no mapping"),
            )
        identity_key = _identity_binding(item.bindings, mapping)
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
        )
        return observation, activity, None

    def _object(
        self, item: ObjectSelect, tenant: str
    ) -> tuple[Observation, SourceActivity | None, Diagnostic | None]:
        mapping = self._mapping_for_target(item.object_type, None)
        if mapping is None:
            return (
                Observation(kind="UNAVAILABLE", target=item.object_type, reason="NO_MAPPING"),
                None,
                Diagnostic(code="NO_MAPPING", path=item.object_type, message="no mapping"),
            )
        identity_value = next(iter(item.identity.values()))
        row = self.provider.fetch_object(mapping, tenant=tenant, identity_value=identity_value)
        if row is None:
            obs = Observation(
                kind="MISSING",
                target=item.object_type,
                mapping_id=mapping.id,
                source_id=mapping.source_id,
            )
        else:
            obs = Observation(
                kind="PRESENT",
                target=item.object_type,
                value=json.dumps(
                    {
                        key: str(row.get(key))
                        for key in row
                        if key in item.properties or not item.properties
                    },
                    sort_keys=True,
                ),
                mapping_id=mapping.id,
                source_id=mapping.source_id,
            )
        activity = SourceActivity(
            activity_id=uuid.uuid4().hex,
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            query_digest=_digest(
                {"object": item.object_type, "identity": item.identity, "tenant": tenant}
            ),
        )
        return obs, activity, None

    def _mapping_for_target(self, target: str, perspective: str | None) -> MappingDef | None:
        candidates = [
            item
            for item in self.bundle.mappings
            if item.target == target and (perspective is None or item.perspective == perspective)
        ]
        if len(candidates) == 1:
            return candidates[0]
        if perspective is None and len(candidates) > 1:
            return candidates[0]
        return None


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

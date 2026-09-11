"""Query, observation, claim, and evidence types used by later runtime tasks."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from semaloom.core.diagnostics import Diagnostic

ObservationKind = Literal["PRESENT", "MISSING", "NULL", "UNAVAILABLE", "FORBIDDEN"]
ClaimTruth = Literal["TRUE", "FALSE", "UNKNOWN"]
ExecutionStatus = Literal["SUCCEEDED", "PARTIAL", "FAILED"]


class _Frozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        validate_by_name=True,
    )


class MetricSelect(_Frozen):
    metric: str
    bindings: dict[str, str | int]


class ObjectSelect(_Frozen):
    object_type: str = Field(alias="objectType")
    identity: dict[str, str]
    properties: tuple[str, ...] = ()


class QueryContext(_Frozen):
    business_period: dict[str, str] = Field(alias="businessPeriod")
    scope: dict[str, str] = Field(default_factory=dict)


class QueryRequest(_Frozen):
    api_version: Literal["semaloom/v0.1"] = Field(alias="apiVersion")
    select: tuple[MetricSelect | ObjectSelect, ...]
    context: QueryContext


class Observation(_Frozen):
    kind: ObservationKind
    target: str
    bindings: dict[str, str | int] = Field(default_factory=dict)
    value: str | None = None
    value_type: str | None = Field(default=None, alias="valueType")
    unit: str | None = None
    source_id: str | None = Field(default=None, alias="sourceId")
    mapping_id: str | None = Field(default=None, alias="mappingId")
    observed_at: str | None = Field(default=None, alias="observedAt")
    source_version: str | None = Field(default=None, alias="sourceVersion")
    reason: str | None = None


class Claim(_Frozen):
    claim_id: str = Field(alias="claimId")
    evaluation_id: str = Field(alias="evaluationId")
    truth: ClaimTruth
    predicate_version: str = Field(alias="predicateVersion")
    reason_codes: tuple[str, ...] = Field(default=(), alias="reasonCodes")
    evidence_refs: tuple[str, ...] = Field(default=(), alias="evidenceRefs")
    context: dict[str, str] = Field(default_factory=dict)


class SourceActivity(_Frozen):
    activity_id: str = Field(alias="activityId")
    mapping_id: str = Field(alias="mappingId")
    source_id: str = Field(alias="sourceId")
    query_digest: str = Field(alias="queryDigest")
    observed_at: str | None = Field(default=None, alias="observedAt")
    source_version: str | None = Field(default=None, alias="sourceVersion")
    authorization_ref: str | None = Field(default=None, alias="authorizationRef")


class EvidenceEnvelope(_Frozen):
    request_id: str = Field(alias="requestId")
    release_digest: str = Field(alias="releaseDigest")
    observations: tuple[Observation, ...]
    claims: tuple[Claim, ...] = ()
    source_activities: tuple[SourceActivity, ...] = Field(default=(), alias="sourceActivities")
    diagnostics: tuple[Diagnostic, ...] = ()
    status: ExecutionStatus
    extras: dict[str, Any] = Field(default_factory=dict)

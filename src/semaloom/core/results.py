"""Query, observation, claim, and evidence types used by later runtime tasks."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from semaloom.core.diagnostics import Diagnostic
from semaloom.core.values import scalar_value

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

    @field_validator("business_period")
    @classmethod
    def valid_period(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != {"from", "to"}:
            raise ValueError("businessPeriod requires from and to")
        start = scalar_value(value["from"], "DATE")
        end = scalar_value(value["to"], "DATE")
        if str(start) >= str(end):
            raise ValueError("businessPeriod must be half-open and non-empty")
        return value


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
    rule_id: str | None = Field(default=None, alias="ruleId")


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


class ObjectSearchRequest(_Frozen):
    object_type: str = Field(alias="objectType")
    filters: dict[str, str | int | bool] = Field(default_factory=dict)
    properties: tuple[str, ...] = ()
    limit: int = Field(default=20, ge=1, le=50)


class PopulationComparison(_Frozen):
    identity: dict[str, str] | None = Field(
        default=None,
        description="Exact object identity from find_objects; choose identity OR filters.",
    )
    filters: dict[str, str | int | bool] | None = Field(
        default=None,
        description=(
            "Exact subject properties on the metric's objectType, e.g. its name property. "
            "Selects the subject INSIDE the full population; does not filter the denominator."
        ),
    )
    operation: Literal["shareOfTotal", "percentAboveMean", "outperforms"]
    direction: Literal["higher", "lower"] = "higher"

    @model_validator(mode="after")
    def one_subject_selector(self) -> Self:
        if bool(self.identity) == bool(self.filters):
            raise ValueError("provide exactly one non-empty identity or filters for the subject")
        return self


class PopulationRequest(_Frozen):
    metric: str
    year: int = Field(ge=1900, le=2200)
    filters: dict[str, str | int | bool] = Field(default_factory=dict)
    operation: Literal["mean", "sum", "min", "max", "count"] = "mean"
    missing_policy: Literal["reject", "exclude"] = Field(default="reject", alias="missingPolicy")
    comparison: PopulationComparison | None = None

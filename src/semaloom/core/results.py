"""Query, observation, claim, and evidence types used by later runtime tasks."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from semaloom.core.diagnostics import Diagnostic
from semaloom.core.values import scalar_value
from semaloom.core.wire import wire_config

ObservationKind = Literal["PRESENT", "MISSING", "NULL", "UNAVAILABLE", "FORBIDDEN"]
ClaimTruth = Literal["TRUE", "FALSE", "UNKNOWN"]
ExecutionStatus = Literal["SUCCEEDED", "PARTIAL", "FAILED"]


class _Frozen(BaseModel):
    model_config = wire_config()


class MetricSelect(_Frozen):
    metric: str
    bindings: dict[str, str | int]


class ObjectSelect(_Frozen):
    object_type: str
    identity: dict[str, str]
    properties: tuple[str, ...] = ()


class QueryContext(_Frozen):
    business_period: dict[str, str]
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
    api_version: Literal["semaloom/v0.1"]
    select: tuple[MetricSelect | ObjectSelect, ...]
    context: QueryContext


class Observation(_Frozen):
    kind: ObservationKind
    target: str
    bindings: dict[str, str | int] = Field(default_factory=dict)
    value: str | None = None
    value_type: str | None = None
    unit: str | None = None
    source_id: str | None = None
    mapping_id: str | None = None
    observed_at: str | None = None
    source_version: str | None = None
    reason: str | None = None
    rule_id: str | None = None


class Claim(_Frozen):
    claim_id: str
    evaluation_id: str
    truth: ClaimTruth
    predicate_version: str
    reason_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    context: dict[str, str] = Field(default_factory=dict)


class SourceActivity(_Frozen):
    activity_id: str
    mapping_id: str
    source_id: str
    query_digest: str
    observed_at: str | None = None
    source_version: str | None = None
    authorization_ref: str | None = None


class EvidenceEnvelope(_Frozen):
    request_id: str
    release_digest: str
    observations: tuple[Observation, ...]
    claims: tuple[Claim, ...] = ()
    source_activities: tuple[SourceActivity, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    status: ExecutionStatus
    extras: dict[str, Any] = Field(default_factory=dict)


class ObjectSearchRequest(_Frozen):
    object_type: str
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
    missing_policy: Literal["reject", "exclude"] = "reject"
    comparison: PopulationComparison | None = None

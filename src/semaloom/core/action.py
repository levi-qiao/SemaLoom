"""Action plan and execution states. Bindings stay in the integration layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ActionStatus = Literal[
    "PLANNED",
    "APPROVAL_PENDING",
    "APPROVED",
    "REJECTED",
    "EXPIRED",
    "CANCELLED",
    "DENIED",
    "STALE_PLAN",
    "EXECUTING",
    "SUCCEEDED",
    "FAILED",
    "OUTCOME_UNKNOWN",
    "VERIFICATION_PENDING",
    "VERIFIED",
    "VERIFICATION_FAILED",
]


class ActionPlan(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        validate_by_name=True,
    )

    plan_id: str = Field(alias="planId")
    action_id: str = Field(alias="actionId")
    action_version: str = Field(alias="actionVersion")
    tenant: str
    actor: str
    target: dict[str, str]
    parameters: dict[str, str]
    digest: str
    release_digest: str = Field(alias="releaseDigest")
    expires_at: str = Field(alias="expiresAt")
    expected_effect: str = Field(alias="expectedEffect")


class ActionExecution(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        validate_by_name=True,
    )

    execution_id: str = Field(alias="executionId")
    plan_id: str = Field(alias="planId")
    status: ActionStatus
    payload_digest: str = Field(alias="payloadDigest")
    external_ref: str | None = Field(default=None, alias="externalRef")

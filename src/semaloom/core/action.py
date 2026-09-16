"""Action plan and execution states. Bindings stay in the integration layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from semaloom.core.wire import wire_config

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
    model_config = wire_config()

    plan_id: str
    action_id: str
    action_version: str
    tenant: str
    actor: str
    target: dict[str, str]
    parameters: dict[str, str]
    digest: str
    release_digest: str
    expires_at: str
    expected_effect: str


class ActionExecution(BaseModel):
    model_config = wire_config()

    execution_id: str
    plan_id: str
    status: ActionStatus
    payload_digest: str
    external_ref: str | None = None

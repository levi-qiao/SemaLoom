"""Authorization decision and scope. A boolean is not a decision."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from semaloom.core.wire import wire_config


class ResourceScope(BaseModel):
    model_config = wire_config()

    tenants: tuple[str, ...]
    object_types: tuple[str, ...] = ()
    identities: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()


class AccessDecision(BaseModel):
    model_config = wire_config()

    allowed: bool
    effect: Literal["ALLOW", "DENY"]
    reason: str
    scope: ResourceScope
    policy_revision: str
    decision_id: str

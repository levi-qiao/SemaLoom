"""Authorization decision and scope. A boolean is not a decision."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResourceScope(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        validate_by_name=True,
    )

    tenants: tuple[str, ...]
    object_types: tuple[str, ...] = Field(default=(), alias="objectTypes")
    identities: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()


class AccessDecision(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        validate_by_name=True,
    )

    allowed: bool
    effect: Literal["ALLOW", "DENY"]
    reason: str
    scope: ResourceScope
    policy_revision: str = Field(alias="policyRevision")
    decision_id: str = Field(alias="decisionId")

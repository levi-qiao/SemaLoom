"""Immutable compiled bundle. Digest covers payload, not online proofs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from semaloom.core.model import (
    ActionBindingDef,
    ActionDef,
    AuthorizationProfileDef,
    DomainPackDef,
    LinkDef,
    MappingDef,
    MetricDef,
    ObjectTypeDef,
    PolicyDef,
    RuleDef,
)

OnlineValidation = Literal["NOT_RUN", "PASSED", "FAILED"]


class CompiledBundle(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        validate_by_name=True,
    )

    api_version: Literal["semaloom/v0.1"] = Field(alias="apiVersion")
    format_version: str = Field(alias="formatVersion")
    compiler_version: str = Field(alias="compilerVersion")
    ir_version: str = Field(alias="irVersion")
    digest: str
    online_validation: OnlineValidation = Field(alias="onlineValidation")
    packs: tuple[DomainPackDef, ...]
    object_types: tuple[ObjectTypeDef, ...] = Field(alias="objectTypes")
    metrics: tuple[MetricDef, ...]
    links: tuple[LinkDef, ...]
    rules: tuple[RuleDef, ...]
    policies: tuple[PolicyDef, ...]
    actions: tuple[ActionDef, ...]
    authorization_profiles: tuple[AuthorizationProfileDef, ...] = Field(
        alias="authorizationProfiles"
    )
    mappings: tuple[MappingDef, ...]
    action_bindings: tuple[ActionBindingDef, ...] = Field(alias="actionBindings")
    physical_digests: dict[str, str] = Field(alias="physicalDigests")
    extras: dict[str, Any] = Field(default_factory=dict)

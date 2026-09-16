"""Immutable compiled bundle. Digest covers payload, not online proofs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from semaloom.core.model import (
    ActionBindingDef,
    ActionDef,
    AuthorizationProfileDef,
    DomainPackDef,
    IntegrationBindingDef,
    LinkDef,
    MappingDef,
    MetricDef,
    ObjectTypeDef,
    PolicyDef,
    RuleDef,
)
from semaloom.core.wire import wire_config

OnlineValidation = Literal["NOT_RUN", "PASSED", "FAILED"]


class CompiledBundle(BaseModel):
    model_config = wire_config()

    api_version: Literal["semaloom/v0.1"]
    format_version: str
    compiler_version: str
    ir_version: str
    digest: str
    online_validation: OnlineValidation
    packs: tuple[DomainPackDef, ...]
    object_types: tuple[ObjectTypeDef, ...]
    metrics: tuple[MetricDef, ...]
    links: tuple[LinkDef, ...]
    rules: tuple[RuleDef, ...]
    policies: tuple[PolicyDef, ...]
    actions: tuple[ActionDef, ...]
    authorization_profiles: tuple[AuthorizationProfileDef, ...]
    integration_bindings: tuple[IntegrationBindingDef, ...]
    mappings: tuple[MappingDef, ...]
    action_bindings: tuple[ActionBindingDef, ...]
    physical_digests: dict[str, str]
    extras: dict[str, Any] = Field(default_factory=dict)

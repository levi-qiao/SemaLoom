"""JSON Schema export for T01 documents (draft 2020-12)."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

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

_MODELS = (
    DomainPackDef,
    ObjectTypeDef,
    MetricDef,
    LinkDef,
    RuleDef,
    PolicyDef,
    ActionDef,
    AuthorizationProfileDef,
    MappingDef,
    ActionBindingDef,
    IntegrationBindingDef,
)


def document_schemas() -> dict[str, Any]:
    return {model.__name__: TypeAdapter(model).json_schema() for model in _MODELS}

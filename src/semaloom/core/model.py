"""Protocol-neutral semantic definitions. Physical fields stay in bindings."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from semaloom.core.expr import Expr, parse_expr
from semaloom.core.wire import wire_config

ValueType = Literal["STRING", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DATETIME"]
Cardinality = Literal["ONE", "MANY"]
Aggregation = Literal["NONE", "SUM", "MAX", "MIN"]
PolicyEnd = str | None


class _Doc(BaseModel):
    model_config = wire_config()

    api_version: Literal["semaloom/v0.1"]
    kind: str
    id: str
    version: str
    label: str | None = None
    description: str | None = None


class EmbeddedProperty(BaseModel):
    model_config = wire_config()

    id: str
    value_type: ValueType
    required: bool = False
    label: str | None = None
    unit: str | None = None
    aggregation: Aggregation | None = None
    aliases: tuple[str, ...] = ()


class ObjectPeriod(BaseModel):
    model_config = wire_config()
    from_property: str
    to_property: str


class PopulationSpec(BaseModel):
    """Approved population grain: one object per statistical unit and year."""

    model_config = wire_config()
    unit_property: str
    year_property: str
    description: str = Field(min_length=1)


class ObjectTypeDef(_Doc):
    kind: Literal["ObjectType"] = "ObjectType"
    identity_keys: tuple[str, ...]
    properties: tuple[EmbeddedProperty, ...]
    period: ObjectPeriod | None = None
    population: PopulationSpec | None = None


class MetricDef(_Doc):
    kind: Literal["Metric"] = "Metric"
    object_type: str
    property: str | None = None
    select: dict[str, str] = Field(default_factory=dict)
    value_type: Literal["DECIMAL", "INTEGER"] | None = None
    unit: str | None = None
    grain: tuple[str, ...] = ()
    aggregation: Aggregation = "NONE"
    population: PopulationSpec | None = None
    aliases: tuple[str, ...] = Field(default=(), max_length=30)
    perspective: str | None = None
    derived_from: tuple[str, ...] = ()


class LinkIdentity(BaseModel):
    model_config = wire_config()

    source: str
    target: str


class LinkDef(_Doc):
    kind: Literal["Link"] = "Link"
    source: str
    target: str
    identity: LinkIdentity
    cardinality: Cardinality
    traversal: Literal["FORWARD"] = "FORWARD"


class RuleInput(BaseModel):
    model_config = wire_config()

    name: str
    metric: str | None = None
    property: str | None = None
    object_type: str | None = None
    required: bool = True


class RuleDef(_Doc):
    kind: Literal["Rule"] = "Rule"
    inputs: tuple[RuleInput, ...]
    expression: Expr
    claim: str | None = None
    output_metric: str | None = None
    applicability: tuple[str, ...] = ()

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> RuleDef:
        payload = dict(data)
        payload["expression"] = parse_expr(payload["expression"])
        return cls.model_validate(payload)


class PolicyInterval(BaseModel):
    model_config = wire_config()

    effective_from: str
    effective_to: str | None = None


class PolicyDef(_Doc):
    kind: Literal["Policy"] = "Policy"
    rule: str
    interval: PolicyInterval
    dimensions: dict[str, str] = Field(default_factory=dict)
    coverage: tuple[str, ...] = ()


class ActionParam(BaseModel):
    model_config = wire_config()

    name: str
    value_type: ValueType
    required: bool = True


class ActionDef(_Doc):
    kind: Literal["Action"] = "Action"
    target_object: str
    parameters: tuple[ActionParam, ...]
    preconditions: tuple[str, ...] = ()
    effect: str


class AuthorizationProfileDef(_Doc):
    kind: Literal["AuthorizationProfile"] = "AuthorizationProfile"
    roles: tuple[str, ...]
    capabilities: tuple[str, ...]
    resource_types: tuple[str, ...] = ()


class PackDependency(BaseModel):
    model_config = wire_config()

    id: str
    version: str


class ContextDimension(BaseModel):
    model_config = wire_config()

    id: str
    value_type: ValueType


class DomainPackDef(_Doc):
    kind: Literal["DomainPack"] = "DomainPack"
    contract_version: Literal["v0.1"]
    namespace: str
    dependencies: tuple[PackDependency, ...] = ()
    context_dimensions: tuple[ContextDimension, ...] = ()


class MappingDef(_Doc):
    kind: Literal["Mapping"] = "Mapping"
    target: str
    source_id: str
    provider: str
    object_type: str
    perspective: str | None = None
    expected_cardinality: Cardinality
    completeness: Literal["AUTHORITATIVE", "PARTIAL"] = "PARTIAL"
    physical: dict[str, Any]


class ActionBindingDef(_Doc):
    kind: Literal["ActionBinding"] = "ActionBinding"
    action: str
    source_id: str
    provider: str
    idempotent: bool = True
    reconcilable: bool = True
    physical: dict[str, Any]


class IntegrationBindingDef(_Doc):
    kind: Literal["IntegrationBinding"] = "IntegrationBinding"
    provider: str
    source_id: str
    mappings: tuple[str, ...] = ()
    action_bindings: tuple[str, ...] = ()

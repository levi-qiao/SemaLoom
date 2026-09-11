"""Protocol-neutral semantic definitions. Physical fields stay in bindings."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from semaloom.core.expr import Expr, parse_expr

ValueType = Literal["STRING", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DATETIME"]
Cardinality = Literal["ONE", "MANY"]
Aggregation = Literal["NONE", "SUM", "MAX", "MIN"]
PolicyEnd = str | None


class _Doc(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, validate_by_name=True, frozen=True
    )

    api_version: Literal["semaloom/v0.1"] = Field(alias="apiVersion")
    kind: str
    id: str
    version: str
    label: str | None = None


class PropertyDef(_Doc):
    kind: Literal["Property"] = "Property"
    value_type: ValueType = Field(alias="valueType")
    required: bool = False


class EmbeddedProperty(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, validate_by_name=True, frozen=True
    )

    id: str
    value_type: ValueType = Field(alias="valueType")
    required: bool = False
    label: str | None = None


class ObjectTypeDef(_Doc):
    kind: Literal["ObjectType"] = "ObjectType"
    identity_keys: tuple[str, ...] = Field(alias="identityKeys")
    properties: tuple[EmbeddedProperty, ...]


class MetricDef(_Doc):
    kind: Literal["Metric"] = "Metric"
    object_type: str = Field(alias="objectType")
    value_type: Literal["DECIMAL", "INTEGER"] = Field(alias="valueType")
    unit: str
    grain: tuple[str, ...]
    aggregation: Aggregation = "NONE"
    perspective: str | None = None
    derived_from: tuple[str, ...] = Field(default=(), alias="derivedFrom")


class LinkIdentity(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, validate_by_name=True, frozen=True
    )

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
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, validate_by_name=True, frozen=True
    )

    name: str
    metric: str | None = None
    property: str | None = None
    object_type: str | None = Field(default=None, alias="objectType")
    required: bool = True


class RuleDef(_Doc):
    kind: Literal["Rule"] = "Rule"
    inputs: tuple[RuleInput, ...]
    expression: Expr
    claim: str | None = None
    output_metric: str | None = Field(default=None, alias="outputMetric")
    applicability: tuple[str, ...] = ()

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> RuleDef:
        payload = dict(data)
        payload["expression"] = parse_expr(payload["expression"])
        return cls.model_validate(payload)


class PolicyInterval(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, validate_by_name=True, frozen=True
    )

    effective_from: str = Field(alias="effectiveFrom")
    effective_to: str | None = Field(default=None, alias="effectiveTo")


class PolicyDef(_Doc):
    kind: Literal["Policy"] = "Policy"
    rule: str
    interval: PolicyInterval
    dimensions: dict[str, str] = Field(default_factory=dict)
    coverage: tuple[str, ...] = ()


class ActionParam(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, validate_by_name=True, frozen=True
    )

    name: str
    value_type: ValueType = Field(alias="valueType")
    required: bool = True


class ActionDef(_Doc):
    kind: Literal["Action"] = "Action"
    target_object: str = Field(alias="targetObject")
    parameters: tuple[ActionParam, ...]
    preconditions: tuple[str, ...] = ()
    effect: str


class AuthorizationProfileDef(_Doc):
    kind: Literal["AuthorizationProfile"] = "AuthorizationProfile"
    roles: tuple[str, ...]
    capabilities: tuple[str, ...]
    resource_types: tuple[str, ...] = Field(default=(), alias="resourceTypes")


class PackDependency(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, validate_by_name=True, frozen=True
    )

    id: str
    version: str


class DomainPackDef(_Doc):
    kind: Literal["DomainPack"] = "DomainPack"
    contract_version: Literal["v0.1"] = Field(alias="contractVersion")
    namespace: str
    dependencies: tuple[PackDependency, ...] = ()


class MappingDef(_Doc):
    kind: Literal["Mapping"] = "Mapping"
    target: str
    source_id: str = Field(alias="sourceId")
    provider: str
    object_type: str = Field(alias="objectType")
    perspective: str | None = None
    expected_cardinality: Cardinality = Field(alias="expectedCardinality")
    completeness: Literal["AUTHORITATIVE", "PARTIAL"] = "PARTIAL"
    physical: dict[str, Any]


class ActionBindingDef(_Doc):
    kind: Literal["ActionBinding"] = "ActionBinding"
    action: str
    source_id: str = Field(alias="sourceId")
    provider: str
    idempotent: bool = True
    reconcilable: bool = True
    physical: dict[str, Any]


class IntegrationBindingDef(_Doc):
    kind: Literal["IntegrationBinding"] = "IntegrationBinding"
    provider: str
    source_id: str = Field(alias="sourceId")
    mappings: tuple[str, ...] = ()
    action_bindings: tuple[str, ...] = Field(default=(), alias="actionBindings")

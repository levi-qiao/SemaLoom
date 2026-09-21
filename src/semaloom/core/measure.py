"""Kimball additivity and Gray/Chaudhuri query aggregations.

Ontology names the measurement and whether it may roll up. SemanticQuery
picks SUM/AVG/… Adapter compiles the operator; this module only decides
which operators are legal for a request grain.
"""

from __future__ import annotations

from semaloom.core.model import Additivity
from semaloom.core.semantic_query import AggregationOp, SemanticQuery, equality_value

_OPS: dict[Additivity, tuple[AggregationOp, ...]] = {
    "FULL": ("SUM", "AVG", "MIN", "MAX", "COUNT"),
    "SEMI": ("SUM", "AVG", "MIN", "MAX", "COUNT"),
    "NONE": ("COUNT", "MIN", "MAX"),
}


def aggregations_for(additivity: Additivity) -> tuple[AggregationOp, ...]:
    return _OPS.get(additivity, _OPS["FULL"])


def default_aggregation(additivity: Additivity) -> AggregationOp | None:
    if additivity in {"FULL", "SEMI"}:
        return "SUM"
    return None


def _bare(field: str) -> str:
    return field.rsplit(".", 1)[-1]


def scope_dimensions_held(
    query: SemanticQuery,
    scope_properties: tuple[str, ...],
) -> bool:
    """SEMI facts may SUM only when every declared non-additive scope is held."""
    if not scope_properties:
        return False
    grouped = {_bare(item.id) for item in query.group_by}
    return all(
        equality_value(query.filters, prop) is not None or prop in grouped
        for prop in scope_properties
    )


def aggregation_legal(
    additivity: Additivity,
    op: AggregationOp,
    query: SemanticQuery,
    scope_properties: tuple[str, ...],
) -> bool:
    if op not in aggregations_for(additivity):
        return False
    if additivity == "SEMI" and op == "SUM":
        return scope_dimensions_held(query, scope_properties)
    return True

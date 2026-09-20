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


def time_dimension_held(
    query: SemanticQuery,
    year_property: str | None,
) -> bool:
    """SEMI facts may SUM only at one snapshot, or grouped so each row is one."""
    if not year_property:
        return False
    if equality_value(query.filters, year_property) is not None:
        return True
    return any(
        _bare(item.id) == year_property or item.id == year_property for item in query.group_by
    )


def aggregation_legal(
    additivity: Additivity,
    op: AggregationOp,
    query: SemanticQuery,
    year_property: str | None,
) -> bool:
    if op not in aggregations_for(additivity):
        return False
    if additivity == "SEMI" and op == "SUM":
        return time_dimension_held(query, year_property)
    return True

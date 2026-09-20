"""Shared SemanticQuery builders for collection-analysis tests."""

from __future__ import annotations

from typing import Any

from semaloom.core.semantic_query import (
    AnalysisError,
    ComparisonExpr,
    FilterAtom,
    FilterGroup,
    MetricRef,
    SemanticQuery,
    SubjectSelector,
    TypedValue,
)
from semaloom.runtime.analysis import execute, prepare
from semaloom.runtime.auth import RequestActor

_OPS = {"mean": "AVG", "sum": "SUM", "min": "MIN", "max": "MAX", "count": "COUNT"}
_CMP = {
    "shareOfTotal": "SHARE_OF_TOTAL",
    "percentAboveMean": "RELATIVE_TO_MEAN",
    "outperforms": "STRICT_PEER",
}


def _typed(value: str | int | bool) -> TypedValue:
    if isinstance(value, bool):
        return TypedValue(value_type="BOOLEAN", value=value)
    if isinstance(value, int):
        return TypedValue(value_type="INTEGER", value=value)
    return TypedValue(value_type="STRING", value=value)


def analysis_query(
    *,
    metric: str = "finance.review.declared_profit",
    year: int = 2024,
    year_field: str = "taxYear",
    operation: str = "mean",
    filters: dict[str, str | int | bool] | None = None,
    comparison: dict[str, Any] | None = None,
    missing_policy: str = "reject",
) -> SemanticQuery:
    year_atom = FilterAtom(
        field=year_field,
        op="EQ",
        value=TypedValue(value_type="INTEGER", value=year),
    )
    extra = [
        FilterAtom(field=key, op="EQ", value=_typed(val))
        for key, val in (filters or {}).items()
        if key != year_field
    ]
    year_conflict = [
        FilterAtom(field=key, op="EQ", value=_typed(val))
        for key, val in (filters or {}).items()
        if key == year_field
    ]
    atoms = (year_atom, *year_conflict, *extra)
    filters_node: FilterAtom | FilterGroup = (
        FilterGroup(kind="AND", args=atoms) if len(atoms) > 1 else year_atom
    )
    cmp_expr = None
    if comparison is not None:
        identity = comparison.get("identity")
        subject = (
            SubjectSelector(identity=identity)
            if identity
            else SubjectSelector(filters=comparison.get("filters"))
        )
        cmp_expr = ComparisonExpr(
            op=_CMP[comparison["operation"]],
            metric=metric,
            subject=subject,
            direction=comparison.get("direction", "higher"),
        )
    return SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id=metric, aggregation=_OPS[operation]),),
        filters=filters_node,
        comparison=cmp_expr,
        missing_policy=missing_policy,  # type: ignore[arg-type]
        evidence_limit=50,
    )


def run_analysis(
    service: Any,
    actor: RequestActor,
    query: SemanticQuery | None = None,
    **kwargs: Any,
):
    semantic = query or analysis_query(**kwargs)
    prepared = prepare(service, semantic, actor)
    if prepared.status == "NEEDS_INPUT":
        slot = prepared.question.slot if prepared.question else ""
        if slot == "subject":
            raise AnalysisError("AMBIGUOUS_COMPARISON_SUBJECT")
        raise AnalysisError("NEEDS_INPUT")
    if prepared.status == "UNSUPPORTED":
        raise AnalysisError(prepared.capability or prepared.error_code or "OPERATOR_NOT_SUPPORTED")
    if prepared.status == "SOURCE_ERROR":
        raise AnalysisError(prepared.error_code or "PROVIDER_ERROR")
    if prepared.plan is None:
        raise AnalysisError("PROVIDER_ERROR")
    return execute(service, prepared.plan, actor)

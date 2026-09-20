"""Kimball additivity is ontology config; query aggregations stay on SemanticQuery."""

from __future__ import annotations

from pathlib import Path

from semaloom.core.measure import aggregation_legal, aggregations_for, default_aggregation
from semaloom.core.semantic_query import (
    FilterAtom,
    GroupByItem,
    MetricRef,
    SemanticQuery,
    TypedValue,
)
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.discovery import SemanticDiscovery
from semaloom.sdk import compile_paths

ROOT = Path(__file__).resolve().parents[1]


def _query(
    *,
    aggregation: str | None = "SUM",
    year: int | None = 2024,
    years: tuple[int, ...] | None = None,
    group_year: bool = False,
) -> SemanticQuery:
    filters = None
    if years is not None:
        filters = FilterAtom(
            field="stockYear",
            op="IN",
            value=TypedValue(value_type="INTEGER", value=years),
        )
    elif year is not None:
        filters = FilterAtom(
            field="stockYear",
            op="EQ",
            value=TypedValue(value_type="INTEGER", value=year),
        )
    return SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="warehouse.onHandQty", aggregation=aggregation),),
        filters=filters,
        group_by=(GroupByItem(id="stockYear"),) if group_year else (),
    )


def test_operator_sets_follow_kimball_and_gray() -> None:
    assert aggregations_for("FULL") == ("SUM", "AVG", "MIN", "MAX", "COUNT")
    assert aggregations_for("SEMI") == ("SUM", "AVG", "MIN", "MAX", "COUNT")
    assert aggregations_for("NONE") == ("COUNT", "MIN", "MAX")
    assert default_aggregation("FULL") == "SUM"
    assert default_aggregation("SEMI") == "SUM"
    assert default_aggregation("NONE") is None


def test_semi_sum_holds_only_a_single_year_or_year_group() -> None:
    assert aggregation_legal("SEMI", "SUM", _query(year=2024), "stockYear")
    assert aggregation_legal("SEMI", "SUM", _query(year=None, group_year=True), "stockYear")
    assert not aggregation_legal("SEMI", "SUM", _query(year=None), "stockYear")
    assert not aggregation_legal("SEMI", "SUM", _query(year=None, years=(2024, 2025)), "stockYear")
    assert aggregation_legal("SEMI", "AVG", _query(year=None), "stockYear")
    assert not aggregation_legal("NONE", "SUM", _query(year=2024), "stockYear")
    assert aggregation_legal("FULL", "SUM", _query(year=None), "stockYear")


def test_warehouse_on_hand_inherits_semi_from_the_measurement_slot() -> None:
    result = compile_paths([ROOT / "examples/warehouse"])
    assert result.bundle is not None
    metric = next(item for item in result.bundle.metrics if item.id == "warehouse.onHandQty")
    assert metric.additivity == "SEMI"
    assets = compile_paths([ROOT / "examples/financial-review"])
    assert assets.bundle is not None
    equity = next(item for item in assets.bundle.metrics if item.id == "finance.review.equity")
    profit = next(
        item for item in assets.bundle.metrics if item.id == "finance.review.declared_profit"
    )
    assert equity.additivity == "SEMI"
    assert profit.additivity == "FULL"
    ratio = next(item for item in assets.bundle.metrics if item.id == "finance.review.debtRatio")
    assert ratio.additivity == "NONE"
    assert aggregations_for(ratio.additivity) == ("COUNT", "MIN", "MAX")
    described = SemanticDiscovery(result.bundle).describe(
        "warehouse.onHandQty",
        RequestActor(tenant="tenant-a", subject="test", roles=("analyst",)),
    )
    assert described["analysisCapabilities"]["additivity"] == "SEMI"
    assert described["analysisCapabilities"]["aggregations"] == [
        "SUM",
        "AVG",
        "MIN",
        "MAX",
        "COUNT",
    ]

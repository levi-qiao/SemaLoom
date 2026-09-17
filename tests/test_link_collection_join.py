"""Declared ONE same-source Link collection JOIN on the shipped prepare/execute path."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from semaloom.core.semantic_query import (
    FilterAtom,
    FilterGroup,
    GroupByItem,
    MetricRef,
    SemanticQuery,
    TypedValue,
)
from semaloom.runtime.analysis import AnalysisError, execute, prepare
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.discovery import SemanticDiscovery
from tests.test_business_analysis import ACTOR, financial_query  # noqa: F401
from tests.test_chat_choices import _load_declaration


@pytest.fixture
def population_query(financial_query: Any) -> Any:  # noqa: F811
    return financial_query


def _load_companies(engine: Any, *, include_c3: bool = False) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sample_taxpayer (
                  tenant_id TEXT, id TEXT, name TEXT
                )
                """
            )
        )
        conn.execute(text("DELETE FROM sample_taxpayer"))
        rows = [
            ("tenant-a", "C1", "示例甲"),
            ("tenant-a", "C2", "示例乙"),
        ]
        if include_c3:
            rows.append(("tenant-a", "C3", "示例丙"))
        conn.execute(
            text("INSERT INTO sample_taxpayer (tenant_id, id, name) VALUES (:t, :i, :n)"),
            [{"t": tenant, "i": ident, "n": name} for tenant, ident, name in rows],
        )


def _query(**changes: Any) -> SemanticQuery:
    payload: dict[str, Any] = {
        "apiVersion": "semaloom/v0.1",
        "metrics": [{"id": "finance.declaredRevenue", "aggregation": "SUM"}],
        "filters": {
            "kind": "PRED",
            "field": "taxYear",
            "op": "EQ",
            "value": {"valueType": "INTEGER", "value": 2024},
        },
        "groupBy": [{"id": "finance.Company.name"}],
        "missingPolicy": "reject",
        "evidenceLimit": 50,
    }
    payload.update(changes)
    return SemanticQuery.model_validate(payload)


def test_one_link_join_groups_by_company_name(population_query: Any) -> None:
    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
    _load_companies(engine)
    with engine.connect() as conn:
        oracle = {
            (row.name, str(row.total))
            for row in conn.execute(
                text(
                    """
                    SELECT t.name AS name, SUM(d.revenue) AS total
                    FROM sample_declaration d
                    LEFT JOIN sample_taxpayer t
                      ON t.tenant_id = d.tenant_id AND t.id = d.taxpayer_id
                    WHERE d.tenant_id = 'tenant-a' AND d.tax_year = 2024
                    GROUP BY t.name
                    """
                )
            )
        }
    prepared = prepare(population_query, _query(), ACTOR)
    assert prepared.status == "READY"
    assert prepared.plan is not None
    result = execute(population_query, prepared.plan, ACTOR)
    got = {(row["grain"].get("name"), row["value"]) for row in result.values}
    assert got == oracle
    assert any(name is None for name, _ in got)


def test_one_link_join_filter_by_company_name(population_query: Any) -> None:
    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
    _load_companies(engine, include_c3=True)
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="finance.declaredRevenue", aggregation="SUM"),),
        filters=FilterGroup(
            kind="AND",
            args=(
                FilterAtom(
                    field="taxYear",
                    op="EQ",
                    value=TypedValue(value_type="INTEGER", value=2024),
                ),
                FilterAtom(
                    field="finance.Company.name",
                    op="EQ",
                    value=TypedValue(value_type="STRING", value="示例甲"),
                ),
            ),
        ),
        missing_policy="reject",
    )
    prepared = prepare(population_query, query, ACTOR)
    assert prepared.status == "READY" and prepared.plan is not None
    result = execute(population_query, prepared.plan, ACTOR)
    assert result.values[0]["value"] == str(Decimal("100.01"))


def test_unrelated_object_field_is_rejected(population_query: Any) -> None:
    query = _query(groupBy=[{"id": "finance.AuditFactor.factorRef"}])
    with pytest.raises(AnalysisError, match="INVALID_PROPERTIES"):
        prepare(population_query, query, ACTOR)


def test_two_hop_company_from_return_line_is_rejected(population_query: Any) -> None:
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="finance.returnLineAmount", aggregation="SUM"),),
        group_by=(GroupByItem(id="finance.Company.name"),),
    )
    with pytest.raises(AnalysisError, match="INVALID_PROPERTIES"):
        prepare(population_query, query, ACTOR)


def test_discovery_marks_one_same_source_link_join(population_query: Any) -> None:
    service = SemanticDiscovery(population_query.bundle)
    actor = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
    link = service.describe("finance.returnCompany", actor)
    assert link["analysisCapabilities"]["collectionJoin"] is True
    metric = service.describe("finance.declaredRevenue", actor)
    assert metric["analysisCapabilities"]["collectionJoin"] is True
    assert "physical" not in link


def test_same_source_collection_join_rejects_composite_link(population_query: Any) -> None:
    """Prepare path: composite Links fail with LINK_ANALYSIS_UNSUPPORTED, not multi-ON SQL."""
    from semaloom.runtime.query import QueryService

    link = next(
        item for item in population_query.bundle.links if item.id == "finance.returnCompany"
    )
    pair = link.identity[0]
    composite = link.model_copy(update={"identity": (pair, pair)})
    links = tuple(
        composite if item.id == "finance.returnCompany" else item
        for item in population_query.bundle.links
    )
    service = QueryService(
        population_query.bundle.model_copy(update={"links": links}),
        population_query.provider,
    )
    discovery = SemanticDiscovery(service.bundle).describe("finance.returnCompany", ACTOR)
    assert discovery["analysisCapabilities"]["collectionJoin"] is False
    prepared = prepare(service, _query(), ACTOR)
    assert prepared.status == "UNSUPPORTED"
    assert prepared.capability == "LINK_ANALYSIS_UNSUPPORTED"
    assert prepared.error_message == "LINK_ANALYSIS_UNSUPPORTED"

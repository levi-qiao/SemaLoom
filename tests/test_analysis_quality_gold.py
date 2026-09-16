"""Independent gold cases for population analysis.

Expectations come from SQL/Decimal, not the SUT.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

import pytest
from sqlalchemy import text

from semaloom.core.results import PopulationRequest
from semaloom.runtime.population import analyze_population
from tests.test_business_analysis import ACTOR, financial_query  # noqa: F401


@pytest.fixture
def gold_query(financial_query: Any) -> Any:  # noqa: F811
    engine = financial_query.provider._engines["sample_pg"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET company_id=id"))
        conn.execute(
            text(
                "INSERT INTO sample_financial_review ("
                "tenant_id,id,company_id,company_name,tax_year,period_start,period_to,"
                "unique_pair,declared_profit,audit_profit,net_profit,tax_expense,assets,"
                "liabilities,equity) VALUES "
                "('tenant-a','Y25A','Y25A','二年样本',2025,'2025-01-01','2026-01-01',"
                "true,50.25,50.00,40,10,500,200,300)"
            )
        )
    return financial_query


def req(**changes: Any) -> PopulationRequest:
    return PopulationRequest.model_validate(
        {"metric": "finance.review.declared_profit", "year": 2024, **changes}
    )


def sql_agg(query: Any, op: str, year: int, column: str = "declared_profit") -> Decimal | None:
    with query.provider._engines["sample_pg"].connect() as conn:
        value = conn.execute(
            text(
                f"SELECT {op}({column}) FROM sample_financial_review "
                "WHERE tenant_id='tenant-a' AND tax_year=:year"
            ),
            {"year": year},
        ).scalar_one()
    return None if value is None else Decimal(value)


def test_cross_tenant_same_key_is_excluded_from_mean(gold_query: Any) -> None:
    expected = sql_agg(gold_query, "avg", 2024)
    result = analyze_population(gold_query, req(), ACTOR)
    assert expected is not None
    assert Decimal(result["value"]) == expected
    assert result["populationCount"] == 3
    identities = {row["identity"]["caseId"] for row in result["members"]}
    assert identities == {"C1", "C2", "C3"}
    with gold_query.provider._engines["sample_pg"].connect() as conn:
        foreign = conn.execute(
            text(
                "SELECT declared_profit FROM sample_financial_review "
                "WHERE tenant_id='tenant-b' AND id='C1'"
            )
        ).scalar_one()
    assert Decimal(foreign) == Decimal("999")
    assert Decimal(result["value"]) != Decimal(foreign)


def test_mixed_years_do_not_blend(gold_query: Any) -> None:
    y2024 = analyze_population(gold_query, req(year=2024), ACTOR)
    y2025 = analyze_population(gold_query, req(year=2025), ACTOR)
    assert Decimal(y2024["value"]) == sql_agg(gold_query, "avg", 2024)
    assert Decimal(y2025["value"]) == sql_agg(gold_query, "avg", 2025)
    assert y2024["populationCount"] == 3 and y2025["populationCount"] == 1
    assert {row["identity"]["caseId"] for row in y2025["members"]} == {"Y25A"}
    assert y2024["year"] == 2024 and y2025["year"] == 2025


def test_single_member_share_is_one_hundred(gold_query: Any) -> None:
    result = analyze_population(
        gold_query,
        req(
            year=2025,
            comparison={"identity": {"caseId": "Y25A"}, "operation": "shareOfTotal"},
        ),
        ACTOR,
    )
    comparison = result["comparison"]
    assert Decimal(comparison["numerator"]) == Decimal("50.25")
    assert Decimal(comparison["denominator"]) == Decimal("50.25")
    assert Decimal(comparison["value"]) == Decimal("100")
    assert result["populationCount"] == result["observedCount"] == 1


def test_empty_and_all_missing_are_not_zero(gold_query: Any) -> None:
    empty = analyze_population(gold_query, req(year=2023), ACTOR)
    assert empty["value"] is None and empty["reason"] == "EMPTY_POPULATION"
    assert empty["status"] == "UNAVAILABLE"
    with gold_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET audit_profit=NULL"))
    missing = analyze_population(gold_query, req(metric="finance.review.audit_profit"), ACTOR)
    assert missing["value"] is None
    assert missing["reason"] == "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION"
    assert missing["missingCount"] == missing["populationCount"] == 3
    excluded = analyze_population(
        gold_query,
        req(metric="finance.review.audit_profit", missingPolicy="exclude"),
        ACTOR,
    )
    assert excluded["value"] is None
    assert excluded["reason"] == "NO_OBSERVED_VALUES"
    assert excluded["observedCount"] == 0


def test_declared_versus_audit_perspective(gold_query: Any) -> None:
    declared = analyze_population(gold_query, req(), ACTOR)
    audit = analyze_population(
        gold_query, req(metric="finance.review.audit_profit", missingPolicy="exclude"), ACTOR
    )
    assert Decimal(declared["value"]) == sql_agg(gold_query, "avg", 2024)
    assert Decimal(audit["value"]) == sql_agg(gold_query, "avg", 2024, "audit_profit")
    assert declared["metric"] != audit["metric"]
    assert audit["missingCount"] == 1 and audit["observedCount"] == 2


def test_derived_profit_difference_matches_hand_decimal(gold_query: Any) -> None:
    with localcontext() as ctx:
        ctx.prec = 28
        expected = (Decimal("0.01") + Decimal("0.02")) / 2
    result = analyze_population(
        gold_query,
        req(metric="finance.review.profitDifference", missingPolicy="exclude"),
        ACTOR,
    )
    assert Decimal(result["value"]) == expected
    assert result["unit"] == "CNY"
    assert result["observedCount"] == 2 and result["missingCount"] == 1


def test_fifty_members_succeed_fifty_one_refuses_truncated_total(gold_query: Any) -> None:
    with gold_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sample_financial_review ("
                "tenant_id,id,company_id,tax_year,period_start,period_to,declared_profit) "
                "SELECT 'tenant-a','E'||i,'E'||i,2024,'2024-01-01','2025-01-01',1 "
                "FROM generate_series(1,47) i"
            )
        )
    ok = analyze_population(gold_query, req(operation="count"), ACTOR)
    assert Decimal(ok["value"]) == Decimal("50")
    assert ok["populationCount"] == 50
    with gold_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sample_financial_review ("
                "tenant_id,id,company_id,tax_year,period_start,period_to,declared_profit) "
                "VALUES ('tenant-a','E48','E48',2024,'2024-01-01','2025-01-01',1)"
            )
        )
    larger = analyze_population(gold_query, req(operation="count"), ACTOR)
    assert Decimal(larger["value"]) == Decimal("51")
    assert larger["populationCount"] == 51
    assert len(larger["members"]) == 50


def test_source_error_is_not_a_successful_number(gold_query: Any) -> None:
    with gold_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(text("ALTER TABLE sample_financial_review DROP COLUMN declared_profit"))
    with pytest.raises(ValueError):
        analyze_population(gold_query, req(), ACTOR)


def test_http_analyze_matches_independent_sql(gold_query: Any) -> None:
    from fastapi.testclient import TestClient

    from semaloom.app.bootstrap import build_services
    from semaloom.app.factory import create_app
    from semaloom.app.http import router

    expected = sql_agg(gold_query, "avg", 2024)
    services = build_services(load_data=True)
    services.query_active = lambda tenant: gold_query  # type: ignore[method-assign]
    app = create_app(load_services=False)
    app.state.services = services
    app.include_router(router)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v0.1/analyze",
                headers={"Authorization": "Bearer tenant-a-analyst"},
                json={"metric": "finance.review.declared_profit", "year": 2024},
            )
        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["value"]) == expected
        assert body["complete"] is True
        assert body["sourceActivities"]
    finally:
        services.close()

"""Independent gold cases for collection analysis.

Expectations come from SQL/Decimal, not the SUT.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

import pytest
from sqlalchemy import text

from semaloom.runtime.query import QueryService
from tests.analysis_support import analysis_query, run_analysis
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
    result = run_analysis(gold_query, ACTOR)
    assert expected is not None
    assert Decimal(result.values[0]["value"]) == expected
    assert result.scope["populationCount"] == 3
    identities = {row[0] for row in result.evidence.rows}
    assert identities == {"C1", "C2", "C3"}
    with gold_query.provider._engines["sample_pg"].connect() as conn:
        foreign = conn.execute(
            text(
                "SELECT declared_profit FROM sample_financial_review "
                "WHERE tenant_id='tenant-b' AND id='C1'"
            )
        ).scalar_one()
    assert Decimal(foreign) == Decimal("999")
    assert Decimal(result.values[0]["value"]) != Decimal(foreign)


def test_mixed_years_do_not_blend(gold_query: Any) -> None:
    y2024 = run_analysis(gold_query, ACTOR, year=2024)
    y2025 = run_analysis(gold_query, ACTOR, year=2025)
    assert Decimal(y2024.values[0]["value"]) == sql_agg(gold_query, "avg", 2024)
    assert Decimal(y2025.values[0]["value"]) == sql_agg(gold_query, "avg", 2025)
    assert y2024.scope["populationCount"] == 3 and y2025.scope["populationCount"] == 1
    assert {row[0] for row in y2025.evidence.rows} == {"Y25A"}


def test_single_member_share_is_one_hundred(gold_query: Any) -> None:
    result = run_analysis(
        gold_query,
        ACTOR,
        year=2025,
        comparison={"identity": {"caseId": "Y25A"}, "operation": "shareOfTotal"},
    )
    calculation = result.scope["calculation"]
    assert Decimal(calculation["numerator"]) == Decimal("50.25")
    assert Decimal(calculation["denominator"]) == Decimal("50.25")
    assert Decimal(calculation["value"]) == Decimal("1")
    assert result.scope["populationCount"] == result.scope["observedCount"] == 1


def test_empty_and_all_missing_are_not_zero(gold_query: Any) -> None:
    empty = run_analysis(gold_query, ACTOR, year=2023)
    assert not empty.values and empty.scope["reason"] == "EMPTY_POPULATION"
    with gold_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET audit_profit=NULL"))
    missing = run_analysis(gold_query, ACTOR, metric="finance.review.audit_profit")
    assert missing.values == ()
    assert missing.scope["reason"] == "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION"
    assert missing.scope["missingCount"] == missing.scope["populationCount"] == 3
    excluded = run_analysis(
        gold_query,
        ACTOR,
        metric="finance.review.audit_profit",
        missing_policy="exclude",
    )
    assert excluded.values == ()
    assert excluded.scope["reason"] == "NO_OBSERVED_VALUES"
    assert excluded.scope["observedCount"] == 0


def test_declared_versus_audit_perspective(gold_query: Any) -> None:
    declared = run_analysis(gold_query, ACTOR)
    audit = run_analysis(
        gold_query, ACTOR, metric="finance.review.audit_profit", missing_policy="exclude"
    )
    assert Decimal(declared.values[0]["value"]) == sql_agg(gold_query, "avg", 2024)
    assert Decimal(audit.values[0]["value"]) == sql_agg(gold_query, "avg", 2024, "audit_profit")
    assert declared.values[0]["metric"] != audit.values[0]["metric"]
    assert audit.scope["missingCount"] == 1 and audit.scope["observedCount"] == 2


def test_derived_profit_difference_matches_hand_decimal(gold_query: Any) -> None:
    with localcontext() as ctx:
        ctx.prec = 28
        expected = (Decimal("0.01") + Decimal("0.02")) / 2
    result = run_analysis(
        gold_query,
        ACTOR,
        metric="finance.review.profitDifference",
        missing_policy="exclude",
    )
    assert Decimal(result.values[0]["value"]) == expected
    assert result.values[0]["unit"] == "CNY"
    assert result.scope["observedCount"] == 2 and result.scope["missingCount"] == 1


def test_configured_round_expression_is_lowered_for_collection_analysis(
    gold_query: Any,
) -> None:
    rules = []
    for rule in gold_query.bundle.rules:
        if rule.output_metric != "finance.review.profitDifference":
            rules.append(rule)
            continue
        rules.append(
            rule.model_copy(
                update={
                    "expression": {
                        "op": "round",
                        "value": rule.expression,
                        "places": 2,
                        "mode": "ROUND_HALF_UP",
                    }
                }
            )
        )
    service = QueryService(
        gold_query.bundle.model_copy(update={"rules": tuple(rules)}), gold_query.provider
    )
    result = run_analysis(
        service,
        ACTOR,
        metric="finance.review.profitDifference",
        missing_policy="exclude",
    )
    assert Decimal(result.values[0]["value"]) == Decimal("0.015")


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
    ok = run_analysis(gold_query, ACTOR, operation="count")
    assert Decimal(ok.values[0]["value"]) == Decimal("50")
    assert ok.scope["populationCount"] == 50
    with gold_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sample_financial_review ("
                "tenant_id,id,company_id,tax_year,period_start,period_to,declared_profit) "
                "VALUES ('tenant-a','E48','E48',2024,'2024-01-01','2025-01-01',1)"
            )
        )
    larger = run_analysis(gold_query, ACTOR, operation="count")
    assert Decimal(larger.values[0]["value"]) == Decimal("51")
    assert larger.scope["populationCount"] == 51
    assert len(larger.evidence.rows) == 50


def test_source_error_is_not_a_successful_number(gold_query: Any) -> None:
    with gold_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(text("ALTER TABLE sample_financial_review DROP COLUMN declared_profit"))
    with pytest.raises(ValueError):
        run_analysis(gold_query, ACTOR)


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
            headers = {"Authorization": "Bearer tenant-a-analyst"}
            prepared = client.post(
                "/v0.1/semantic/prepare",
                headers=headers,
                json=analysis_query().model_dump(by_alias=True),
            )
            assert prepared.status_code == 200
            response = client.post(
                "/v0.1/semantic/execute",
                headers=headers,
                json=prepared.json()["plan"],
            )
        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["values"][0]["value"]) == expected
        assert body["scope"]["complete"] is True
        assert body["sourceActivities"]
    finally:
        services.close()

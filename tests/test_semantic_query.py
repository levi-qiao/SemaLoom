"""Shipped prepare/execute on isolated PostgreSQL. Independent SQL/Decimal oracle."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from semaloom.adapters.postgres import PostgresReadProvider
from semaloom.app.factory import create_app
from semaloom.app.http import router
from semaloom.core.semantic_query import (
    FilterAtom,
    GroupByItem,
    MetricRef,
    SemanticQuery,
    TypedValue,
)
from semaloom.runtime.analysis import AnalysisError, execute, prepare
from semaloom.runtime.fixtures import engines
from semaloom.runtime.query import QueryService
from semaloom.sdk import compile_paths
from tests.test_business_analysis import ACTOR, financial_query  # noqa: F401


@pytest.fixture
def population_query(financial_query: Any) -> Any:  # noqa: F811
    engine = financial_query.provider._engines["sample_pg"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET company_id=id"))
    return financial_query


ROOT = Path(__file__).resolve().parents[1]


def _query(**changes: Any) -> SemanticQuery:
    payload = {
        "apiVersion": "semaloom/v0.1",
        "metrics": [{"id": "finance.review.declared_profit", "aggregation": "SUM"}],
        "filters": {
            "kind": "PRED",
            "field": "taxYear",
            "op": "EQ",
            "value": {"valueType": "INTEGER", "value": 2024},
        },
        "missingPolicy": "reject",
        "evidenceLimit": 50,
    }
    payload.update(changes)
    return SemanticQuery.model_validate(payload)


def test_prepare_ready_and_needs_input(population_query: Any) -> None:
    ready = prepare(population_query, _query(), ACTOR)
    assert ready.status == "READY"
    assert ready.plan is not None
    empty = prepare(
        population_query,
        SemanticQuery.model_validate({"apiVersion": "semaloom/v0.1", "metrics": []}),
        ACTOR,
    )
    assert empty.status == "NEEDS_INPUT"
    assert empty.question is not None
    assert empty.question.slot == "metric"
    kinds = {item.choice.kind for item in empty.question.options}
    assert kinds >= {"ABORT", "OTHER"}
    no_year = prepare(
        population_query,
        SemanticQuery.model_validate(
            {
                "apiVersion": "semaloom/v0.1",
                "metrics": [{"id": "finance.review.declared_profit", "aggregation": "SUM"}],
            }
        ),
        ACTOR,
    )
    assert no_year.status == "NEEDS_INPUT"
    assert no_year.question is not None
    assert no_year.question.slot == "year"


def test_sum_matches_independent_sql_oracle(population_query: Any) -> None:
    prepared = prepare(population_query, _query(), ACTOR)
    assert prepared.plan is not None
    result = execute(population_query, prepared.plan, ACTOR)
    with population_query.provider._engines["sample_pg"].connect() as conn:
        expected = conn.execute(
            text(
                "SELECT SUM(declared_profit) FROM sample_financial_review "
                "WHERE tenant_id='tenant-a' AND tax_year=2024"
            )
        ).scalar_one()
    assert result.values[0]["value"] is not None
    assert Decimal(result.values[0]["value"]) == Decimal(expected)
    assert isinstance(Decimal(result.values[0]["value"]), Decimal)
    assert result.scope["populationCount"] == 3


def test_group_and_or_topn(population_query: Any) -> None:
    query = _query(
        groupBy=[{"id": "companyId"}],
        filters={
            "kind": "AND",
            "args": [
                {
                    "kind": "PRED",
                    "field": "taxYear",
                    "op": "EQ",
                    "value": {"valueType": "INTEGER", "value": 2024},
                },
                {
                    "kind": "OR",
                    "args": [
                        {
                            "kind": "PRED",
                            "field": "companyId",
                            "op": "EQ",
                            "value": {"valueType": "STRING", "value": "C1"},
                        },
                        {
                            "kind": "PRED",
                            "field": "companyId",
                            "op": "EQ",
                            "value": {"valueType": "STRING", "value": "C2"},
                        },
                    ],
                },
            ],
        },
        orderBy=[{"field": "value", "direction": "DESC"}],
        limit=1,
    )
    prepared = prepare(population_query, query, ACTOR)
    assert prepared.plan is not None
    result = execute(population_query, prepared.plan, ACTOR)
    assert len(result.values) == 1
    assert result.values[0]["grain"]["companyId"] in {"C1", "C2"}
    assert result.values[0]["labels"]["companyId"] == "示例企业"


def test_share_does_not_shrink_denominator(population_query: Any) -> None:
    query = _query(
        comparison={
            "op": "SHARE_OF_TOTAL",
            "metric": "finance.review.declared_profit",
            "subject": {"identity": {"caseId": "C2"}},
        }
    )
    prepared = prepare(population_query, query, ACTOR)
    assert prepared.plan is not None
    result = execute(population_query, prepared.plan, ACTOR)
    comparison = result.scope["comparison"]
    assert Decimal(comparison["numerator"]) == Decimal("100.02")
    assert Decimal(comparison["denominator"]) == Decimal("300.03")
    assert Decimal(comparison["value"]) == Decimal("100.02") / Decimal("300.03") * 100


def test_thousands_of_rows_pushdown_caps_evidence_only(population_query: Any) -> None:
    query = population_query
    with query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sample_financial_review "
                "(tenant_id,id,company_id,tax_year,declared_profit) "
                "SELECT 'tenant-a','bulk'||i,'u'||i,2024,1.0000 FROM generate_series(1,3000) i"
            )
        )
    prepared = prepare(query, _query(), ACTOR)
    assert prepared.plan is not None
    result = execute(query, prepared.plan, ACTOR)
    with query.provider._engines["sample_pg"].connect() as conn:
        expected = conn.execute(
            text(
                "SELECT SUM(declared_profit) FROM sample_financial_review "
                "WHERE tenant_id='tenant-a' AND tax_year=2024"
            )
        ).scalar_one()
    assert Decimal(result.values[0]["value"]) == Decimal(expected)
    assert result.scope["populationCount"] == 3003
    assert len(result.evidence.rows) == 50
    assert result.evidence.truncated is True


def test_source_error_is_not_a_choice(population_query: Any) -> None:
    with population_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(text("DROP TABLE sample_financial_review"))
    prepared = prepare(population_query, _query(), ACTOR)
    if prepared.status == "READY":
        assert prepared.plan is not None
        with pytest.raises(AnalysisError, match="PROVIDER_UNAVAILABLE"):
            execute(population_query, prepared.plan, ACTOR)
    else:
        assert prepared.status == "SOURCE_ERROR"
        assert prepared.retryable is True


def test_unsupported_cross_table_metrics(population_query: Any) -> None:
    query = SemanticQuery.model_validate(
        {
            "apiVersion": "semaloom/v0.1",
            "metrics": [
                {"id": "finance.review.declared_profit", "aggregation": "SUM"},
                {"id": "finance.declaredRevenue", "aggregation": "SUM"},
            ],
            "filters": {
                "kind": "PRED",
                "field": "taxYear",
                "op": "EQ",
                "value": {"valueType": "INTEGER", "value": 2024},
            },
        }
    )
    result = prepare(population_query, query, ACTOR)
    assert result.status in {"UNSUPPORTED", "READY"}
    if result.status == "READY":
        assert result.plan is not None
        with pytest.raises(AnalysisError):
            execute(population_query, result.plan, ACTOR)
    else:
        assert result.capability


def test_procurement_config_only_second_domain() -> None:
    bundle = compile_paths([ROOT / "examples/procurement"]).bundle
    assert bundle is not None
    engine = engines()["orders_pg"]
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS analysis_q1"))
        conn.execute(text("SET search_path TO analysis_q1"))
        conn.execute(
            text(
                """CREATE TABLE proc_order (
                tenant_id TEXT, order_id TEXT, organization_id TEXT, supplier_id TEXT,
                status TEXT, amount NUMERIC, quantity NUMERIC
            )"""
            )
        )
        conn.execute(
            text(
                """INSERT INTO proc_order VALUES
                ('tenant-a','PO1','O1','S1','OPEN',100.0100,1),
                ('tenant-a','PO2','O1','S2','OPEN',50.0000,1),
                ('tenant-a','PO3','O2','S1','CLOSED',25.0000,1),
                ('tenant-b','POX','OX','SX','OPEN',9999,1)"""
            )
        )
        conn.commit()
        read_engine = create_engine(
            engine.url, connect_args={"options": "-csearch_path=analysis_q1"}
        )
        provider = PostgresReadProvider({"orders_pg": read_engine})
        try:
            service = QueryService(bundle, provider)
            query = SemanticQuery(
                api_version="semaloom/v0.1",
                metrics=(MetricRef(id="procurement.orderAmount", aggregation="SUM"),),
                group_by=(GroupByItem(id="organizationId"),),
                filters=FilterAtom(
                    field="status",
                    op="EQ",
                    value=TypedValue(value_type="STRING", value="OPEN"),
                ),
            )
            prepared = prepare(service, query, ACTOR)
            assert prepared.status == "READY"
            assert prepared.plan is not None
            result = execute(service, prepared.plan, ACTOR)
            by_org = {
                row["grain"]["organizationId"]: Decimal(row["value"]) for row in result.values
            }
            assert by_org["O1"] == Decimal("150.0100")
            assert "O2" not in by_org
            with read_engine.connect() as check:
                expected = check.execute(
                    text(
                        "SELECT SUM(amount) FROM proc_order "
                        "WHERE tenant_id='tenant-a' AND status='OPEN' AND organization_id='O1'"
                    )
                ).scalar_one()
            assert by_org["O1"] == Decimal(expected)
        finally:
            read_engine.dispose()
            conn.rollback()
            conn.execute(text("SET search_path TO public"))
            conn.execute(text("DROP SCHEMA analysis_q1 CASCADE"))
            conn.commit()


def test_http_prepare_execute_matches_oracle(population_query: Any) -> None:
    app = create_app(load_services=False)
    app.include_router(router)

    class Services:
        def query_active(self, tenant: str | None = None) -> Any:
            return population_query

    app.state.services = Services()
    client = TestClient(app)
    headers = {"Authorization": "Bearer tenant-a-analyst"}
    prepared = client.post(
        "/v0.1/semantic/prepare",
        headers=headers,
        json=_query().model_dump(mode="json", by_alias=True),
    )
    assert prepared.status_code == 200
    body = prepared.json()
    assert body["status"] == "READY"
    executed = client.post("/v0.1/semantic/execute", headers=headers, json=body["plan"])
    assert executed.status_code == 200
    payload = executed.json()
    with population_query.provider._engines["sample_pg"].connect() as conn:
        expected = conn.execute(
            text(
                "SELECT SUM(declared_profit) FROM sample_financial_review "
                "WHERE tenant_id='tenant-a' AND tax_year=2024"
            )
        ).scalar_one()
    assert Decimal(payload["values"][0]["value"]) == Decimal(expected)

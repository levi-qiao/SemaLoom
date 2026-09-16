"""Principal accuracy regression checks, using invented values and isolated test storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from semaloom.adapters.postgres import PostgresReadProvider
from semaloom.compiler import compile_documents, compile_paths
from semaloom.compiler.yaml_load import load_yaml_documents
from semaloom.core.expr import parse_expr
from semaloom.core.model import RuleDef
from semaloom.core.results import (
    MetricSelect,
    ObjectSearchRequest,
    ObjectSelect,
    Observation,
    QueryContext,
    QueryRequest,
)
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.eval import evaluate_claim_with_evidence, evaluate_rule
from semaloom.runtime.fixtures import engines
from semaloom.runtime.query import QueryService

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples/financial-review"
ACTOR = RequestActor(tenant="tenant-a", subject="test", roles=("analyst",))
PERIOD = QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"})


@pytest.fixture
def financial_query() -> Any:
    bundle = compile_paths([PACK]).bundle
    assert bundle is not None
    engine = engines()["tax_pg"]
    # A temporary schema on a test-owned connection keeps every existing fixture intact.
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA analysis_regression"))
        conn.execute(text("SET search_path TO analysis_regression"))
        conn.execute(
            text("""CREATE TABLE sample_financial_review (
            tenant_id TEXT, id TEXT, company_name TEXT, tax_year INTEGER,
            period_start DATE, period_to DATE, unique_pair BOOLEAN,
            declared_profit NUMERIC, audit_profit NUMERIC, net_profit NUMERIC,
            tax_expense NUMERIC, assets NUMERIC, liabilities NUMERIC, equity NUMERIC
        )""")
        )
        conn.execute(
            text("""INSERT INTO sample_financial_review VALUES
            ('tenant-a','C1','示例企业',2024,'2024-01-01','2025-01-01',true,100.01,100,80,20,1000,600,400),
            ('tenant-a','C2','示例企业',2024,'2024-01-01','2025-01-01',false,100.02,100,79,20,1002,600,400),
            ('tenant-a','C3','缺失样本',2024,'2024-01-01','2025-01-01',true,100,NULL,80,20,NULL,600,400),
            ('tenant-b','C1','别的租户',2024,'2024-01-01','2025-01-01',true,999,999,999,0,999,0,999)
        """)
        )
        for column in [
            "company_id",
            "report_id",
            "return_id",
            "pairing_policy",
            "unit_basis",
            "source_review_status",
            "audit_profit_status",
            "net_profit_status",
            "tax_expense_status",
            "assets_status",
            "liabilities_status",
            "equity_status",
        ]:
            conn.execute(text(f"ALTER TABLE sample_financial_review ADD COLUMN {column} TEXT"))
        conn.commit()
        # Each real provider read uses this test schema, not shared fixture tables.
        read_engine = create_engine(
            engine.url, connect_args={"options": "-csearch_path=analysis_regression"}
        )
        provider = PostgresReadProvider({"sample_pg": read_engine})
        try:
            yield QueryService(bundle, provider)
        finally:
            read_engine.dispose()
            conn.rollback()
            conn.execute(text("SET search_path TO public"))
            conn.execute(text("DROP SCHEMA analysis_regression CASCADE"))
            conn.commit()


def request(
    case: str, metric: str = "profitDifference", period: QueryContext = PERIOD
) -> QueryRequest:
    return QueryRequest(
        api_version="semaloom/v0.1",
        select=(MetricSelect(metric="finance.review." + metric, bindings={"caseId": case}),),
        context=period,
    )


@pytest.mark.parametrize(
    ("case", "expected", "profit", "balance", "net"),
    [
        ("C1", "0.01", "TRUE", "TRUE", "TRUE"),
        ("C2", "0.02", "FALSE", "FALSE", "TRUE"),
        ("C3", None, "UNKNOWN", "UNKNOWN", "UNKNOWN"),
    ],
)
def test_financial_rules_and_derived_metric(
    financial_query: QueryService,
    case: str,
    expected: str | None,
    profit: str,
    balance: str,
    net: str,
) -> None:
    result = financial_query.execute(request(case), ACTOR)
    obs = result.observations[0]
    assert obs.value == expected
    assert obs.unit == "CNY"
    assert obs.rule_id == "finance.review.profitDifference.rule"
    assert result.source_activities
    for name, truth in [
        ("profitMatches", profit),
        ("balanceBalances", balance),
        ("netProfitBalances", net),
    ]:
        claim, inputs, diagnostics, digest, activities = evaluate_claim_with_evidence(
            financial_query.bundle,
            financial_query,
            ACTOR,
            claim_id="finance.review." + name,
            bindings={"caseId": case},
            period_from="2024-01-01",
            period_to="2025-01-01",
            dimensions={},
        )
        assert claim.truth == truth
        assert inputs and digest and not diagnostics
        assert set(claim.evidence_refs) == {a.activity_id for a in activities}
        assert all(a.observed_at for a in activities)


def test_search_requires_selection_and_limits_tenant(financial_query: QueryService) -> None:
    result = financial_query.find_objects(
        ObjectSearchRequest(
            object_type="finance.ReviewCase",
            filters={"companyName": "示例企业", "taxYear": 2024},
            properties=("uniquePair",),
            limit=1,
        ),
        ACTOR,
    )
    assert len(result["objects"]) == 1 and result["hasMore"] and result["requiresSelection"]
    assert result["objects"][0]["identity"] == {"caseId": "C1"}
    assert result["objects"][0]["properties"]["companyName"] == "示例企业"
    missing = financial_query.find_objects(
        ObjectSearchRequest(object_type="finance.ReviewCase", filters={"companyName": "别的租户"}),
        ACTOR,
    )
    assert not missing["objects"]


def test_wrong_period_and_incomplete_grain_do_not_return_numbers(
    financial_query: QueryService,
) -> None:
    wrong = QueryContext(business_period={"from": "2025-01-01", "to": "2026-01-01"})
    result = financial_query.execute(request("C1", period=wrong), ACTOR)
    assert result.observations[0].reason == "PERIOD_MISMATCH"
    assert result.observations[0].value is None
    invalid = request("C1").model_copy(
        update={
            "select": (
                MetricSelect(
                    metric="finance.review.audit_profit",
                    bindings={"caseId": "C1", "bogus": "ignored?"},
                ),
            )
        }
    )
    assert financial_query.execute(invalid, ACTOR).observations[0].reason == "INVALID_BINDINGS"
    missing = QueryRequest(
        api_version="semaloom/v0.1",
        select=(
            ObjectSelect(
                object_type="finance.ReviewCase",
                identity={"caseId": "absent"},
                properties=("caseId",),
            ),
        ),
        context=PERIOD,
    )
    assert financial_query.execute(missing, ACTOR).observations[0].kind == "MISSING"


@pytest.mark.parametrize(
    ("kind", "value", "literal"),
    [
        ("BOOLEAN", "True", {"op": "bool", "value": True}),
        ("STRING", "observed", {"op": "string", "value": "observed"}),
        ("DATE", "2024-01-01", {"op": "date", "value": "2024-01-01"}),
        (
            "DATETIME",
            "2024-01-01T00:00:00+00:00",
            {"op": "datetime", "value": "2024-01-01T08:00:00+08:00"},
        ),
    ],
)
def test_typed_rule_values(kind: str, value: str, literal: dict[str, Any]) -> None:
    rule = RuleDef.from_document(
        dict(
            apiVersion="semaloom/v0.1",
            kind="Rule",
            id="x.r",
            version="1",
            claim="x.c",
            inputs=[{"name": "v", "objectType": "x.o", "property": "v"}],
            expression={"op": "eq", "args": [{"op": "ref", "name": "v"}, literal]},
        )
    )
    claim, diagnostics = evaluate_rule(
        rule, {"v": Observation(kind="PRESENT", target="v", value=value, value_type=kind)}
    )
    assert claim.truth == "TRUE" and not diagnostics


def test_numeric_result_is_never_a_true_claim_and_invalid_rules_do_not_compile() -> None:
    rule = RuleDef.from_document(
        dict(
            apiVersion="semaloom/v0.1",
            kind="Rule",
            id="finance.bad",
            version="1",
            claim="finance.bad",
            inputs=[],
            expression={"op": "decimal", "value": "1"},
        )
    )
    assert evaluate_rule(rule, {})[0].truth == "UNKNOWN"
    docs = [doc for _, doc in load_yaml_documents(PACK)]
    assert not compile_documents([*docs, rule.model_dump(by_alias=True, exclude_none=True)]).ok
    rule_doc = rule.model_dump(by_alias=True, exclude_none=True)
    rule_doc.update(
        inputs=[{"name": "v", "objectType": "finance.ReviewCase", "property": "absent"}],
        expression={
            "op": "eq",
            "args": [{"op": "ref", "name": "v"}, {"op": "string", "value": "x"}],
        },
    )
    assert not compile_documents([*docs, rule_doc]).ok


@pytest.mark.parametrize(
    "period",
    [
        {"from": "2024-02-30", "to": "2025-01-01"},
        {"from": "2025-01-01", "to": "2024-01-01"},
        {"from": "2024-01-01"},
    ],
)
def test_invalid_period_rejected(period: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        QueryContext(business_period=period)


def test_expression_budget_is_bounded() -> None:
    node: dict[str, Any] = {"op": "bool", "value": True}
    for _ in range(40):
        node = {"op": "not", "arg": node}
    with pytest.raises(ValueError):
        parse_expr(node)


def test_duplicate_grain_and_nonfinite_source_are_operational_errors(
    financial_query: QueryService,
) -> None:
    engine = financial_query.provider._engines["sample_pg"]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sample_financial_review SELECT * FROM sample_financial_review "
                "WHERE id='C1' AND tenant_id='tenant-a'"
            )
        )
        conn.execute(
            text("UPDATE sample_financial_review SET audit_profit='NaN'::numeric WHERE id='C2'")
        )
    duplicate = financial_query.execute(request("C1", "audit_profit"), ACTOR)
    assert duplicate.observations[0].reason == "CARDINALITY_VIOLATION"
    invalid = financial_query.execute(request("C2", "audit_profit"), ACTOR)
    assert invalid.observations[0].reason == "TYPE_MISMATCH"
    assert invalid.observations[0].value is None


def test_optional_unknown_obeys_three_valued_boolean_logic() -> None:
    rule = RuleDef.from_document(
        dict(
            apiVersion="semaloom/v0.1",
            kind="Rule",
            id="x.r",
            version="1",
            claim="x.c",
            inputs=[{"name": "v", "objectType": "x.o", "property": "v", "required": False}],
            expression={
                "op": "or",
                "args": [{"op": "ref", "name": "v"}, {"op": "bool", "value": True}],
            },
        )
    )
    claim, diagnostics = evaluate_rule(rule, {"v": Observation(kind="MISSING", target="v")})
    assert claim.truth == "TRUE" and not diagnostics
    unknown = rule.model_copy(
        update={
            "expression": parse_expr(
                {"op": "eq", "args": [{"op": "ref", "name": "v"}, {"op": "bool", "value": True}]}
            )
        }
    )
    assert (
        evaluate_rule(unknown, {"v": Observation(kind="MISSING", target="v")})[0].truth == "UNKNOWN"
    )


def test_conflicting_identity_aliases_are_rejected_before_query_or_claim() -> None:
    from semaloom.runtime.eval import EvaluationError

    compiled = compile_paths([ROOT / "examples/tax"])
    assert compiled.bundle is not None
    query = QueryService(compiled.bundle, PostgresReadProvider({}))
    bindings = {"taxpayer": "A", "taxpayerId": "B", "taxYear": 2024}
    result = query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(MetricSelect(metric="tax.reportedIncome", bindings=bindings),),
            context=PERIOD,
        ),
        ACTOR,
    )
    assert result.observations[0].reason == "INVALID_BINDINGS"
    with pytest.raises(EvaluationError, match="conflicting identity aliases"):
        evaluate_claim_with_evidence(
            compiled.bundle,
            query,
            ACTOR,
            claim_id="tax.incomeReconciles",
            bindings=bindings,
            period_from="2024-01-01",
            period_to="2025-01-01",
            dimensions={"jurisdiction": "CN"},
        )

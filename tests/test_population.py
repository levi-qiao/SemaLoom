"""Independent SQL oracle and adversarial collection-analysis cases."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from semaloom.app.chat.presentation import project_browser_answer, visible_answer
from semaloom.app.chat.tools import SemanticTools
from semaloom.core.semantic_query import SemanticQuery
from semaloom.runtime.analysis import execute, prepare
from semaloom.runtime.auth import RequestActor
from tests.analysis_support import analysis_query, run_analysis
from tests.test_business_analysis import ACTOR, financial_query  # noqa: F401


@pytest.fixture
def population_query(financial_query: Any) -> Any:  # noqa: F811
    engine = financial_query.provider._engines["sample_pg"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET company_id=id"))
    return financial_query


@pytest.mark.parametrize(
    ("operation", "sql_op"),
    [("mean", "avg"), ("sum", "sum"), ("min", "min"), ("max", "max"), ("count", "count")],
)
def test_statistics_match_independent_database_oracle(
    population_query: Any, operation: str, sql_op: str
) -> None:
    query = population_query
    result = run_analysis(query, ACTOR, operation=operation)
    with query.provider._engines["sample_pg"].connect() as conn:
        expected = conn.execute(
            text(
                f"SELECT {sql_op}(declared_profit) FROM sample_financial_review "
                "WHERE tenant_id='tenant-a' AND tax_year=2024"
            )
        ).scalar_one()
    assert Decimal(result.values[0]["value"]) == Decimal(expected)
    assert result.scope["complete"]
    assert result.scope["populationCount"] == result.scope["observedCount"] == 3
    assert {row[0] for row in result.evidence.rows} == {"C1", "C2", "C3"}
    assert result.source_activities


@pytest.mark.parametrize(
    ("operation", "numerator", "denominator"),
    [
        ("shareOfTotal", "100.02", "300.03"),
        ("percentAboveMean", ".01", "100.01"),
        ("outperforms", "2", "2"),
    ],
)
def test_comparison_denominator_is_explicit(
    population_query: Any, operation: str, numerator: str, denominator: str
) -> None:
    result = run_analysis(
        population_query,
        ACTOR,
        comparison={"identity": {"caseId": "C2"}, "operation": operation},
    )
    calculation = result.scope["calculation"]
    assert Decimal(calculation["numerator"]) == Decimal(numerator)
    assert Decimal(calculation["denominator"]) == Decimal(denominator)
    assert Decimal(calculation["value"]) == Decimal(numerator) / Decimal(denominator)
    assert result.values[0]["unit"] == ""
    assert result.values[0]["valueType"] == "DECIMAL"
    assert calculation["formula"]
    assert result.mapping_fields
    assert result.mapping_fields[0]["mappingId"]
    assert result.source_activities[0]["formula"] == calculation["formula"]


def test_formula_rejects_difference_between_money_and_count(population_query: Any) -> None:
    from semaloom.core.semantic_query import AnalysisError, Formula, MeasureTerm

    metric = "finance.review.declared_profit"
    query = analysis_query().model_copy(
        update={
            "formula": Formula(
                op="DIFFERENCE",
                left=MeasureTerm(metric=metric, aggregation="SUM"),
                right=MeasureTerm(metric=metric, aggregation="COUNT"),
            )
        }
    )
    with pytest.raises(AnalysisError, match="UNIT_MISMATCH"):
        prepare(population_query, query, ACTOR)


def test_previous_observed_preserves_other_filters(population_query: Any) -> None:
    from semaloom.core.semantic_query import Formula, MeasureTerm

    with population_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sample_financial_review "
                "(tenant_id, id, company_id, tax_year, declared_profit) VALUES "
                "('tenant-a', 'C1-latest', 'C1', 2026, 200), "
                "('tenant-a', 'other', 'other', 2025, 999)"
            )
        )
    query = analysis_query(year=2026, filters={"companyId": "C1"}).model_copy(
        update={
            "formula": Formula(
                op="VALUE",
                left=MeasureTerm(
                    metric="finance.review.declared_profit",
                    aggregation="SUM",
                    previous_observed=True,
                ),
            )
        }
    )
    result = run_analysis(population_query, ACTOR, query=query)
    assert result.scope["calculation"]["priorPeriod"] == 2024
    assert Decimal(result.values[0]["value"]) == Decimal("100.01")


def test_formula_operand_is_checked_before_ready(population_query: Any) -> None:
    from semaloom.core.semantic_query import Formula, MeasureTerm, SubjectSelector

    metric = "finance.review.declared_profit"
    query = analysis_query().model_copy(
        update={
            "formula": Formula(
                op="VALUE",
                left=MeasureTerm(metric=metric, aggregation="SUM", value_relation="LT"),
                subject=SubjectSelector(identity={"caseId": "C2"}),
            )
        }
    )
    assert prepare(population_query, query, ACTOR).status == "UNSUPPORTED"


def test_missing_is_not_zero_and_exclusion_is_explicit(population_query: Any) -> None:
    query = population_query
    strict = run_analysis(query, ACTOR, metric="finance.review.audit_profit")
    assert strict.values == () and strict.scope["missingCount"] == 1
    assert strict.scope["reason"] == "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION"
    partial = run_analysis(
        query, ACTOR, metric="finance.review.audit_profit", missing_policy="exclude"
    )
    assert Decimal(partial.values[0]["value"]) == 100 and partial.scope["observedCount"] == 2
    assert partial.scope["populationCount"] == 3


def test_empty_period_and_duplicate_unit_are_not_averaged(population_query: Any) -> None:
    query = population_query
    empty = run_analysis(query, ACTOR, year=2025)
    assert not empty.values and empty.scope["reason"] == "EMPTY_POPULATION"
    with query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET company_id='duplicate'"))
    with pytest.raises(ValueError, match="DUPLICATE_OR_MISSING_STATISTICAL_UNIT"):
        run_analysis(query, ACTOR)


def test_population_aggregates_beyond_evidence_page(population_query: Any) -> None:
    query = population_query
    with query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sample_financial_review "
                "(tenant_id,id,company_id,tax_year,declared_profit) "
                "SELECT 'tenant-a','extra'||i,'company'||i,2024,1 "
                "FROM generate_series(1,51) i"
            )
        )
    result = run_analysis(query, ACTOR, operation="count")
    assert Decimal(result.values[0]["value"]) == Decimal(54)
    assert result.scope["populationCount"] == 54
    assert len(result.evidence.rows) == 50


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"filters": {"taxYear": 2025}}, "NEEDS_INPUT"),
        ({"filters": {"sql": "SELECT 1"}}, "INVALID_PROPERTIES"),
        (
            {"comparison": {"identity": {"caseId": "outside"}, "operation": "shareOfTotal"}},
            "COMPARISON_SUBJECT_OUTSIDE_POPULATION",
        ),
    ],
)
def test_invalid_scope_is_refused(
    population_query: Any, changes: dict[str, Any], code: str
) -> None:
    with pytest.raises(ValueError, match=code):
        run_analysis(population_query, ACTOR, **changes)


def test_forbidden_and_injected_schema_rejected(population_query: Any) -> None:
    with pytest.raises(PermissionError):
        run_analysis(
            population_query,
            RequestActor(tenant="tenant-a", subject="viewer", roles=()),
        )
    with pytest.raises(ValidationError):
        SemanticQuery.model_validate({"apiVersion": "semaloom/v0.1", "sql": "select 1"})


def test_chat_tool_and_browser_lineage_separation(population_query: Any) -> None:
    gateway = SemanticTools(population_query, ACTOR)
    result = gateway.call(
        "prepare_semantic_query",
        {"query": analysis_query().model_dump(by_alias=True)},
    )
    assert Decimal(result["result"]["values"][0]["value"]) == Decimal("100.01")
    assert "physical" not in str(result) and "sample_financial_review" not in str(result)
    answer = project_browser_answer(gateway.answer, population_query.bundle)
    assert any(m["resource"] == "sample_financial_review" for m in answer["evidence"][0]["lineage"])
    presentation = answer["presentation"]
    assert presentation["version"] == "semaloom/presentation-v0.1"
    assert presentation["metrics"][0]["value"] == result["result"]["values"][0]["value"]
    assert presentation["reports"] == []
    result_labels = answer["evidence"][0]["result"]["labels"]
    assert result["result"]["values"][0]["metric"] in result_labels
    assert not any(key.startswith(("procurement.", "tax.")) for key in result_labels)
    visible = visible_answer(answer, ACTOR)
    assert "lineage" not in visible["evidence"][0]
    assert visible["presentation"] == presentation
    modeler = RequestActor(tenant="tenant-a", subject="test", roles=("analyst", "modeler"))
    assert visible_answer(answer, modeler)["evidence"][0]["lineage"]


@pytest.mark.parametrize(
    ("values", "operation", "direction", "expected", "reason"),
    [
        (["10", "10", "5"], "outperforms", "higher", "0.5", None),
        (["10", "10", "5"], "outperforms", "lower", "0", None),
        (["0", "0", "0"], "shareOfTotal", "higher", None, "ZERO_DENOMINATOR"),
        (["-10", "20", "30"], "shareOfTotal", "higher", "-0.25", None),
        (["-10", "-20", "-30"], "percentAboveMean", "higher", "-0.5", None),
    ],
)
def test_ties_negative_and_zero_denominators(
    population_query: Any,
    values: list[str],
    operation: str,
    direction: str,
    expected: str | None,
    reason: str | None,
) -> None:
    with population_query.provider._engines["sample_pg"].begin() as conn:
        for index, value in enumerate(values, 1):
            conn.execute(
                text("UPDATE sample_financial_review SET declared_profit=:v WHERE id=:id"),
                {"v": Decimal(value), "id": f"C{index}"},
            )
    result = run_analysis(
        population_query,
        ACTOR,
        comparison={
            "identity": {"caseId": "C1"},
            "operation": operation,
            "direction": direction,
        },
    )
    assert result.scope["calculation"]["reason"] == reason
    actual = result.scope["calculation"]["value"]
    assert (Decimal(actual) if actual is not None else None) == (
        Decimal(expected) if expected is not None else None
    )


def test_http_population_and_chat_stream_use_same_engine(
    population_query: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    import json

    from fastapi.testclient import TestClient

    from semaloom.app.bootstrap import build_services
    from semaloom.app.chat.http import router as chat_router
    from semaloom.app.chat.service import ChatService
    from semaloom.app.chat.store import ChatStore
    from semaloom.app.factory import create_app
    from semaloom.app.http import router

    services = build_services(load_data=True)
    monkeypatch.setattr(services, "query_active", lambda tenant: population_query)
    config = tmp_path / "provider.json"
    config.write_text(
        json.dumps({"apiKey": "offline-secret", "baseUrl": "https://example.invalid"})
    )
    worker = tmp_path / "worker.mjs"
    worker.write_text("""import {createInterface} from 'node:readline';
const io=createInterface({input:process.stdin});const emit=x=>console.log(JSON.stringify(x));
io.on('line',line=>{const p=JSON.parse(line);
if(p.type==='start') emit({type:'call',id:'1',name:'prepare_semantic_query',
args:{query:{apiVersion:'semaloom/v0.1',
metrics:[{id:'finance.review.declared_profit',aggregation:'AVG'}],
filters:{field:'taxYear',op:'EQ',value:{valueType:'INTEGER',value:2024}}}}});
else emit({type:'complete',history:[]});});""")
    (tmp_path / "node_modules/@earendil-works/pi-agent-core").mkdir(parents=True)
    app = create_app(load_services=False)
    app.state.services = services
    app.include_router(router)
    app.include_router(chat_router)
    app.state.chat = ChatService(ChatStore(services.studio_drafts.engine), config)
    app.state.chat.worker = worker
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer tenant-a-analyst"}
            prepared = client.post(
                "/v0.1/semantic/prepare",
                headers=headers,
                json=analysis_query().model_dump(by_alias=True),
            )
            assert prepared.status_code == 200
            plan = prepared.json()["plan"]
            direct = client.post("/v0.1/semantic/execute", headers=headers, json=plan)
            assert direct.status_code == 200
            streamed = client.post(
                "/v0.1/chat/turns", headers=headers, json={"message": "Average in 2024"}
            )
            events = [json.loads(line) for line in streamed.text.splitlines()]
            assert events[-1]["type"] == "done", events
            answer = next(e["answer"] for e in events if e["type"] == "answer")
            assert (
                answer["evidence"][0]["result"]["values"][0]["value"]
                == direct.json()["values"][0]["value"]
                == "100.01"
            )
            assert "lineage" not in answer["evidence"][0]
            history = client.get(
                "/v0.1/chat/conversations/" + events[0]["conversationId"], headers=headers
            ).json()
            assert history["turns"][0]["answer"] == answer
    finally:
        services.close()


def test_subject_filter_resolves_in_full_cohort_without_changing_denominator(
    population_query: Any,
) -> None:
    result = run_analysis(
        population_query,
        ACTOR,
        comparison={"filters": {"companyName": "缺失样本"}, "operation": "shareOfTotal"},
    )
    assert result.scope["populationCount"] == 3
    assert result.scope["subjectIdentity"] == "C3"
    assert Decimal(result.scope["calculation"]["denominator"]) == Decimal("300.03")
    with pytest.raises(ValueError, match="AMBIGUOUS_COMPARISON_SUBJECT"):
        run_analysis(
            population_query,
            ACTOR,
            comparison={"filters": {"companyName": "示例企业"}, "operation": "shareOfTotal"},
        )
    with pytest.raises(ValueError, match="SUBJECT_FILTER_MUST_NOT_RESTRICT_POPULATION"):
        run_analysis(
            population_query,
            ACTOR,
            filters={"companyName": "缺失样本"},
            comparison={"filters": {"companyName": "缺失样本"}, "operation": "shareOfTotal"},
        )


def test_statistical_chat_finishes_with_engine_narrative_and_metric_lineage(
    population_query: Any,
) -> None:
    gateway = SemanticTools(population_query, ACTOR, "2024年选定申报利润总额均值")
    result = gateway.call(
        "prepare_semantic_query",
        {"query": analysis_query().model_dump(by_alias=True)},
    )
    assert result["answerReady"] is True
    assert gateway.answer["textOrigin"] == "ENGINE"
    assert result["result"]["values"][0]["value"] in gateway.answer["text"]
    answer = project_browser_answer(gateway.answer, population_query.bundle)
    assert any(m["targetKind"] == "metric" for m in answer["evidence"][0]["lineage"])


def test_lower_is_better_narrative_matches_comparison_not_raw_value_order(
    population_query: Any,
) -> None:
    from semaloom.app.chat.summary import semantic_summary

    semantic = analysis_query(
        comparison={
            "identity": {"caseId": "C3"},
            "operation": "outperforms",
            "direction": "lower",
        }
    )
    prepared = prepare(population_query, semantic, ACTOR)
    executed = execute(population_query, prepared.plan, ACTOR)
    narrative = semantic_summary(population_query.bundle, semantic, executed)
    assert "越小越好" in narrative and "越大越好" not in narrative
    assert executed.scope["calculation"]["value"] in narrative


def test_domains_inherit_grain_and_compose_previous_period() -> None:
    """Tax year binds without a time role; procurement string periods shift by observation."""
    from decimal import Decimal
    from pathlib import Path

    from sqlalchemy import create_engine, text

    from semaloom.adapters.postgres import PostgresReadProvider
    from semaloom.app.chat.choices import prepare_turn, query_from_intent
    from semaloom.app.chat.intent import TurnIntent
    from semaloom.core.semantic_query import (
        FilterAtom,
        Formula,
        MeasureTerm,
        MetricRef,
        SemanticQuery,
        TypedValue,
    )
    from semaloom.runtime.fixtures import engines
    from semaloom.runtime.query import QueryService
    from semaloom.sdk import compile_paths

    root = Path(__file__).resolve().parents[1]
    tax = compile_paths([root / "examples/tax"]).bundle
    procurement = compile_paths([root / "examples/procurement"]).bundle
    assert tax is not None and procurement is not None
    year = next(
        prop
        for obj in tax.object_types
        if obj.id == "tax.Taxpayer"
        for prop in obj.properties
        if prop.id == "taxYear"
    )
    assert year.semantic_roles == ()
    reported = next(metric for metric in tax.metrics if metric.id == "tax.reportedIncome")
    assert reported.select["measureCode"] == "reportedIncome"
    assert reported.unit == "CNY"
    assert reported.additivity == "FULL"
    assert "taxpayerId" in reported.grain
    amount = next(
        metric for metric in procurement.metrics if metric.id == "procurement.orderAmount"
    )
    assert amount.unit == "CNY" and amount.additivity == "FULL" and "orderId" in amount.grain
    period = next(
        prop
        for obj in procurement.object_types
        if obj.id == "procurement.Contract"
        for prop in obj.properties
        if prop.id == "accountingPeriod"
    )
    assert period.semantic_roles == ()
    intent = TurnIntent.read("2024年申报收入合计", tax)
    assert query_from_intent(intent, tax).filters is not None

    tax_engine = engines()["tax_pg"]
    order_engine = engines()["orders_pg"]
    with tax_engine.connect() as tax_conn, order_engine.connect() as order_conn:
        tax_conn.execute(text("DROP SCHEMA IF EXISTS domain_compose CASCADE"))
        order_conn.execute(text("DROP SCHEMA IF EXISTS domain_compose CASCADE"))
        tax_conn.execute(text("CREATE SCHEMA domain_compose"))
        tax_conn.execute(text("SET search_path TO domain_compose"))
        order_conn.execute(text("CREATE SCHEMA domain_compose"))
        order_conn.execute(text("SET search_path TO domain_compose"))
        tax_conn.execute(
            text(
                """CREATE TABLE tax_metric (
                tenant_id TEXT, taxpayer_id TEXT, tax_year INTEGER,
                perspective TEXT, metric TEXT, amount NUMERIC)"""
            )
        )
        tax_conn.execute(
            text(
                """INSERT INTO tax_metric VALUES
                ('tenant-a','TAXPAYER-A',2024,'TAX_RETURN','reportedIncome',110.10),
                ('tenant-a','TAXPAYER-B',2024,'TAX_RETURN','reportedIncome',80.00),
                ('tenant-a','TAXPAYER-A',2025,'TAX_RETURN','reportedIncome',200.00),
                ('tenant-a','TAXPAYER-A',2024,'AUDIT_REPORT','reportedIncome',999)"""
            )
        )
        order_conn.execute(
            text(
                """CREATE TABLE proc_contract (
                tenant_id TEXT, contract_id TEXT, organization_id TEXT, supplier_id TEXT,
                accounting_period TEXT, category TEXT, status TEXT,
                contract_value NUMERIC, committed_spend NUMERIC)"""
            )
        )
        order_conn.execute(
            text(
                """INSERT INTO proc_contract VALUES
                ('tenant-a','C1','O1','S1','2024-01','GOODS','ACTIVE',2500,1800),
                ('tenant-a','C2','O1','S2','2024-01','SERVICE','ACTIVE',1800,1750),
                ('tenant-a','C3','O2','S3','2024-01','LOGISTICS','CLOSED',900,900),
                ('tenant-a','C4','O2','S2','2025-01','GOODS','ACTIVE',3200,1600),
                ('tenant-a','C5','O1','S3','2025-01','SERVICE','EXPIRING',1200,1100),
                ('tenant-a','C6','O2','S1','2025-01','LOGISTICS','ACTIVE',2100,NULL)"""
            )
        )
        tax_conn.commit()
        order_conn.commit()
        tax_read = create_engine(
            tax_engine.url, connect_args={"options": "-csearch_path=domain_compose"}
        )
        order_read = create_engine(
            order_engine.url, connect_args={"options": "-csearch_path=domain_compose"}
        )
        try:
            tax_service = QueryService(tax, PostgresReadProvider({"tax_pg": tax_read}))
            procurement_service = QueryService(
                procurement, PostgresReadProvider({"orders_pg": order_read})
            )
            reported_query = SemanticQuery(
                api_version="semaloom/v0.1",
                metrics=(MetricRef(id="tax.reportedIncome", aggregation="SUM"),),
                filters=FilterAtom(
                    field="taxYear", op="EQ", value=TypedValue(value_type="INTEGER", value=2024)
                ),
            )
            prepared = prepare(tax_service, reported_query, ACTOR)
            assert prepared.status == "READY" and prepared.plan is not None
            reported_result = execute(tax_service, prepared.plan, ACTOR)
            with tax_read.connect() as conn:
                oracle = conn.execute(
                    text(
                        "SELECT SUM(amount) FROM tax_metric WHERE tenant_id='tenant-a' "
                        "AND tax_year=2024 AND perspective='TAX_RETURN' AND metric='reportedIncome'"
                    )
                ).scalar_one()
            assert Decimal(reported_result.values[0]["value"]) == Decimal(oracle)

            previous = SemanticQuery(
                api_version="semaloom/v0.1",
                metrics=(MetricRef(id="procurement.contractValue", aggregation="SUM"),),
                filters=FilterAtom(
                    field="accountingPeriod",
                    op="EQ",
                    value=TypedValue(value_type="STRING", value="2025-01"),
                ),
                formula=Formula(
                    op="VALUE",
                    left=MeasureTerm(
                        metric="procurement.contractValue",
                        aggregation="SUM",
                        previous_observed=True,
                    ),
                ),
            )
            prepared = prepare(procurement_service, previous, ACTOR)
            assert prepared.status == "READY" and prepared.plan is not None
            shifted = execute(procurement_service, prepared.plan, ACTOR)
            with order_read.connect() as conn:
                prior = conn.execute(
                    text(
                        "SELECT SUM(contract_value) FROM proc_contract "
                        "WHERE tenant_id='tenant-a' AND accounting_period='2024-01'"
                    )
                ).scalar_one()
            assert Decimal(shifted.values[0]["value"]) == Decimal(prior)
            assert shifted.scope["calculation"]["priorPeriod"] == "2024-01"
            assert shifted.mapping_fields

            difference = SemanticQuery(
                api_version="semaloom/v0.1",
                metrics=(
                    MetricRef(id="procurement.contractValue", aggregation="SUM"),
                    MetricRef(id="procurement.committedSpend", aggregation="SUM"),
                ),
                filters=FilterAtom(
                    field="accountingPeriod",
                    op="EQ",
                    value=TypedValue(value_type="STRING", value="2024-01"),
                ),
                formula=Formula(
                    op="DIFFERENCE",
                    left=MeasureTerm(metric="procurement.contractValue", aggregation="SUM"),
                    right=MeasureTerm(metric="procurement.committedSpend", aggregation="SUM"),
                ),
            )
            prepared = prepare(procurement_service, difference, ACTOR)
            assert prepared.status == "READY" and prepared.plan is not None
            diff = execute(procurement_service, prepared.plan, ACTOR)
            with order_read.connect() as conn:
                expected = conn.execute(
                    text(
                        "SELECT SUM(contract_value) - SUM(committed_spend) FROM proc_contract "
                        "WHERE tenant_id='tenant-a' AND accounting_period='2024-01'"
                    )
                ).scalar_one()
            assert Decimal(diff.values[0]["value"]) == Decimal(expected)
            assert "-" in diff.scope["calculation"]["formula"]

            refused = prepare(
                procurement_service,
                SemanticQuery(
                    api_version="semaloom/v0.1",
                    metrics=(MetricRef(id="procurement.contractUtilization", aggregation="SUM"),),
                    filters=FilterAtom(
                        field="accountingPeriod",
                        op="EQ",
                        value=TypedValue(value_type="STRING", value="2024-01"),
                    ),
                ),
                ACTOR,
            )
            assert refused.status == "UNSUPPORTED"
            assert refused.capability == "ADDITIVITY_VIOLATION"

            chat = prepare_turn(procurement_service, ACTOR, "2025-01合同总额月环比")
            assert chat.get("status") == "READY"
            assert Decimal(chat["result"]["values"][0]["value"]) == Decimal(prior)
            grouped = prepare_turn(procurement_service, ACTOR, "2025-01按合同类别合计合同总额")
            assert grouped.get("status") == "READY"
            grains = {row["grain"].get("category") for row in grouped["result"]["values"]}
            assert grains == {"GOODS", "SERVICE", "LOGISTICS"}
            unknown = prepare_turn(procurement_service, ACTOR, "按航线合计合同总额")
            assert unknown["status"] == "NEEDS_INPUT"
            assert unknown["question"]["slot"] == "group"
            assert unknown.get("errorCode") is None
        finally:
            tax_read.dispose()
            order_read.dispose()
            tax_conn.rollback()
            order_conn.rollback()
            tax_conn.execute(text("SET search_path TO public"))
            order_conn.execute(text("SET search_path TO public"))
            tax_conn.execute(text("DROP SCHEMA domain_compose CASCADE"))
            order_conn.execute(text("DROP SCHEMA domain_compose CASCADE"))
            tax_conn.commit()
            order_conn.commit()


def test_formula_scans_enforce_missing_duplicate_and_full_period_sequence() -> None:
    """Term scans, not the unshifted request, own missingness, duplicates, and evidence."""
    from pathlib import Path

    from sqlalchemy import create_engine, text

    from semaloom.adapters.postgres import PostgresReadProvider
    from semaloom.core.semantic_query import (
        FilterAtom,
        Formula,
        MeasureTerm,
        MetricRef,
        SemanticQuery,
        TypedValue,
    )
    from semaloom.runtime.fixtures import engines
    from semaloom.runtime.query import QueryService
    from semaloom.sdk import compile_paths

    bundle = compile_paths([Path(__file__).resolve().parents[1] / "examples/procurement"]).bundle
    assert bundle is not None
    periods = []
    year, month = 2020, 1
    for _ in range(31):
        periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    engine = engines()["orders_pg"]
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS formula_scan CASCADE"))
        conn.execute(text("CREATE SCHEMA formula_scan"))
        conn.execute(text("SET search_path TO formula_scan"))
        conn.execute(
            text(
                """CREATE TABLE proc_contract (
                tenant_id TEXT, contract_id TEXT, organization_id TEXT, supplier_id TEXT,
                accounting_period TEXT, category TEXT, status TEXT,
                contract_value NUMERIC, committed_spend NUMERIC)"""
            )
        )
        rows: list[dict[str, object]] = [
            {
                "id": "C1",
                "period": "2025-01",
                "value": Decimal("3200"),
                "spend": Decimal("1600"),
            },
            {"id": "C2", "period": "2025-01", "value": Decimal("2100"), "spend": None},
            {"id": "D1", "period": "2024-01", "value": Decimal("10"), "spend": Decimal("10")},
            {"id": "D1", "period": "2024-02", "value": Decimal("20"), "spend": Decimal("20")},
            {"id": "D1", "period": "2024-02", "value": Decimal("30"), "spend": None},
            {"id": "E1", "period": "2023-01", "value": Decimal("5"), "spend": Decimal("5")},
            {"id": "E1", "period": "2023-01", "value": Decimal("6"), "spend": Decimal("6")},
            {"id": "E1", "period": "2023-02", "value": Decimal("7"), "spend": Decimal("7")},
        ]
        for index, period in enumerate(periods, start=1):
            rows.append(
                {
                    "id": "F1",
                    "period": period,
                    "value": Decimal(index * 100),
                    "spend": Decimal(index * 100),
                }
            )
        rows.append({"id": "FNULL", "period": periods[-1], "value": None, "spend": None})
        conn.execute(
            text(
                """INSERT INTO proc_contract VALUES
                ('tenant-a', :id, 'O1', 'S1', :period, 'GOODS', 'ACTIVE', :value, :spend)"""
            ),
            rows,
        )
        conn.commit()
        read = create_engine(engine.url, connect_args={"options": "-csearch_path=formula_scan"})
        try:
            service = QueryService(bundle, PostgresReadProvider({"orders_pg": read}))

            def run(query: SemanticQuery):
                prepared = prepare(service, query, ACTOR)
                assert prepared.status == "READY" and prepared.plan is not None
                return execute(service, prepared.plan, ACTOR)

            difference = SemanticQuery(
                api_version="semaloom/v0.1",
                metrics=(
                    MetricRef(id="procurement.contractValue", aggregation="SUM"),
                    MetricRef(id="procurement.committedSpend", aggregation="SUM"),
                ),
                filters=FilterAtom(
                    field="accountingPeriod",
                    op="EQ",
                    value=TypedValue(value_type="STRING", value="2025-01"),
                ),
                formula=Formula(
                    op="DIFFERENCE",
                    left=MeasureTerm(metric="procurement.contractValue", aggregation="SUM"),
                    right=MeasureTerm(metric="procurement.committedSpend", aggregation="SUM"),
                ),
                missing_policy="reject",
            )
            refused = run(difference)
            with read.connect() as check:
                nulls = check.execute(
                    text(
                        "SELECT COUNT(*) FROM proc_contract WHERE tenant_id='tenant-a' "
                        "AND accounting_period='2025-01' AND committed_spend IS NULL"
                    )
                ).scalar_one()
            assert nulls == 1
            assert refused.values == ()
            assert refused.scope["reason"] == "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION"
            assert refused.scope["calculation"]["value"] is None
            assert refused.scope["missingCount"] == 1

            previous = Formula(
                op="VALUE",
                left=MeasureTerm(
                    metric="procurement.contractValue",
                    aggregation="SUM",
                    previous_observed=True,
                ),
            )
            current_duplicate = run(
                SemanticQuery(
                    api_version="semaloom/v0.1",
                    metrics=(MetricRef(id="procurement.contractValue", aggregation="SUM"),),
                    filters=FilterAtom(
                        field="accountingPeriod",
                        op="EQ",
                        value=TypedValue(value_type="STRING", value="2024-02"),
                    ),
                    formula=previous,
                    missing_policy="reject",
                )
            )
            with read.connect() as check:
                prior_total = check.execute(
                    text(
                        "SELECT SUM(contract_value) FROM proc_contract "
                        "WHERE tenant_id='tenant-a' AND accounting_period='2024-01'"
                    )
                ).scalar_one()
            assert Decimal(current_duplicate.values[0]["value"]) == Decimal(prior_total)
            assert current_duplicate.scope["populationCount"] == 1
            assert current_duplicate.scope["missingCount"] == 0
            assert {Decimal(row[-1]) for row in current_duplicate.evidence.rows} == {
                Decimal(prior_total)
            }
            executed = str(current_duplicate.scope["executedFilters"])
            assert "2024-01" in executed
            assert "2024-02" not in executed

            with pytest.raises(ValueError, match="DUPLICATE_OR_MISSING_STATISTICAL_UNIT"):
                run(
                    SemanticQuery(
                        api_version="semaloom/v0.1",
                        metrics=(MetricRef(id="procurement.contractValue", aggregation="SUM"),),
                        filters=FilterAtom(
                            field="accountingPeriod",
                            op="EQ",
                            value=TypedValue(value_type="STRING", value="2023-02"),
                        ),
                        formula=previous,
                        missing_policy="reject",
                    )
                )

            latest = run(
                SemanticQuery(
                    api_version="semaloom/v0.1",
                    metrics=(MetricRef(id="procurement.contractValue", aggregation="SUM"),),
                    filters=FilterAtom(
                        field="accountingPeriod",
                        op="EQ",
                        value=TypedValue(value_type="STRING", value=periods[-1]),
                    ),
                    formula=previous,
                    missing_policy="reject",
                )
            )
            with read.connect() as check:
                expected_prior = check.execute(
                    text(
                        "SELECT SUM(contract_value) FROM proc_contract "
                        "WHERE tenant_id='tenant-a' AND accounting_period=:period"
                    ),
                    {"period": periods[-2]},
                ).scalar_one()
            assert Decimal(latest.values[0]["value"]) == Decimal(expected_prior)
            assert latest.scope["calculation"]["priorPeriod"] == periods[-2]
            assert periods[-2] in str(latest.scope["executedFilters"])
            assert {Decimal(row[-1]) for row in latest.evidence.rows} == {Decimal(expected_prior)}
            assert latest.scope["missingCount"] == 0
        finally:
            read.dispose()
            conn.rollback()
            conn.execute(text("SET search_path TO public"))
            conn.execute(text("DROP SCHEMA formula_scan CASCADE"))
            conn.commit()

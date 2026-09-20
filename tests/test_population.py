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
    comparison = result.scope["comparison"]
    assert Decimal(comparison["numerator"]) == Decimal(numerator)
    assert Decimal(comparison["denominator"]) == Decimal(denominator)
    assert Decimal(comparison["value"]) == Decimal(numerator) / Decimal(denominator) * 100


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
        (["10", "10", "5"], "outperforms", "higher", "50", None),
        (["10", "10", "5"], "outperforms", "lower", "0", None),
        (["0", "0", "0"], "shareOfTotal", "higher", None, "ZERO_DENOMINATOR"),
        (["-10", "20", "30"], "shareOfTotal", "higher", None, "NEGATIVE_VALUES_NOT_A_SHARE"),
        (["-10", "-20", "-30"], "percentAboveMean", "higher", None, "NON_POSITIVE_MEAN"),
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
    assert result.scope["comparison"]["reason"] == reason
    actual = result.scope["comparison"]["value"]
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
    assert Decimal(result.scope["comparison"]["denominator"]) == Decimal("300.03")
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
    assert executed.scope["comparison"]["value"] in narrative

"""Choice persist/resume on the shipped store and submit_choice path."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from semaloom.app.chat.choices import (
    prepare_turn,
    query_from_intent,
    submit_choice,
    try_direct_turn,
)
from semaloom.app.chat.http import router as chat_router
from semaloom.app.chat.intent import TurnIntent
from semaloom.app.chat.store import ChatStore
from semaloom.app.chat.tools import SemanticTools
from semaloom.app.factory import create_app
from semaloom.app.http import router
from semaloom.core.semantic_query import (
    ChoiceError,
    ChoiceSubmit,
    FilterAtom,
    GroupByItem,
    MetricRef,
    SemanticQuery,
    TypedValue,
)
from semaloom.runtime.auth import RequestActor
from tests.test_business_analysis import ACTOR, financial_query  # noqa: F401


@pytest.fixture
def population_query(financial_query: Any) -> Any:  # noqa: F811
    engine = financial_query.provider._engines["sample_pg"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET company_id=id"))
    return financial_query


def test_intent_allows_multi_year_and_metric_for_generic_query(population_query: Any) -> None:
    intent = TurnIntent.read("2024年和2025年申报营业收入与应纳税所得额", population_query.bundle)
    assert intent.multiple_years is True
    query = query_from_intent(intent, population_query.bundle)
    assert isinstance(query, SemanticQuery)


def test_complete_named_metric_year_uses_tax_year_field(population_query: Any) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    intent = TurnIntent.read("2024年申报营业收入合计", population_query.bundle)
    built = query_from_intent(intent, population_query.bundle)
    assert isinstance(built.filters, FilterAtom)
    assert built.filters.field == "taxYear"
    result = prepare_turn(population_query, ACTOR, "2024年申报营业收入合计")
    assert result["status"] == "READY"
    assert result.get("answerReady")
    assert result["result"]["values"][0]["value"] in result["text"]
    assert "平均值" not in result["text"]


def test_prepare_turn_needs_metric_then_year(population_query: Any) -> None:
    first = prepare_turn(population_query, ACTOR, "收入多少？")
    assert first["status"] == "NEEDS_INPUT"
    assert first["question"]["slot"] == "metric"
    assert first["waiting"] is True
    assert first["releaseDigest"] == population_query.bundle.digest
    kinds = {item["choice"]["kind"] for item in first["question"]["options"]}
    assert kinds >= {"ABORT", "OTHER"}


def test_prepare_semantic_query_tool_waits_on_ambiguous_metric(population_query: Any) -> None:
    tools = SemanticTools(population_query, ACTOR, user_message="收入多少")
    payload = tools.call("prepare_semantic_query", {"question": "收入多少"})
    assert payload["status"] == "NEEDS_INPUT"
    assert payload["waiting"] is True
    assert payload["releaseDigest"] == population_query.bundle.digest
    assert tools.pending is not None
    assert tools.pending["question"]["slot"] == "metric"
    assert tools.pending["question"]["questionId"].startswith("q-metric-intent-")
    metric_ids = {
        item["choice"]["id"]
        for item in payload["question"]["options"]
        if item["choice"]["kind"] == "METRIC"
    }
    assert metric_ids == {"finance.declaredRevenue", "finance.taxableIncome"}


def test_source_error_includes_release_digest(population_query: Any) -> None:
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="finance.declaredRevenue", aggregation="SUM"),),
        filters=FilterAtom(
            field="taxYear",
            op="EQ",
            value=TypedValue(value_type="INTEGER", value=2024),
        ),
    )
    result = prepare_turn(population_query, ACTOR, "申报营业收入", query)
    assert result["status"] == "SOURCE_ERROR"
    assert result["releaseDigest"] == population_query.bundle.digest


def _load_declaration(engine: Any) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sample_declaration (
                  tenant_id TEXT, id TEXT, taxpayer_id TEXT, tax_year INTEGER,
                  period_start DATE, period_end DATE,
                  revenue NUMERIC, total_profit NUMERIC, taxable_income NUMERIC,
                  income_tax NUMERIC
                )
                """
            )
        )
        conn.execute(text("DELETE FROM sample_declaration"))
        conn.execute(
            text(
                """
                INSERT INTO sample_declaration VALUES
                ('tenant-a','D1','C1',2024,'2024-01-01','2025-01-01',100.01,80,90.01,20),
                ('tenant-a','D2','C2',2024,'2024-01-01','2025-01-01',100.02,79,90.02,20),
                ('tenant-a','D3','C3',2024,'2024-01-01','2025-01-01',100.00,80,90.00,20)
                """
            )
        )


def test_two_round_compute_uses_engine_numbers(population_query: Any) -> None:
    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
    store = ChatStore(engine)
    row = store.create(ACTOR, population_query.bundle.digest)
    first = prepare_turn(population_query, ACTOR, "收入多少？")
    store.save_pending(ACTOR, row, first["question"], {"query": first["query"]}, "收入多少？")
    metric_opt = next(
        item["id"] for item in first["question"]["options"] if item["choice"]["kind"] == "METRIC"
    )
    second = submit_choice(
        store,
        population_query,
        ACTOR,
        row["id"],
        ChoiceSubmit.model_validate(
            {
                "questionId": first["question"]["questionId"],
                "revision": 1,
                "optionIds": [metric_opt],
            }
        ),
    )
    assert second.get("answerReady")
    assert second.get("textOrigin") == "ENGINE"
    assert second.get("population") is None
    engine_value = second["result"]["values"][0]["value"]
    assert "平均值" not in second["text"]
    assert engine_value in second["text"]
    assert second["evidence"][0]["lineage"]
    assert second["confidence"]["label"] in {"高", "中", "低"}
    assert any(item["slot"] == "year" for item in second["assumptions"])


def test_two_round_submit_keeps_metric_and_year(population_query: Any) -> None:
    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
    store = ChatStore(engine)
    row = store.create(ACTOR, population_query.bundle.digest)
    first = prepare_turn(population_query, ACTOR, "收入多少？")
    store.save_pending(ACTOR, row, first["question"], {"query": first["query"]}, "收入多少？")
    metric_opt = next(
        item["id"] for item in first["question"]["options"] if item["choice"]["kind"] == "METRIC"
    )
    second = submit_choice(
        store,
        population_query,
        ACTOR,
        row["id"],
        ChoiceSubmit.model_validate(
            {
                "questionId": first["question"]["questionId"],
                "revision": 1,
                "optionIds": [metric_opt],
            }
        ),
    )
    assert second.get("answerReady")
    saved = store.load(ACTOR, row["id"])
    assert saved["pending"] is None
    assert saved["turns"]
    assert saved["turns"][0]["answer"]["confidence"]["label"] in {"高", "中", "低"}


def test_forged_and_abort_do_not_invent_answers(population_query: Any) -> None:
    store = ChatStore(population_query.provider._engines["sample_pg"])
    row = store.create(ACTOR, population_query.bundle.digest)
    first = prepare_turn(population_query, ACTOR, "收入多少？")
    store.save_pending(ACTOR, row, first["question"], {"query": first["query"]}, "收入多少？")
    with pytest.raises(ChoiceError, match="UNKNOWN_OPTION"):
        submit_choice(
            store,
            population_query,
            ACTOR,
            row["id"],
            ChoiceSubmit.model_validate(
                {
                    "questionId": first["question"]["questionId"],
                    "revision": 1,
                    "optionIds": ["forged"],
                }
            ),
        )
    abort = next(
        item["id"] for item in first["question"]["options"] if item["choice"]["kind"] == "ABORT"
    )
    result = submit_choice(
        store,
        population_query,
        ACTOR,
        row["id"],
        ChoiceSubmit.model_validate(
            {"questionId": first["question"]["questionId"], "revision": 1, "optionIds": [abort]}
        ),
    )
    assert result["status"] == "ABORTED"
    assert store.load(ACTOR, row["id"])["pending"] is None


def test_http_choice_restore_roundtrip(population_query: Any) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    store = ChatStore(population_query.provider._engines["sample_pg"])
    http_actor = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
    row = store.create(http_actor, population_query.bundle.digest)
    first = prepare_turn(population_query, http_actor, "收入多少？")
    store.save_pending(http_actor, row, first["question"], {"query": first["query"]}, "收入多少？")
    app = create_app(load_services=False)
    app.include_router(router)
    app.include_router(chat_router)

    class Chat:
        def __init__(self) -> None:
            self.store = store

        def status(self) -> dict[str, Any]:
            return {"enabled": True, "ready": True}

    class Services:
        def query_active(self, tenant: str | None = None) -> Any:
            return population_query

    app.state.chat = Chat()
    app.state.services = Services()
    client = TestClient(app)
    headers = {"Authorization": "Bearer tenant-a-analyst"}
    restored = client.get(f"/v0.1/chat/conversations/{row['id']}", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["pendingQuestion"]["questionId"] == first["question"]["questionId"]
    metric_opt = next(
        item["id"] for item in first["question"]["options"] if item["choice"]["kind"] == "METRIC"
    )
    chosen = client.post(
        "/v0.1/chat/choices",
        headers=headers,
        json={
            "conversationId": row["id"],
            "questionId": first["question"]["questionId"],
            "revision": 1,
            "optionIds": [metric_opt],
        },
    )
    assert chosen.status_code == 200
    body = chosen.json()
    assert body.get("answerReady") or body["status"] == "READY"


def test_direct_turn_skips_model_for_named_metric(population_query: Any) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    assert try_direct_turn(population_query, ACTOR, "你好") is None
    assert try_direct_turn(population_query, ACTOR, "申报营业收入是什么") is None
    named = try_direct_turn(population_query, ACTOR, "申报营业收入")
    assert named is not None and named.get("answerReady")
    vague = try_direct_turn(population_query, ACTOR, "收入多少")
    assert vague is not None and vague["status"] == "NEEDS_INPUT"
    assert any(item["choice"]["kind"] == "OTHER" for item in vague["question"]["options"])


def test_named_metric_answers_with_assumed_year(population_query: Any) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    result = prepare_turn(population_query, ACTOR, "申报营业收入")
    assert result.get("answerReady")
    assert result["confidence"]["label"] in {"高", "中", "低"}
    assert any(item["slot"] == "year" for item in result["assumptions"])
    assert any(item["slot"] == "aggregation" for item in result["assumptions"])
    assert "置信度" in result["text"]
    assert not result["query"].get("groupBy")


def test_unsolicited_groupby_is_stripped(population_query: Any) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="finance.declaredRevenue", aggregation="SUM"),),
        group_by=(GroupByItem(id="companyId"),),
        filters=FilterAtom(
            field="taxYear",
            op="EQ",
            value=TypedValue(value_type="INTEGER", value=2024),
        ),
    )
    result = prepare_turn(population_query, ACTOR, "申报营业收入", query)
    assert result.get("answerReady")
    assert result["query"].get("groupBy") in (None, [])
    assert len(result["result"]["values"]) == 1
    assert not result["result"]["values"][0].get("grain")


def test_other_free_text_continues_original_question(population_query: Any) -> None:
    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
    store = ChatStore(engine)
    row = store.create(ACTOR, population_query.bundle.digest)
    first = prepare_turn(population_query, ACTOR, "收入多少？")
    store.save_pending(ACTOR, row, first["question"], {"query": first["query"]}, "收入多少？")
    other = next(
        item["id"] for item in first["question"]["options"] if item["choice"]["kind"] == "OTHER"
    )
    with pytest.raises(ChoiceError, match="OTHER_TEXT_REQUIRED"):
        submit_choice(
            store,
            population_query,
            ACTOR,
            row["id"],
            ChoiceSubmit.model_validate(
                {
                    "questionId": first["question"]["questionId"],
                    "revision": 1,
                    "optionIds": [other],
                }
            ),
        )
    done = submit_choice(
        store,
        population_query,
        ACTOR,
        row["id"],
        ChoiceSubmit.model_validate(
            {
                "questionId": first["question"]["questionId"],
                "revision": 1,
                "optionIds": [other],
                "otherText": "申报营业收入 2024年合计",
            }
        ),
    )
    assert done.get("answerReady")
    assert done["result"]["values"][0]["value"] in done["text"]

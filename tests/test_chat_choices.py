"""Choice persist/resume on the shipped store and submit_choice path."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from semaloom.app.bootstrap import compile_examples
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
    equality_value,
)
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService
from tests.test_business_analysis import ACTOR, financial_query  # noqa: F401


@pytest.fixture
def population_query(financial_query: Any) -> Any:  # noqa: F811
    engine = financial_query.provider._engines["sample_pg"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET company_id=id"))
    return financial_query


def test_intent_allows_multi_year_and_metric_for_generic_query(population_query: Any) -> None:
    intent = TurnIntent.read("2024年和2025年申报营业收入与应纳税所得额", population_query.bundle)
    assert intent.role_constraints[0].role == "time.year"
    assert intent.role_constraints[0].operator == "IN"
    assert intent.role_constraints[0].values == (2024, 2025)
    assert intent.grouping_role == "time.year"
    query = query_from_intent(intent, population_query.bundle)
    assert isinstance(query, SemanticQuery)
    assert query.group_by == (GroupByItem(id="taxYear"),)


def test_year_language_only_targets_a_declared_year_role() -> None:
    bundle = compile_examples()
    intent = TurnIntent.read("2026年合同总额合计", bundle)
    query = query_from_intent(intent, bundle)
    assert query.metrics[0].id == "procurement.contractValue"
    assert query.filters is None

    trend = query_from_intent(TurnIntent.read("合同总额趋势", bundle), bundle)
    assert trend.group_by == (GroupByItem(id="accountingPeriod"),)


def test_recent_year_trend_uses_available_periods_and_preserves_year_grain(
    population_query: Any,
) -> None:
    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sample_declaration
                SELECT tenant_id, id || '-23', taxpayer_id, 2023,
                       DATE '2023-01-01', DATE '2024-01-01', revenue - 10,
                       total_profit, taxable_income, income_tax
                FROM sample_declaration WHERE tax_year = 2024
                UNION ALL
                SELECT tenant_id, id || '-25', taxpayer_id, 2025,
                       DATE '2025-01-01', DATE '2026-01-01', revenue + 10,
                       total_profit, taxable_income, income_tax
                FROM sample_declaration WHERE tax_year = 2024
                """
            )
        )
    result = prepare_turn(population_query, ACTOR, "近三年申报营业收入合计趋势")
    assert result["status"] == "READY"
    assert result["query"]["groupBy"] == [{"id": "taxYear", "timeGrain": None}]
    assert {row["grain"]["taxYear"] for row in result["result"]["values"]} == {
        2023,
        2024,
        2025,
    }
    assert all("labels" not in row for row in result["result"]["values"])


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


def _confirm_scope(
    store: ChatStore, service: Any, conversation_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    for slot, kind, value in (
        ("scope:taxYear", "DIMENSION_VALUE", "2024"),
        ("aggregation", "AGGREGATION", "SUM"),
    ):
        assert result["status"] == "NEEDS_INPUT"
        assert result["question"]["slot"] == slot
        restored = store.load(ACTOR, conversation_id)
        assert restored["pending"]["questionId"] == result["question"]["questionId"]
        assert not restored["turns"]
        option = next(
            item
            for item in result["question"]["options"]
            if item["choice"]["kind"] == kind and item["choice"]["id"] == value
        )
        result = submit_choice(
            store,
            service,
            ACTOR,
            conversation_id,
            ChoiceSubmit.model_validate(
                {
                    "questionId": result["question"]["questionId"],
                    "revision": result["question"]["revision"],
                    "optionIds": [option["id"]],
                }
            ),
        )
    return result


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
    second = _confirm_scope(store, population_query, row["id"], second)
    assert second.get("answerReady")
    assert second.get("textOrigin") == "ENGINE"
    assert second.get("population") is None
    engine_value = second["result"]["values"][0]["value"]
    assert "平均值" not in second["text"]
    assert engine_value in second["text"]
    assert second["evidence"][0]["lineage"]
    assert "confidence" not in second
    assert "置信度" not in second["text"]
    assert not second["assumptions"]


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
    second = _confirm_scope(store, population_query, row["id"], second)
    assert second.get("answerReady")
    saved = store.load(ACTOR, row["id"])
    assert saved["pending"] is None
    assert saved["turns"]
    assert "confidence" not in saved["turns"][0]["answer"]


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
    assert body["status"] == "NEEDS_INPUT"
    assert body["question"]["slot"] == "scope:taxYear"


def test_direct_turn_skips_model_for_named_metric(population_query: Any) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    assert try_direct_turn(population_query, ACTOR, "你好") is None
    assert try_direct_turn(population_query, ACTOR, "申报营业收入是什么") is None
    named = try_direct_turn(population_query, ACTOR, "申报营业收入")
    assert named is not None and named["status"] == "NEEDS_INPUT"
    vague = try_direct_turn(population_query, ACTOR, "收入多少")
    assert vague is not None and vague["status"] == "NEEDS_INPUT"
    assert any(item["choice"]["kind"] == "OTHER" for item in vague["question"]["options"])


def test_named_metric_asks_for_missing_context_without_scoring(population_query: Any) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    result = prepare_turn(population_query, ACTOR, "申报营业收入")
    assert result["status"] == "NEEDS_INPUT"
    assert result["question"]["slot"] in {"scope:taxYear", "aggregation"}
    assert not result.get("answerReady")
    assert "confidence" not in result
    assert not result.get("assumptions")
    assert not result["query"].get("groupBy")


def test_year_choices_only_advertise_non_null_observations_for_selected_metric(
    population_query: Any,
) -> None:
    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sample_declaration VALUES
                ('tenant-a','D4','C4',2025,'2025-01-01','2026-01-01',NULL,81,91.00,21)
                """
            )
        )

    revenue = prepare_turn(population_query, ACTOR, "申报营业收入")
    taxable = prepare_turn(population_query, ACTOR, "申报应纳税所得额")

    assert revenue["question"]["slot"] == "scope:taxYear"
    assert [
        option["choice"]["id"]
        for option in revenue["question"]["options"]
        if option["choice"]["kind"] == "DIMENSION_VALUE"
    ] == ["2024"]
    assert [
        option["choice"]["id"]
        for option in taxable["question"]["options"]
        if option["choice"]["kind"] == "DIMENSION_VALUE"
    ] == ["2024", "2025"]


def test_named_metric_revalidates_an_unconfirmed_inherited_scope(
    population_query: Any,
) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    stale = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="finance.declaredRevenue", aggregation="SUM"),),
        filters=FilterAtom(
            field="taxYear",
            op="EQ",
            value=TypedValue(value_type="INTEGER", value=2025),
        ),
    )

    result = prepare_turn(population_query, ACTOR, "我要看申报营业收入", stale)

    assert result["status"] == "NEEDS_INPUT"
    assert result["question"]["slot"] == "scope:taxYear"
    assert [
        option["choice"]["id"]
        for option in result["question"]["options"]
        if option["choice"]["kind"] == "DIMENSION_VALUE"
    ] == ["2024"]


def test_follow_up_can_replace_year_on_confirmed_query(population_query: Any) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    first = try_direct_turn(population_query, ACTOR, "2024年申报营业收入合计")
    assert first is not None and first["answerReady"]

    follow_up = try_direct_turn(
        population_query,
        ACTOR,
        "那查一下2026年",
        confirmed_query=first["query"],
    )

    assert follow_up is not None and follow_up["answerReady"]
    continued_query = SemanticQuery.model_validate(follow_up["query"])
    assert equality_value(continued_query.filters, "taxYear") == 2026
    assert follow_up["result"]["scope"]["reason"] == "EMPTY_POPULATION"
    assert "EMPTY_POPULATION" not in follow_up["text"]
    assert "没有匹配记录" in follow_up["text"]


def test_model_defaults_require_user_confirmation_but_confirmed_context_survives(
    population_query: Any,
) -> None:
    _load_declaration(population_query.provider._engines["sample_pg"])
    query = query_from_intent(
        TurnIntent.read("2024年申报营业收入合计", population_query.bundle), population_query.bundle
    ).model_dump(mode="json", by_alias=True)
    gateway = SemanticTools(population_query, ACTOR, "申报营业收入")
    with pytest.raises(ValueError, match="UNCONFIRMED_SCOPE"):
        gateway.call("prepare_semantic_query", {"query": query})
    without_year = {**query, "filters": None}
    waiting = gateway.call("prepare_semantic_query", {"query": without_year, "view": "table"})
    assert waiting["question"]["slot"] == "scope:taxYear"
    assert waiting["query"]["metrics"][0]["aggregation"] is None
    assert waiting["query_state"]["view"] == "table"
    resumed = SemanticTools(population_query, ACTOR, "那用表格看", confirmed_query=query)
    result = resumed.call("prepare_semantic_query", {"query": query, "view": "table"})
    assert result["answerReady"]
    assert resumed.answer is not None
    assert resumed.answer["views"][0]["view"] == "table"


def test_open_clarification_is_a_persisted_card_and_stale_other_is_rejected(
    population_query: Any,
) -> None:
    gateway = SemanticTools(population_query, ACTOR, "帮我看看经营情况")
    pending = gateway.call(
        "present_answer",
        {"kind": "clarification", "text": "希望了解哪方面的业务？", "evidenceIds": []},
    )
    assert pending["waiting"]
    store = ChatStore(population_query.provider._engines["sample_pg"])
    row = store.create(ACTOR, population_query.bundle.digest)
    store.save_pending(ACTOR, row, pending["question"], pending["query_state"], "帮我看看经营情况")
    submit = ChoiceSubmit(
        question_id=pending["question"]["questionId"],
        revision=2,
        option_ids=("opt_other_input",),
        other_text="2024年申报营业收入合计",
    )
    with pytest.raises(ChoiceError, match="VERSION_INVALID"):
        submit_choice(store, population_query, ACTOR, row["id"], submit)
    assert store.load(ACTOR, row["id"])["pending"]
    continued = submit_choice(
        store, population_query, ACTOR, row["id"], submit.model_copy(update={"revision": 1})
    )
    assert continued == {
        "status": "CONTINUE",
        "message": "帮我看看经营情况\n2024年申报营业收入合计",
    }


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


def test_capability_message_explains_link_boundary() -> None:
    from semaloom.app.chat.summary import capability_message

    text = capability_message("LINK_ANALYSIS_UNSUPPORTED")
    assert "ONE" in text or "一对一" in text or "基数为 ONE" in text
    assert "不支持" in text
    assert capability_message(None)


def _query_with_split_tax_return_table(service: Any) -> QueryService:
    """Compiled IR where the object mapping table differs from the metric mapping table."""
    mappings = []
    for item in service.bundle.mappings:
        if item.target == "finance.TaxReturn":
            physical = dict(item.physical)
            physical["table"] = "sample_taxpayer"
            item = item.model_copy(update={"physical": physical})
        mappings.append(item)
    bundle = service.bundle.model_copy(update={"mappings": tuple(mappings)})
    return QueryService(bundle, service.provider)


def _link_unsupported_query() -> SemanticQuery:
    return SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="finance.declaredRevenue", aggregation="SUM"),),
        filters=FilterAtom(
            field="taxYear",
            op="EQ",
            value=TypedValue(value_type="INTEGER", value=2024),
        ),
    )


def test_prepare_turn_groups_by_linked_company_name(population_query: Any) -> None:
    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
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
        conn.execute(
            text(
                """
                INSERT INTO sample_taxpayer VALUES
                ('tenant-a','C1','示例甲'),
                ('tenant-a','C2','示例乙')
                """
            )
        )
    result = prepare_turn(population_query, ACTOR, "2024年按企业名称合计申报营业收入")
    assert result.get("status") == "READY"
    assert result.get("answerReady") is True
    grains = {row.get("grain", {}).get("name") for row in result["result"]["values"]}
    assert "示例甲" in grains and "示例乙" in grains
    same = prepare_turn(population_query, ACTOR, "2024年申报营业收入合计")
    assert same.get("errorCode") != "LINK_ANALYSIS_UNSUPPORTED"


def test_prepare_turn_delivers_link_unsupported_as_engine_answer(population_query: Any) -> None:
    from semaloom.app.chat.summary import capability_message

    split = _query_with_split_tax_return_table(population_query)
    result = prepare_turn(split, ACTOR, "按企业合计申报营业收入", _link_unsupported_query())
    expected = capability_message("LINK_ANALYSIS_UNSUPPORTED")
    assert result["status"] == "UNSUPPORTED"
    assert result.get("answerReady") is True
    assert result.get("kind") == "unsupported"
    assert result.get("textOrigin") == "ENGINE"
    assert result["text"] == expected
    assert "不支持" in result["text"]
    assert "没有数据" not in result["text"]
    assert result["errorCode"] == "LINK_ANALYSIS_UNSUPPORTED"


def test_submit_choice_delivers_link_unsupported_as_engine_answer(population_query: Any) -> None:
    from semaloom.app.chat.summary import capability_message

    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sample_taxpayer (
                  tenant_id TEXT, id TEXT, name TEXT, tax_year INTEGER
                )
                """
            )
        )
        conn.execute(text("DELETE FROM sample_taxpayer"))
        conn.execute(text("INSERT INTO sample_taxpayer VALUES ('tenant-a','C1','示例企业',2024)"))
    split = _query_with_split_tax_return_table(population_query)
    store = ChatStore(engine)
    row = store.create(ACTOR, split.bundle.digest)
    first = prepare_turn(split, ACTOR, "收入多少？")
    assert first["status"] == "NEEDS_INPUT"
    store.save_pending(ACTOR, row, first["question"], {"query": first["query"]}, "收入多少？")
    metric_opt = next(
        item["id"] for item in first["question"]["options"] if item["choice"]["kind"] == "METRIC"
    )
    done = submit_choice(
        store,
        split,
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
    done = _confirm_scope(store, split, row["id"], done)
    expected = capability_message("LINK_ANALYSIS_UNSUPPORTED")
    assert done.get("answerReady") is True
    assert done["status"] == "UNSUPPORTED"
    assert done.get("kind") == "unsupported"
    assert done.get("textOrigin") == "ENGINE"
    assert done["text"] == expected
    assert "不支持" in done["text"]
    assert "没有数据" not in done["text"]
    assert done["errorCode"] == "LINK_ANALYSIS_UNSUPPORTED"
    assert done["evidence"][0]["result"]["errorCode"] == "LINK_ANALYSIS_UNSUPPORTED"

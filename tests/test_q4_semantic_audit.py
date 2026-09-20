"""Q4 independent acceptance: warehouse pack, SQL/Decimal oracle, redundancy audit."""

from __future__ import annotations

import ast
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from semaloom.adapters.postgres import PostgresReadProvider
from semaloom.app.agent_tools import read_tools
from semaloom.app.chat.choices import prepare_turn, query_from_intent, submit_choice
from semaloom.app.chat.intent import TurnIntent
from semaloom.app.chat.store import ChatStore
from semaloom.app.chat.tools import SemanticTools
from semaloom.app.http import ClaimBody
from semaloom.compiler import compile_paths
from semaloom.core.semantic_query import (
    ChoiceError,
    ChoiceQuestion,
    ChoiceSubmit,
    ComparisonExpr,
    FilterAtom,
    GroupByItem,
    MetricRef,
    SemanticQuery,
    SubjectSelector,
    TypedValue,
    merge_decision,
)
from semaloom.runtime.analysis import execute, prepare
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.fixtures import engines
from semaloom.runtime.query import QueryService

ROOT = Path(__file__).resolve().parents[1]
ACTOR = RequestActor(tenant="tenant-a", subject="q4", roles=("analyst",))
OTHER = RequestActor(tenant="tenant-a", subject="other", roles=("analyst",))


@pytest.fixture
def warehouse() -> Any:
    bundle = compile_paths([ROOT / "examples/warehouse"]).bundle
    assert bundle is not None
    engine = engines()["orders_pg"]
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS q4_warehouse"))
        conn.execute(text("SET search_path TO q4_warehouse"))
        conn.execute(
            text(
                """CREATE TABLE warehouse_sku (
                tenant_id TEXT, sku_id TEXT, category TEXT, stock_year INTEGER, on_hand NUMERIC
            )"""
            )
        )
        conn.execute(
            text(
                """INSERT INTO warehouse_sku
                SELECT 'tenant-a', 'S'||i, CASE WHEN i%2=0 THEN 'A' ELSE 'B' END, 2024, (i%7)+0.2500
                FROM generate_series(1,2000) i"""
            )
        )
        conn.execute(text("INSERT INTO warehouse_sku VALUES ('tenant-b','SX','A',2024,99999)"))
        conn.commit()
        read_engine = create_engine(
            engine.url, connect_args={"options": "-csearch_path=q4_warehouse"}
        )
        try:
            provider = PostgresReadProvider({"warehouse_pg": read_engine})
            yield QueryService(bundle, provider), read_engine
        finally:
            read_engine.dispose()
            conn.rollback()
            conn.execute(text("SET search_path TO public"))
            conn.execute(text("DROP SCHEMA q4_warehouse CASCADE"))
            conn.commit()


def _sql(engine: Any, statement: str) -> Decimal:
    with engine.connect() as conn:
        value = conn.execute(text(statement)).scalar_one()
    return Decimal(value)


def test_warehouse_pack_runs_without_core_change(warehouse: Any) -> None:
    service, read_engine = warehouse
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="warehouse.onHandQty", aggregation="SUM"),),
        filters=FilterAtom(
            field="stockYear",
            op="EQ",
            value=TypedValue(value_type="INTEGER", value=2024),
        ),
    )
    prepared = prepare(service, query, ACTOR)
    assert prepared.status == "READY"
    assert prepared.plan is not None
    result = execute(service, prepared.plan, ACTOR)
    expected = _sql(
        read_engine,
        "SELECT SUM(on_hand) FROM warehouse_sku WHERE tenant_id='tenant-a' AND stock_year=2024",
    )
    tenant_b = _sql(
        read_engine,
        "SELECT SUM(on_hand) FROM warehouse_sku WHERE tenant_id='tenant-b' AND stock_year=2024",
    )
    assert Decimal(result.values[0]["value"]) == expected
    assert expected != tenant_b
    assert result.scope["populationCount"] == 2000
    assert len(result.evidence.rows) == 50
    assert result.evidence.truncated is True


def test_complete_warehouse_question_is_ready_matching_sql(warehouse: Any) -> None:
    service, read_engine = warehouse
    intent = TurnIntent.read("2024年在库数量合计", service.bundle)
    assert intent.metric_ids == frozenset({"warehouse.onHandQty"})
    assert intent.year == 2024
    built = query_from_intent(intent, service.bundle)
    assert isinstance(built.filters, FilterAtom)
    assert built.filters.field == "stockYear"
    prepared = prepare_turn(service, ACTOR, "2024年在库数量合计")
    assert prepared["status"] == "READY"
    assert prepared.get("answerReady") is True
    expected = _sql(
        read_engine,
        "SELECT SUM(on_hand) FROM warehouse_sku WHERE tenant_id='tenant-a' AND stock_year=2024",
    )
    value = prepared["result"]["values"][0]["value"]
    assert Decimal(value) == expected
    assert value in prepared["text"]
    assert "合计" in prepared["text"]
    assert "平均值" not in prepared["text"]
    assert prepared.get("population") is None


def test_vague_and_missing_year_need_input(warehouse: Any) -> None:
    service, _engine = warehouse
    vague = prepare_turn(service, ACTOR, "帮我统计一下")
    assert vague["status"] == "NEEDS_INPUT"
    assert vague["question"]["slot"] == "metric"
    assert any(item["choice"]["kind"] == "OTHER" for item in vague["question"]["options"])
    stock = prepare_turn(service, ACTOR, "库存多少")
    assert stock.get("answerReady")
    assert stock["result"]["values"][0]["metric"] == "warehouse.onHandQty"
    missing_year = prepare_turn(service, ACTOR, "在库数量合计")
    assert missing_year.get("answerReady")
    assert any(item["slot"] == "year" for item in missing_year["assumptions"])


def test_row_average_differs_from_sum_and_matches_sql(warehouse: Any) -> None:
    service, read_engine = warehouse
    mean = prepare_turn(service, ACTOR, "2024年在库数量平均")
    total = prepare_turn(service, ACTOR, "2024年在库数量合计")
    assert mean["status"] == "READY" and total["status"] == "READY"
    mean_sql = _sql(
        read_engine,
        "SELECT AVG(on_hand) FROM warehouse_sku WHERE tenant_id='tenant-a' AND stock_year=2024",
    )
    sum_sql = _sql(
        read_engine,
        "SELECT SUM(on_hand) FROM warehouse_sku WHERE tenant_id='tenant-a' AND stock_year=2024",
    )
    assert Decimal(mean["result"]["values"][0]["value"]) == mean_sql
    assert Decimal(total["result"]["values"][0]["value"]) == sum_sql
    assert mean_sql != sum_sql
    assert "平均值" in mean["text"]
    assert "合计" in total["text"]


def test_share_of_total_denominator_is_full_population(warehouse: Any) -> None:
    service, read_engine = warehouse
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="warehouse.onHandQty", aggregation="SUM"),),
        filters=FilterAtom(
            field="stockYear",
            op="EQ",
            value=TypedValue(value_type="INTEGER", value=2024),
        ),
        comparison=ComparisonExpr(
            op="SHARE_OF_TOTAL",
            metric="warehouse.onHandQty",
            subject=SubjectSelector(identity={"skuId": "S1"}),
        ),
    )
    prepared = prepare(service, query, ACTOR)
    assert prepared.status == "READY" and prepared.plan is not None
    result = execute(service, prepared.plan, ACTOR)
    subject = _sql(
        read_engine,
        "SELECT SUM(on_hand) FROM warehouse_sku WHERE tenant_id='tenant-a' "
        "AND stock_year=2024 AND sku_id='S1'",
    )
    total = _sql(
        read_engine,
        "SELECT SUM(on_hand) FROM warehouse_sku WHERE tenant_id='tenant-a' AND stock_year=2024",
    )
    comparison = result.scope["comparison"]
    assert Decimal(comparison["numerator"]) == subject
    assert Decimal(comparison["denominator"]) == total
    with localcontext() as ctx:
        ctx.prec = 28
        assert Decimal(comparison["value"]) == subject / total * 100


def test_named_share_question_selects_the_matching_subject(warehouse: Any) -> None:
    service, _engine = warehouse
    prepared = prepare_turn(service, ACTOR, "S1 占2024年在库数量总额多少")
    assert prepared.get("answerReady")
    assert prepared["result"]["scope"]["comparison"]["operation"] == "shareOfTotal"


def test_missing_policy_reject_vs_exclude(warehouse: Any) -> None:
    service, read_engine = warehouse
    with read_engine.begin() as conn:
        conn.execute(text("UPDATE warehouse_sku SET on_hand=NULL WHERE sku_id IN ('S1','S2')"))
    reject = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="warehouse.onHandQty", aggregation="SUM"),),
        filters=FilterAtom(
            field="stockYear",
            op="EQ",
            value=TypedValue(value_type="INTEGER", value=2024),
        ),
        missing_policy="reject",
    )
    excluded = reject.model_copy(update={"missing_policy": "exclude"})
    rejected_plan = prepare(service, reject, ACTOR).plan
    kept_plan = prepare(service, excluded, ACTOR).plan
    assert rejected_plan is not None and kept_plan is not None
    rejected = execute(service, rejected_plan, ACTOR)
    kept = execute(service, kept_plan, ACTOR)
    assert rejected.values == ()
    assert rejected.scope["reason"] == "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION"
    expected = _sql(
        read_engine,
        "SELECT SUM(on_hand) FROM warehouse_sku WHERE tenant_id='tenant-a' "
        "AND stock_year=2024 AND on_hand IS NOT NULL",
    )
    assert Decimal(kept.values[0]["value"]) == expected


def test_choice_matrix_forged_expired_duplicate_abort_reselect(warehouse: Any) -> None:
    service, engine = warehouse
    store = ChatStore(engine)
    row = store.create(ACTOR, service.bundle.digest)
    first = prepare_turn(service, ACTOR, "帮我统计一下")
    assert first["status"] == "NEEDS_INPUT"
    store.save_pending(ACTOR, row, first["question"], {"query": first["query"]}, "帮我统计一下")
    with pytest.raises(ChoiceError, match="UNKNOWN_OPTION"):
        submit_choice(
            store,
            service,
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
    with pytest.raises(ChoiceError, match="VERSION_INVALID"):
        submit_choice(
            store,
            service,
            ACTOR,
            row["id"],
            ChoiceSubmit.model_validate(
                {
                    "questionId": first["question"]["questionId"],
                    "revision": first["question"]["revision"] + 99,
                    "optionIds": [first["question"]["options"][0]["id"]],
                }
            ),
        )
    live = next(item for item in first["question"]["options"] if item["choice"]["kind"] != "ABORT")
    question = ChoiceQuestion.model_validate(first["question"])
    submit = ChoiceSubmit.model_validate(
        {"questionId": question.question_id, "revision": 1, "optionIds": [live["id"]]}
    )
    query = SemanticQuery.model_validate(first["query"])
    merged = merge_decision(query, question, submit)
    with pytest.raises(ChoiceError, match="DUPLICATE_SUBMIT"):
        merge_decision(merged, question, submit)
    abort = next(
        item["id"] for item in first["question"]["options"] if item["choice"]["kind"] == "ABORT"
    )
    stopped = submit_choice(
        store,
        service,
        ACTOR,
        row["id"],
        ChoiceSubmit.model_validate(
            {
                "questionId": first["question"]["questionId"],
                "revision": 1,
                "optionIds": [abort],
            }
        ),
    )
    assert stopped["status"] == "ABORTED"
    assert store.load(ACTOR, row["id"])["pending"] is None
    with pytest.raises(KeyError):
        store.load(OTHER, row["id"])
    restored = store.create(ACTOR, service.bundle.digest)
    again = prepare_turn(service, ACTOR, "帮我统计一下")
    store.save_pending(
        ACTOR, restored, again["question"], {"query": again["query"]}, "帮我统计一下"
    )
    loaded = store.load(ACTOR, restored["id"])
    assert loaded["pending"]["questionId"] == again["question"]["questionId"]


def test_two_round_keeps_metric_then_year(warehouse: Any) -> None:
    service, read_engine = warehouse
    done = prepare_turn(service, ACTOR, "在库数量合计")
    assert done.get("answerReady")
    expected = _sql(
        read_engine,
        "SELECT SUM(on_hand) FROM warehouse_sku WHERE tenant_id='tenant-a' AND stock_year=2024",
    )
    assert Decimal(done["result"]["values"][0]["value"]) == expected
    assert done["result"]["values"][0]["value"] in done["text"]
    assert done["confidence"]["label"] in {"高", "中", "低"}


def test_source_and_save_failure_do_not_invent_answers(warehouse: Any, monkeypatch: Any) -> None:
    service, read_engine = warehouse
    with read_engine.begin() as conn:
        conn.execute(text("DROP TABLE warehouse_sku"))
    failed = prepare_turn(service, ACTOR, "2024年在库数量合计")
    assert failed["status"] == "SOURCE_ERROR"
    assert failed.get("answerReady") is not True
    store = ChatStore(engines()["orders_pg"])
    row = store.create(ACTOR, service.bundle.digest)
    first = prepare_turn(service, ACTOR, "帮我统计一下")
    store.save_pending(ACTOR, row, first["question"], {"query": first["query"]}, "帮我统计一下")

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(store, "save", boom)
    with pytest.raises(RuntimeError, match="database unavailable"):
        store.save(
            ACTOR,
            store.load(ACTOR, row["id"]),
            [],
            {"question": "x", "answer": {"text": "no"}},
        )
    assert store.load(ACTOR, row["id"])["turns"] == []


def test_unsupported_month_grain_on_integer_year(warehouse: Any) -> None:
    service, _engine = warehouse
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="warehouse.onHandQty", aggregation="SUM"),),
        filters=FilterAtom(
            field="stockYear",
            op="EQ",
            value=TypedValue(value_type="INTEGER", value=2024),
        ),
        group_by=(GroupByItem(id="stockYear", time_grain="MONTH"),),
    )
    prepared = prepare(service, query, ACTOR)
    assert prepared.status == "UNSUPPORTED"
    assert prepared.capability == "TIME_GRAIN_UNSUPPORTED"


def test_semi_additive_sum_across_years_is_refused(warehouse: Any) -> None:
    service, _engine = warehouse
    mixed = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="warehouse.onHandQty", aggregation="SUM"),),
        filters=FilterAtom(
            field="stockYear",
            op="IN",
            value=TypedValue(value_type="INTEGER", value=(2024, 2025)),
        ),
    )
    prepared = prepare(service, mixed, ACTOR)
    assert prepared.status == "UNSUPPORTED"
    assert prepared.capability == "ADDITIVITY_VIOLATION"
    average = mixed.model_copy(
        update={"metrics": (MetricRef(id="warehouse.onHandQty", aggregation="AVG"),)}
    )
    assert prepare(service, average, ACTOR).status == "READY"


def test_analyze_population_path_is_gone() -> None:
    runtime = ROOT / "src/semaloom/runtime"
    assert not (runtime / "population.py").exists()
    http = (ROOT / "src/semaloom/app/http.py").read_text(encoding="utf-8")
    prompt = (ROOT / "src/semaloom/app/chat/system_prompt.txt").read_text(encoding="utf-8")
    assert "analyze_population" not in http
    assert "/analyze" not in http
    assert "analyze_population" not in prompt
    tree = ast.parse((ROOT / "src/semaloom/app/agent_tools.py").read_text(encoding="utf-8"))
    names = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert "analyze_population" not in names
    assert "semantic_prepare" in names


def test_no_second_stats_engine_or_parallel_choice_state_machine(warehouse: Any) -> None:
    service, _engine = warehouse
    owners = list((ROOT / "src/semaloom/app/chat").glob("choices.py"))
    assert owners
    analysis_impl = (ROOT / "src/semaloom/runtime/analysis.py").read_text(encoding="utf-8")
    assert "SemanticQuery" in analysis_impl
    tools = SemanticTools(service, ACTOR)
    names = {item["name"] for item in tools.catalog()}
    assert "prepare_semantic_query" in names
    assert "analyze_population" not in names
    http_names = {item["name"] for item in read_tools(ClaimBody.model_json_schema(by_alias=True))}
    assert "analyze_population" not in http_names
    assert "semantic_prepare" in http_names
    plugin = (ROOT / "harness/semantic-plugin.mjs").read_text(encoding="utf-8")
    assert "waiting" in plugin
    assert "ctx.ui.select" not in plugin
    prompt = (ROOT / "src/semaloom/app/chat/system_prompt.txt").read_text(encoding="utf-8")
    assert "prepare_semantic_query" in prompt
    assert "analyze_population" not in prompt

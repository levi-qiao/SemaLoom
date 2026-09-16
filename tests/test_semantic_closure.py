"""Principal adversarial audit through the public prepare/execute and chat gateway."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from semaloom.app.chat.choices import prepare_turn, submit_choice
from semaloom.app.chat.store import ChatStore
from semaloom.app.chat.tools import SemanticTools
from semaloom.core.semantic_query import (
    AnalysisError,
    ChoiceSubmit,
    SemanticQuery,
    TypedValue,
)
from semaloom.runtime.analysis import execute, prepare
from tests.test_business_analysis import ACTOR, financial_query  # noqa: F401
from tests.test_chat_choices import _load_declaration
from tests.test_semantic_query import _query, population_query  # noqa: F401


def run(service: Any, query: SemanticQuery) -> Any:
    prepared = prepare(service, query, ACTOR)
    assert prepared.status == "READY", prepared
    return execute(service, prepared.plan, ACTOR)


def test_all_metrics_and_groups_are_answered(population_query: Any) -> None:  # noqa: F811
    query = _query(
        metrics=[
            {"id": "finance.review.declared_profit", "aggregation": "SUM"},
            {"id": "finance.review.net_profit", "aggregation": "AVG"},
        ],
        groupBy=[{"id": "companyId"}],
    )
    result = run(population_query, query)
    assert len(result.values) == 6
    from semaloom.app.chat.summary import semantic_summary

    narrative = semantic_summary(population_query.bundle, query, result)
    for value in result.values:
        assert value["value"] in narrative
        assert value["grain"]["companyId"] in narrative
    assert {value["metric"] for value in result.values} == {ref.id for ref in query.metrics}
    assert result.scope["consistency"] == "SOURCE_REPEATABLE_READ"


def test_plan_cannot_change_values_or_release(population_query: Any) -> None:  # noqa: F811
    plan = prepare(population_query, _query(), ACTOR).plan
    assert plan
    forged = plan.model_copy(
        update={
            "query": _query(
                filters={
                    "field": "taxYear",
                    "op": "EQ",
                    "value": {"valueType": "INTEGER", "value": 2025},
                }
            )
        }
    )
    with pytest.raises(AnalysisError, match="PLAN_INVALID"):
        execute(population_query, forged, ACTOR)
    with pytest.raises(AnalysisError, match="VERSION_INVALID"):
        execute(population_query, plan.model_copy(update={"release_digest": "other"}), ACTOR)


def test_ambiguous_alias_cannot_be_overridden_by_model(population_query: Any) -> None:  # noqa: F811
    gateway = SemanticTools(population_query, ACTOR, "2024年收入平均值")
    result = gateway.call(
        "prepare_semantic_query",
        {"question": "已经明确了口径", "query": _query().model_dump(mode="json", by_alias=True)},
    )
    assert result["status"] == "NEEDS_INPUT"
    assert result["question"]["slot"] == "metric"
    assert gateway.answer is None


@pytest.mark.parametrize(
    "message, changes, code",
    [
        ("2024年选定申报利润总额平均值", {}, "AGGREGATION_DOES_NOT_MATCH_USER"),
        ("2025年选定申报利润总额合计", {}, "REQUEST_YEAR_DOES_NOT_MATCH_USER"),
        (
            "2024年选定申报利润总额合计,缺失不要排除",
            {"missingPolicy": "exclude"},
            "MISSING_EXCLUSION_NOT_AUTHORIZED",
        ),
        ("2024年选定申报利润总额占总额比例", {}, "COMPARISON_REQUIRED_BY_USER"),
    ],
)
def test_model_proposal_respects_original_message(
    population_query: Any,  # noqa: F811
    message: str,
    changes: dict[str, Any],
    code: str,
) -> None:
    gateway = SemanticTools(population_query, ACTOR, message)
    with pytest.raises(AnalysisError, match=code):
        gateway.call(
            "prepare_semantic_query",
            {
                "question": "2024年选定申报利润总额合计",
                "query": _query(**changes).model_dump(mode="json", by_alias=True),
            },
        )
    assert gateway.answer is None


def test_contradiction_is_a_choice_not_empty_population(population_query: Any) -> None:  # noqa: F811
    query = _query(
        filters={
            "kind": "AND",
            "args": [
                {"field": "taxYear", "op": "EQ", "value": {"valueType": "INTEGER", "value": year}}
                for year in (2024, 2025)
            ],
        }
    )
    prepared = prepare(population_query, query, ACTOR)
    assert prepared.status == "NEEDS_INPUT"
    assert prepared.question.slot == "filter"


def test_multiyear_does_not_create_false_duplicate_unit(population_query: Any) -> None:  # noqa: F811
    engine = population_query.provider._engines["sample_pg"]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sample_financial_review"
                "(tenant_id,id,company_id,tax_year,declared_profit) "
                "VALUES ('tenant-a','Y2','C1',2025,200)"
            )
        )
    query = _query(
        filters={
            "field": "taxYear",
            "op": "IN",
            "value": {"valueType": "INTEGER", "value": [2024, 2025]},
        },
        groupBy=[{"id": "taxYear"}],
    )
    result = run(population_query, query)
    assert {row["grain"]["taxYear"]: Decimal(row["value"]) for row in result.values} == {
        2024: Decimal("300.03"),
        2025: Decimal(200),
    }


def test_null_subject_is_unknown_not_absent(population_query: Any) -> None:  # noqa: F811
    query = _query(
        metrics=[{"id": "finance.review.audit_profit", "aggregation": "SUM"}],
        missingPolicy="exclude",
        comparison={
            "op": "SHARE_OF_TOTAL",
            "metric": "finance.review.audit_profit",
            "subject": {"identity": {"caseId": "C3"}},
        },
    )
    result = run(population_query, query)
    assert result.scope["comparison"]["reason"] == "SUBJECT_VALUE_MISSING"
    assert result.scope["comparison"]["value"] is None


def test_same_name_subject_requires_choice(population_query: Any) -> None:  # noqa: F811
    query = _query(
        comparison={
            "op": "SHARE_OF_TOTAL",
            "metric": "finance.review.declared_profit",
            "subject": {"filters": {"companyName": "示例企业"}},
        }
    )
    result = prepare(population_query, query, ACTOR)
    assert result.status == "NEEDS_INPUT"
    assert {
        option.choice.id for option in result.question.options if option.choice.kind == "SUBJECT"
    } == {"C1", "C2"}


def test_save_failure_keeps_pending_choice_retryable(
    population_query: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    engine = population_query.provider._engines["sample_pg"]
    _load_declaration(engine)
    store = ChatStore(engine)
    row = store.create(ACTOR, population_query.bundle.digest)
    pending = prepare_turn(population_query, ACTOR, "收入多少？")
    assert pending["status"] == "NEEDS_INPUT"
    store.save_pending(ACTOR, row, pending["question"], {"query": pending["query"]}, "收入多少？")
    question = pending["question"]
    metric_opt = next(
        item["id"] for item in question["options"] if item["choice"]["kind"] == "METRIC"
    )
    submit = ChoiceSubmit(
        question_id=question["questionId"],
        revision=question["revision"],
        option_ids=(metric_opt,),
    )
    original = store.save

    def fail(*args: Any) -> None:
        raise ValueError("storage offline")

    monkeypatch.setattr(store, "save", fail)
    with pytest.raises(ValueError, match="storage offline"):
        submit_choice(store, population_query, ACTOR, row["id"], submit)
    assert store.load(ACTOR, row["id"])["pending"] == question
    monkeypatch.setattr(store, "save", original)
    assert submit_choice(store, population_query, ACTOR, row["id"], submit)["answerReady"]
    assert len(store.load(ACTOR, row["id"])["turns"]) == 1


@pytest.mark.parametrize(
    "value_type,value",
    [
        ("DECIMAL", "NaN"),
        ("DECIMAL", "Infinity"),
        ("INTEGER", "1.2"),
        ("INTEGER", True),
        ("BOOLEAN", "yes"),
    ],
)
def test_typed_filters_reject_invalid_values(value_type: Any, value: Any) -> None:
    with pytest.raises(ValidationError):
        TypedValue(value_type=value_type, value=value)


def test_grouped_average_orders_by_average_not_total(population_query: Any) -> None:  # noqa: F811
    engine = population_query.provider._engines["sample_pg"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET declared_profit=150 WHERE id='C3'"))
    result = run(
        population_query,
        _query(
            metrics=[{"id": "finance.review.declared_profit", "aggregation": "AVG"}],
            groupBy=[{"id": "companyName"}],
            orderBy=[{"field": "finance.review.declared_profit", "direction": "DESC"}],
        ),
    )
    assert [Decimal(value["value"]) for value in result.values] == [
        Decimal(150),
        Decimal("100.015"),
    ]


def test_model_cannot_replace_choices_with_prose(population_query: Any) -> None:  # noqa: F811
    gateway = SemanticTools(population_query, ACTOR, "收入多少")
    result = gateway.call(
        "present_answer", {"kind": "clarification", "text": "请说年份", "evidenceIds": []}
    )
    assert result["waiting"]
    assert gateway.pending["question"]["slot"] == "metric"
    assert gateway.answer is None


def test_authoritative_prose_cannot_invent_rule_truth(population_query: Any) -> None:  # noqa: F811
    gateway = SemanticTools(population_query, ACTOR)
    gateway.evidence["e1"] = {
        "tool": "evaluate_claim",
        "result": {
            "claim": {"claimId": "example.check", "truth": "UNKNOWN", "reasonCodes": ["MISSING"]}
        },
    }
    gateway.call(
        "present_answer",
        {"kind": "answer", "text": "所有审计全部通过,绝对合规", "evidenceIds": ["e1"]},
    )
    assert "UNKNOWN" in gateway.answer["text"]
    assert "绝对合规" not in gateway.answer["text"]
    assert gateway.answer["textOrigin"] == "ENGINE"


def test_runtime_has_no_sql_or_domain_imports() -> None:
    import ast
    from pathlib import Path

    source = Path("src/semaloom/runtime/analysis.py").read_text()
    imports = [
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    ]
    assert not any(
        name.startswith(("semaloom.adapters", "sqlalchemy", "sqlglot", "examples"))
        for name in imports
    )
    assert not any(name in source for name in ('"taxYear"', '"stockYear"', '"jurisdiction"'))


def test_renamed_business_year_needs_no_core_special_case(population_query: Any) -> None:  # noqa: F811
    bundle = population_query.bundle
    metrics = tuple(
        metric.model_copy(
            update={
                "population": metric.population.model_copy(update={"year_property": "fiscalCycle"})
            }
        )
        if metric.population
        else metric
        for metric in bundle.metrics
    )
    objects = tuple(
        obj.model_copy(
            update={
                "properties": tuple(
                    prop.model_copy(update={"id": "fiscalCycle"}) if prop.id == "taxYear" else prop
                    for prop in obj.properties
                )
            }
        )
        for obj in bundle.object_types
    )
    mappings = []
    for mapping in bundle.mappings:
        physical = dict(mapping.physical)
        for name in ("grainColumns", "propertyColumns"):
            if isinstance(physical.get(name), dict):
                physical[name] = {
                    "fiscalCycle" if k == "taxYear" else k: v for k, v in physical[name].items()
                }
        mappings.append(mapping.model_copy(update={"physical": physical}))
    population_query.bundle = bundle.model_copy(
        update={"metrics": metrics, "object_types": objects, "mappings": tuple(mappings)}
    )
    result = prepare_turn(population_query, ACTOR, "2024年选定申报利润总额合计")
    assert result["answerReady"]
    assert "fiscalCycle" in result["text"]
    assert Decimal(result["result"]["values"][0]["value"]) == Decimal("300.03")

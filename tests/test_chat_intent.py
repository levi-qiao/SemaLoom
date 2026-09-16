"""Replay audit intent failures at the real gateway, without an LLM or database."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from ops.ai.evaluate_chat import verdict

from semaloom.app.chat.tools import SemanticTools
from semaloom.compiler import compile_paths
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService


@pytest.fixture
def gateway() -> SemanticTools:
    bundle = compile_paths(
        [Path(__file__).resolve().parents[1] / "examples/financial-review"]
    ).bundle
    assert bundle
    return SemanticTools(
        QueryService(bundle, None),
        RequestActor(tenant="tenant-a", subject="test", roles=("analyst",)),
    )


def test_comparison_question_cannot_submit_mean_only_evidence(gateway: SemanticTools) -> None:
    gateway.user_message = "2025年选定申报利润总额, 某企业比平均值高百分之多少?"
    gateway.evidence["e1"] = {
        "id": "e1",
        "tool": "analyze_population",
        "result": {
            "metric": "finance.review.declared_profit",
            "operation": "mean",
            "year": 2025,
            "value": "125",
            "comparison": None,
            "releaseDigest": gateway.query.bundle.digest,
        },
    }
    with pytest.raises(ValueError, match="COMPARISON_EVIDENCE_REQUIRED"):
        gateway.call(
            "present_answer", {"kind": "answer", "text": "比平均值高12%", "evidenceIds": ["e1"]}
        )


def test_user_missing_prohibition_blocks_exclude_before_execution(
    gateway: SemanticTools, monkeypatch: Any
) -> None:
    gateway.user_message = "2025年抽取审计利润平均值, 缺失不要排除、不要当零。"
    with pytest.raises(ValueError, match="MISSING_EXCLUSION_NOT_AUTHORIZED"):
        gateway.call(
            "prepare_semantic_query",
            {
                "query": {
                    "apiVersion": "semaloom/v0.1",
                    "metrics": [{"id": "finance.review.audit_profit", "aggregation": "AVG"}],
                    "missingPolicy": "exclude",
                }
            },
        )
    assert gateway.answer is None


def test_evaluator_rejects_conflicting_population_evidence() -> None:
    oracle = {"metric": "x", "missingPolicy": "reject", "value": None}
    answer = {
        "kind": "answer",
        "evidence": [
            {"tool": "analyze_population", "result": oracle},
            {
                "tool": "analyze_population",
                "result": {**oracle, "missingPolicy": "exclude", "value": "93.33"},
            },
        ],
    }
    assert verdict(answer, oracle, "answer") != "PASS"


@pytest.mark.parametrize(
    "message, allowed",
    [
        ("缺失不要排除", False),
        ("请不要排除缺失", False),
        ("我明确同意排除缺失观测后再计算", True),
        ("do not exclude missing", False),
        ("exclude missing", True),
    ],
)
def test_missing_consent_is_conservative(
    gateway: SemanticTools, message: str, allowed: bool
) -> None:
    gateway.user_message = message
    assert gateway.intent.exclude_allowed is allowed


def test_ontology_aliases_control_ambiguity_without_enterprise_branches(
    gateway: SemanticTools,
) -> None:
    from semaloom.app.chat.intent import TurnIntent

    bundle = gateway.query.bundle
    metrics = tuple(m.model_copy(update={"aliases": ("工作量",)}) for m in bundle.metrics[:2])
    custom = bundle.model_copy(update={"metrics": metrics})
    intent = TurnIntent.read("2025年工作量均值", custom)
    assert set(intent.candidates) == {m.id for m in metrics}
    precise = TurnIntent.read("2025年" + metrics[0].label + "均值", custom)
    assert not precise.candidates and precise.metric_ids == {metrics[0].id}
    assert not TurnIntent.read("收入", custom).candidates


def test_ambiguous_ontology_word_blocks_all_data_tools(gateway: SemanticTools) -> None:
    gateway.user_message = "这批样本2025年的收入平均多少?"
    assert len(gateway.intent.candidates) == 2
    for name in ("find_objects", "semantic_query", "evaluate_claim", "analyze_population"):
        with pytest.raises(ValueError, match="CLARIFICATION_REQUIRED"):
            gateway.call(name, {})


def test_mean_question_cannot_be_answered_with_sum(gateway: SemanticTools) -> None:
    gateway.user_message = "2025年选定申报利润总额平均值"
    with pytest.raises(ValueError, match="AGGREGATION_DOES_NOT_MATCH_USER"):
        gateway.call(
            "prepare_semantic_query",
            {
                "query": {
                    "apiVersion": "semaloom/v0.1",
                    "metrics": [{"id": "finance.review.declared_profit", "aggregation": "SUM"}],
                }
            },
        )


def test_model_schema_exposes_nested_comparison_fields_without_weakening_python(
    gateway: SemanticTools,
) -> None:
    import json

    from pydantic import ValidationError

    from semaloom.app.agent_tools import read_tools
    from semaloom.app.chat.schema import model_schema
    from semaloom.app.http import ClaimBody
    from semaloom.core.results import PopulationRequest

    names = {item["name"] for item in gateway.catalog()}
    assert "prepare_semantic_query" in names
    assert "analyze_population" not in names
    raw = next(
        item
        for item in read_tools(ClaimBody.model_json_schema(by_alias=True))
        if item["name"] == "analyze_population"
    )
    schema = model_schema(raw["inputSchema"])
    assert "$ref" not in json.dumps(schema)
    comparison = schema["properties"]["comparison"]
    assert comparison["type"] == "object"
    assert comparison["properties"]["operation"]["enum"] == [
        "shareOfTotal",
        "percentAboveMean",
        "outperforms",
    ]
    assert comparison["properties"]["filters"]["type"] == "object"
    with pytest.raises(ValidationError):
        PopulationRequest.model_validate(
            {"metric": "m", "year": 2025, "comparison": '{"operation":"shareOfTotal"}'}
        )

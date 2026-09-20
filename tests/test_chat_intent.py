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
        "tool": "prepare_semantic_query",
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
    oracle = {
        "values": [{"value": None}],
        "scope": {"missingPolicy": "reject"},
        "releaseDigest": "d1",
    }
    answer = {
        "kind": "answer",
        "evidence": [
            {"tool": "prepare_semantic_query", "result": oracle},
            {
                "tool": "prepare_semantic_query",
                "result": {
                    "values": [{"value": "93.33"}],
                    "scope": {"missingPolicy": "exclude"},
                    "releaseDigest": "d1",
                },
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


def test_review_aliases_distinguish_profit_and_share_short_names(gateway: SemanticTools) -> None:
    from semaloom.app.chat.intent import TurnIntent

    bundle = gateway.query.bundle
    profit = TurnIntent.read("2025年利润平均值", bundle)
    assert profit.metric_ids == frozenset()
    assert set(profit.candidates) == {
        "finance.review.declared_profit",
        "finance.review.audit_profit",
    }
    net = TurnIntent.read("2025年净利润平均值", bundle)
    assert net.metric_ids == frozenset({"finance.review.net_profit"})
    assert not net.candidates
    assets = TurnIntent.read("2025年资产合计", bundle)
    assert assets.metric_ids == frozenset({"finance.review.assets"})
    ratio = TurnIntent.read("2025年资产负债率最大值", bundle)
    assert ratio.metric_ids == frozenset({"finance.review.debtRatio"})
    assert ratio.operation == "max"


def test_share_phrasing_allows_year_and_metric_between_zhan_and_total(
    gateway: SemanticTools,
) -> None:
    from semaloom.app.chat.intent import TurnIntent

    intent = TurnIntent.read("样本企业 05 占2025年选定申报利润总额多少", gateway.query.bundle)
    assert intent.comparison == "shareOfTotal"
    assert intent.metric_ids == frozenset({"finance.review.declared_profit"})
    assert intent.year == 2025


def test_claim_aliases_are_read_from_ontology(gateway: SemanticTools) -> None:
    from semaloom.app.chat.intent import TurnIntent

    intent = TurnIntent.read("资产等于负债加权益吗", gateway.query.bundle)
    assert intent.claim_ids == frozenset({"finance.review.balanceBalances"})


def test_ambiguous_ontology_word_blocks_all_data_tools(gateway: SemanticTools) -> None:
    gateway.user_message = "这批样本2025年的收入平均多少?"
    assert len(gateway.intent.candidates) == 2
    for name in ("find_objects", "semantic_query", "evaluate_claim"):
        with pytest.raises(ValueError, match="CLARIFICATION_REQUIRED"):
            gateway.call(name, {})
    prepared = gateway.call("prepare_semantic_query", {})
    assert prepared["status"] == "NEEDS_INPUT"
    assert prepared["question"]["slot"] == "metric"


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

    from semaloom.core.semantic_query import SemanticQuery

    names = {item["name"] for item in gateway.catalog()}
    assert "prepare_semantic_query" in names
    assert "analyze_population" not in names
    raw = next(item for item in gateway.catalog() if item["name"] == "prepare_semantic_query")
    schema = json.dumps(raw["inputSchema"])
    assert "$ref" not in schema
    comparison = raw["inputSchema"]["properties"]["query"]["properties"]["comparison"]
    assert comparison["type"] == "object"
    assert set(comparison["properties"]["op"]["enum"]) == {
        "SHARE_OF_TOTAL",
        "RELATIVE_TO_MEAN",
        "STRICT_PEER",
        "PERIOD_OVER_PERIOD",
    }
    assert comparison["properties"]["subject"]["type"] == "object"
    with pytest.raises(ValidationError):
        SemanticQuery.model_validate(
            {
                "apiVersion": "semaloom/v0.1",
                "metrics": [{"id": "m", "aggregation": "SUM"}],
                "comparison": '{"op":"SHARE_OF_TOTAL"}',
            }
        )

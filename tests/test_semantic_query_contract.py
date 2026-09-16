"""Parse the frozen SemanticQuery samples through shipped types and merge_decision."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from semaloom.core.semantic_query import (
    PREPARE_STATUSES,
    UNSUPPORTED_OPERATORS,
    ChoiceError,
    ChoiceQuestion,
    ChoiceSubmit,
    PrepareResult,
    QueryResult,
    QuerySessionState,
    SemanticQuery,
    merge_decision,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "docs" / "spec" / "samples"


def _load(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def test_prepare_statuses_and_refusals_are_part_of_the_shipped_contract() -> None:
    assert PREPARE_STATUSES == ("READY", "NEEDS_INPUT", "UNSUPPORTED", "SOURCE_ERROR")
    assert "RAW_SQL" in UNSUPPORTED_OPERATORS
    assert "CROSS_SOURCE_SQL" in UNSUPPORTED_OPERATORS
    assert "COALESCE_MISSING_TO_ZERO" in UNSUPPORTED_OPERATORS


def test_direct_compute_sample_parses() -> None:
    sample = _load("semantic-query-direct.json")
    session = QuerySessionState.model_validate(sample["session"])
    prepare = PrepareResult.model_validate(sample["prepare"])
    result = QueryResult.model_validate(sample["result"])
    assert session.pending_question is None
    assert prepare.status == "READY"
    assert prepare.plan is not None
    assert prepare.plan.query.metrics[0].id == "finance.declaredRevenue"
    assert result.evidence.columns[0].id == "companyId"
    assert result.values[0]["value"] == "150.2600"
    assert "SELECT" not in json.dumps(sample["session"])


def test_two_round_choice_sample_merges_through_shipped_function() -> None:
    sample = _load("semantic-query-two-round.json")
    query = SemanticQuery.model_validate(sample["initialQuery"])
    round1 = sample["round1"]
    question1 = ChoiceQuestion.model_validate(round1["prepare"]["question"])
    prepare1 = PrepareResult.model_validate(round1["prepare"])
    assert prepare1.status == "NEEDS_INPUT"
    assert prepare1.question is not None
    submit1 = ChoiceSubmit.model_validate(round1["submit"])
    after_metric = merge_decision(query, question1, submit1)
    assert [item.id for item in after_metric.metrics] == ["finance.declaredRevenue"]
    assert after_metric.filters is None

    round2 = sample["round2"]
    question2 = ChoiceQuestion.model_validate(round2["prepare"]["question"])
    prepare2 = PrepareResult.model_validate(round2["prepare"])
    assert prepare2.status == "NEEDS_INPUT"
    submit2 = ChoiceSubmit.model_validate(round2["submit"])
    after_year = merge_decision(after_metric, question2, submit2)
    assert after_year.metrics[0].id == "finance.declaredRevenue"
    assert after_year.filters is not None
    final = PrepareResult.model_validate(sample["finalPrepare"])
    session = QuerySessionState.model_validate(sample["session"])
    assert final.status == "READY"
    assert final.plan is not None
    assert session.original_question == sample["session"]["originalQuestion"]
    assert {item.slot for item in after_year.decisions} == {"metric", "year"}
    assert after_year.metrics[0].id == final.plan.query.metrics[0].id
    assert len(after_year.decisions) == 2

    unsupported = PrepareResult.model_validate(sample["unsupported"])
    source_error = PrepareResult.model_validate(sample["sourceError"])
    assert unsupported.status == "UNSUPPORTED"
    assert unsupported.capability == "WINDOW_LAG"
    assert source_error.status == "SOURCE_ERROR"
    assert source_error.retryable is True


def test_submit_rejects_forged_expired_and_abort_without_inventing_facts() -> None:
    sample = _load("semantic-query-two-round.json")
    query = SemanticQuery.model_validate(sample["initialQuery"])
    question = ChoiceQuestion.model_validate(sample["round1"]["prepare"]["question"])
    with pytest.raises(ChoiceError, match="UNKNOWN_OPTION"):
        merge_decision(
            query,
            question,
            ChoiceSubmit.model_validate(
                {"questionId": "q-metric-1", "revision": 1, "optionIds": ["forged"]}
            ),
        )
    with pytest.raises(ChoiceError, match="VERSION_INVALID"):
        merge_decision(
            query,
            question,
            ChoiceSubmit.model_validate(
                {"questionId": "q-metric-1", "revision": 9, "optionIds": ["opt_declared_revenue"]}
            ),
        )
    with pytest.raises(ChoiceError, match="ABORTED"):
        merge_decision(
            query,
            question,
            ChoiceSubmit.model_validate(
                {"questionId": "q-metric-1", "revision": 1, "optionIds": ["opt_unclear"]}
            ),
        )
    merged = merge_decision(
        query,
        question,
        ChoiceSubmit.model_validate(sample["round1"]["submit"]),
    )
    with pytest.raises(ChoiceError, match="DUPLICATE_SUBMIT"):
        merge_decision(
            merged,
            question,
            ChoiceSubmit.model_validate(sample["round1"]["submit"]),
        )

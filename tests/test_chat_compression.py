"""Tests for conversation compression, history bounds, and policy dimension guidance."""

# ruff: noqa: RUF001 -- Chinese punctuation in test strings.

from __future__ import annotations

from semaloom.app.bootstrap import build_services
from semaloom.app.chat.compression import build_history_from_turns
from semaloom.app.chat.summary import evidence_summary
from semaloom.app.chat.tools import SemanticTools
from semaloom.runtime.auth import RequestActor

ACTOR = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))


def test_build_history_from_turns_empty_and_normal() -> None:
    assert build_history_from_turns([]) == []

    turns = [
        {"question": "Q1", "answer": {"text": "A1"}},
        {"question": "Q2", "answer": {"text": "A2"}},
    ]
    messages = build_history_from_turns(turns, model="qwen3.7-plus")
    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Q1"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == [{"type": "text", "text": "A1"}]
    assert messages[1]["model"] == "qwen3.7-plus"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "Q2"
    assert messages[3]["role"] == "assistant"
    assert messages[3]["content"] == [{"type": "text", "text": "A2"}]


def test_build_history_bounds_and_sliding_window() -> None:
    # 15 turns with long texts
    long_answer = "结论：" + "这是一段很长很长的业务分析详情内容。" * 200
    turns = [{"question": f"Question {i}", "answer": {"text": long_answer}} for i in range(15)]

    # Sliding window should keep only last 10 turns (20 messages)
    messages = build_history_from_turns(turns, max_turns=10, max_turn_text_len=500)
    assert len(messages) == 20
    assert messages[0]["content"] == "Question 5"
    assert messages[-2]["content"] == "Question 14"

    # Truncation notice attached to long text
    last_assistant_text = messages[-1]["content"][0]["text"]
    assert len(last_assistant_text) <= 500
    assert "已核对完整事实卡" in last_assistant_text


def test_covered_checks_attaches_policy_dimensions_on_no_applicable_policy() -> None:
    services = build_services(load_data=True)
    try:
        tools = SemanticTools(services.query, ACTOR)
        tools.call(
            "find_objects",
            {"objectType": "tax.Taxpayer", "filters": {"taxpayerId": "TAXPAYER-A"}},
        )
        # Query without scope/jurisdiction -> NO_APPLICABLE_POLICY
        result = tools.call(
            "semantic_query",
            {
                "apiVersion": "semaloom/v0.1",
                "select": [
                    {
                        "metric": "tax.adjustmentAmount",
                        "bindings": {"taxpayerId": "TAXPAYER-A", "taxYear": 2024},
                    }
                ],
                "context": {
                    "businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"},
                    "scope": {},
                },
            },
        )
        checks = result["checks"]
        assert len(checks) == 1
        assert checks[0]["error"] == "NO_APPLICABLE_POLICY"
        assert checks[0]["requiredDimensions"] == ["jurisdiction"]
        assert checks[0]["sampleDimensions"] == {"jurisdiction": "CN"}

        # Check evidence_summary formatting
        evidence = [{"tool": "semantic_query", "result": result}]
        rendered = evidence_summary(evidence)
        assert "未匹配到适用政策" in rendered
        assert "jurisdiction" in rendered
        assert "jurisdiction=CN" in rendered
        assert "不能判断为通过" in rendered

        # Check present_answer generates proactive follow-up
        tools.call(
            "present_answer",
            {
                "kind": "answer",
                "text": "测试总结",
                "evidenceIds": [result["evidenceId"]],
            },
        )
        assert tools.answer is not None
        follow_ups = tools.answer.get("followUps", [])
        assert len(follow_ups) == 1
        assert follow_ups[0]["label"] == "按属地 CN 重新核验"
        assert "tax.incomeReconciles" in follow_ups[0]["message"]
    finally:
        services.close()


def test_covered_checks_passes_when_policy_dimension_provided() -> None:
    services = build_services(load_data=True)
    try:
        tools = SemanticTools(services.query, ACTOR)
        tools.call(
            "find_objects",
            {"objectType": "tax.Taxpayer", "filters": {"taxpayerId": "TAXPAYER-A"}},
        )
        # Query with jurisdiction: CN -> evaluates to TRUE
        result = tools.call(
            "semantic_query",
            {
                "apiVersion": "semaloom/v0.1",
                "select": [
                    {
                        "metric": "tax.adjustmentAmount",
                        "bindings": {"taxpayerId": "TAXPAYER-A", "taxYear": 2024},
                    }
                ],
                "context": {
                    "businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"},
                    "scope": {"jurisdiction": "CN"},
                },
            },
        )
        checks = result["checks"]
        assert len(checks) == 1
        assert checks[0]["claim"]["truth"] == "TRUE"
        assert checks[0]["claim"]["claimId"] == "tax.incomeReconciles"
    finally:
        services.close()

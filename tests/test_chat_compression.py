"""Tests for conversation history bounds and policy dimension guidance."""

from __future__ import annotations

import pytest

from semaloom.app.bootstrap import build_services
from semaloom.app.chat.store import ChatStore
from semaloom.app.chat.summary import evidence_summary
from semaloom.app.chat.tools import SemanticTools
from semaloom.runtime.auth import RequestActor

ACTOR = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))


def test_chat_store_saves_pi_messages_and_enforces_limits() -> None:
    services = build_services(load_data=True)
    try:
        store = ChatStore(services.studio_drafts.engine)
        conv = store.create(ACTOR, "digest-1")

        history = [
            {"role": "user", "content": "Question 1", "timestamp": 1000},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Answer 1"}],
                "timestamp": 1001,
            },
        ]
        turn = {"question": "Question 1", "answer": {"text": "Answer 1"}}
        store.save(ACTOR, conv, history, turn)

        loaded = store.load(ACTOR, conv["id"])
        assert len(loaded["history"]) == 2
        assert loaded["history"][0]["role"] == "user"
        assert loaded["history"][1]["role"] == "assistant"
        assert len(loaded["turns"]) == 1

        # Bounded limits: > 100 messages raises
        oversized_history = [{"role": "user", "content": f"Q{i}"} for i in range(101)]
        with pytest.raises(ValueError, match="CONTEXT_LIMIT_START_NEW_CHAT"):
            store.save(ACTOR, loaded, oversized_history, turn)
    finally:
        services.close()


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


def test_browser_projection_uses_ontology_labels() -> None:
    from semaloom.app.bootstrap import compile_examples
    from semaloom.app.chat.presentation import project_browser_answer

    bundle = compile_examples()
    answer = {
        "kind": "explanation",
        "text": "ok",
        "evidence": [
            {
                "id": "e1",
                "tool": "list_semantics",
                "result": {
                    "definitions": [
                        {
                            "kind": "Action",
                            "id": "procurement.CreatePurchaseDraft",
                            "targetObject": "procurement.Order",
                            "preconditions": ["procurement.amountWithinLimit"],
                            "parameters": [{"name": "amount", "valueType": "DECIMAL"}],
                        }
                    ]
                },
            }
        ],
    }
    labeled = project_browser_answer(answer, bundle)
    labels = labeled["evidence"][0]["result"]["labels"]
    assert labels["procurement.CreatePurchaseDraft"] == "创建采购草稿"
    assert labels["procurement.Order"] == "采购订单"
    assert labels["procurement.amountWithinLimit"] == "金额未超授权"
    assert labels["amount"] == "金额"
    sources = labeled["evidence"][0]["result"]["definitions"][0]["sources"]
    assert sources[0]["label"]
    assert sources[0]["sourceId"] == "proc_draft_api"


def test_browser_projection_is_role_driven_and_domain_neutral() -> None:
    from semaloom.app.bootstrap import compile_examples
    from semaloom.app.chat.presentation import project_browser_answer

    answer = {
        "kind": "answer",
        "text": "ok",
        "query": {
            "apiVersion": "semaloom/v0.1",
            "groupBy": [{"id": "supplierCode", "timeGrain": None}],
        },
        "evidence": [
            {
                "id": "e-procurement",
                "tool": "prepare_semantic_query",
                "result": {
                    "claim": {
                        "claimId": "procurement.amountWithinLimit",
                        "truth": "TRUE",
                    },
                    "values": [
                        {
                            "metric": "procurement.orderAmount",
                            "aggregation": "SUM",
                            "grain": {"supplierCode": "S-1"},
                            "labels": {"supplierCode": "通用供应方"},
                            "value": "120.5000",
                            "unit": "CNY",
                        },
                        {
                            "metric": "procurement.orderAmount",
                            "aggregation": "SUM",
                            "grain": {"supplierCode": "S-2"},
                            "labels": {"supplierCode": "另一供应方"},
                            "value": "90.0000",
                            "unit": "CNY",
                        },
                    ],
                    "evidence": {
                        "columns": [
                            {
                                "id": "supplierCode",
                                "label": "伙伴",
                                "role": "CATEGORY",
                                "valueType": "STRING",
                                "unit": None,
                            },
                            {
                                "id": "value",
                                "label": "金额",
                                "role": "MEASURE",
                                "valueType": "DECIMAL",
                                "unit": "CNY",
                            },
                        ],
                        "rows": [["S-1", "120.5000"], ["S-2", "88.0000"]],
                        "truncated": False,
                        "rowCount": 2,
                    },
                },
            }
        ],
    }
    projected = project_browser_answer(answer, compile_examples())["presentation"]
    assert projected["metrics"][0]["label"] == "金额未超授权"
    assert projected["metrics"][0]["displayValue"] == "成立"
    assert projected["reports"][0]["categoryKey"] == "c0"
    assert projected["reports"][0]["rows"][1]["c1"] == "90"
    assert projected["reports"][0]["preferredView"] == "bar"
    assert {item["semanticId"] for item in projected["reports"][0]["columns"]} == {
        "supplierCode",
        "procurement.orderAmount",
    }
    assert "finance" not in str(projected) and "tax" not in str(projected)


def test_browser_projection_uses_aggregate_year_values_for_trends() -> None:
    from semaloom.app.bootstrap import compile_examples
    from semaloom.app.chat.presentation import project_browser_answer

    answer = {
        "kind": "answer",
        "text": "ok",
        "query": {
            "apiVersion": "semaloom/v0.1",
            "groupBy": [{"id": "taxYear", "timeGrain": "YEAR"}],
        },
        "evidence": [
            {
                "id": "e-trend",
                "tool": "prepare_semantic_query",
                "result": {
                    "values": [
                        {
                            "metric": "finance.declaredRevenue",
                            "aggregation": "SUM",
                            "grain": {"taxYear": 2024},
                            "value": "300.0300",
                            "unit": "CNY",
                        },
                        {
                            "metric": "finance.declaredRevenue",
                            "aggregation": "SUM",
                            "grain": {"taxYear": 2025},
                            "value": "330.0300",
                            "unit": "CNY",
                        },
                    ],
                    "evidence": {
                        "columns": ["对象", "原始值"],
                        "rows": [["C1", "100.01"], ["C2", "200.02"]],
                    },
                },
            }
        ],
    }
    report = project_browser_answer(answer, compile_examples())["presentation"]["reports"][0]
    assert report["preferredView"] == "line"
    assert report["rows"] == [{"c0": "2024", "c1": "300.03"}, {"c0": "2025", "c1": "330.03"}]
    assert "100.01" not in str(report)

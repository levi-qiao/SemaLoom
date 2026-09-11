from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from semaloom.app.bootstrap import build_services, compile_examples
from semaloom.app.factory import create_app
from semaloom.core.results import MetricSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.eval import EvaluationError, evaluate_named_claim
from semaloom.runtime.studio import studio_graph, studio_inspector

ANALYST = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
APPROVER = RequestActor(tenant="tenant-a", subject="bob", roles=("approver", "analyst"))
CORE = Path(__file__).resolve().parents[1] / "src" / "semaloom"


def test_second_domain_gold_paths() -> None:
    services = build_services(load_data=True)
    query = services.query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                MetricSelect(
                    metric="procurement.orderAmount",
                    bindings={"orderId": "PO-001"},
                ),
            ),
            context=QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"}),
        ),
        ANALYST,
    )
    assert query.observations[0].kind == "PRESENT"
    explain = query.source_activities[0]
    assert explain.mapping_id.endswith("orders")
    within, _, _, _ = evaluate_named_claim(
        services.bundle,
        services.query,
        ANALYST,
        claim_id="procurement.amountWithinLimit",
        bindings={"orderId": "PO-001", "organizationId": "ORG-A"},
        period_from="2024-01-01",
        period_to="2025-01-01",
        dimensions={"organizationId": "ORG-A"},
    )
    assert within.truth == "TRUE"
    unknown, _, _, _ = evaluate_named_claim(
        services.bundle,
        services.query,
        ANALYST,
        claim_id="tax.incomeReconciles",
        bindings={"taxpayer": "TAXPAYER-A", "taxYear": 2025},
        period_from="2025-01-01",
        period_to="2026-01-01",
        dimensions={"jurisdiction": "CN"},
    )
    assert unknown.truth == "UNKNOWN"
    plan = services.actions.plan(
        ANALYST,
        action_id="procurement.CreatePurchaseDraft",
        target={"orderId": "PO-001"},
        parameters={"amount": "10.00"},
    )
    services.actions.approve(APPROVER, plan.plan_id)
    execution = services.actions.execute(ANALYST, plan.plan_id)
    assert execution.status == "VERIFIED"


def test_policy_period_switch_and_straddle_reject() -> None:
    services = build_services(load_data=True)
    y2024, _, _, _ = evaluate_named_claim(
        services.bundle,
        services.query,
        ANALYST,
        claim_id="tax.incomeReconciles",
        bindings={"taxpayer": "TAXPAYER-A", "taxYear": 2024},
        period_from="2024-01-01",
        period_to="2025-01-01",
        dimensions={"jurisdiction": "CN"},
    )
    y2025, _, _, _ = evaluate_named_claim(
        services.bundle,
        services.query,
        ANALYST,
        claim_id="tax.incomeReconciles",
        bindings={"taxpayer": "TAXPAYER-A", "taxYear": 2025},
        period_from="2025-01-01",
        period_to="2026-01-01",
        dimensions={"jurisdiction": "CN"},
    )
    assert y2024.context["policyId"] == "tax.incomeReconcilesY2024"
    assert y2025.context["policyId"] == "tax.incomeReconcilesY2025"
    assert y2024.context["policyId"] != y2025.context["policyId"]
    try:
        evaluate_named_claim(
            services.bundle,
            services.query,
            ANALYST,
            claim_id="tax.incomeReconciles",
            bindings={"taxpayer": "TAXPAYER-A", "taxYear": 2024},
            period_from="2024-06-01",
            period_to="2025-06-01",
            dimensions={"jurisdiction": "CN"},
        )
        raise AssertionError("straddling period must be rejected")
    except EvaluationError as exc:
        assert exc.code == "POLICY_PERIOD_SPLIT_REQUIRED"


def test_core_and_compiler_have_no_industry_branches() -> None:
    forbidden = (
        "if domain ==",
        "if domain==",
        "tax.operatingRevenue",
        "procurement.Order",
        "GRAIN_COLUMNS",
        '"taxYear"',
        '"organizationId"',
        '"jurisdiction"',
        '"taxpayer"',
        '"orderId"',
    )
    roots = (CORE / "core", CORE / "compiler", CORE / "runtime" / "query.py")
    for folder in roots:
        paths = [folder] if folder.is_file() else folder.rglob("*.py")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in text, f"{path} contains {token}"


def test_studio_graph_and_inspector_and_draft() -> None:
    bundle = compile_examples()
    graph = studio_graph(bundle)
    ids = {node["id"] for node in graph["nodes"]}
    assert "tax.Taxpayer" in ids
    assert "procurement.Order" in ids
    assert any(edge["source"] == "procurement.Order" for edge in graph["edges"])
    inspector = studio_inspector(bundle, "procurement.Order")
    assert inspector is not None
    assert "procurement.orderAmount" in inspector["metrics"]
    client = TestClient(create_app(load_services=True))
    headers = {"Authorization": "Bearer tenant-a-modeler"}
    denied = client.get(
        "/v0.1/studio/graph",
        headers={"Authorization": "Bearer tenant-a-analyst"},
    )
    assert denied.status_code == 403
    graph_resp = client.get("/v0.1/studio/graph", headers=headers)
    assert graph_resp.status_code == 200
    created = client.put(
        "/v0.1/studio/drafts/default",
        headers=headers,
        json={"expectedRevision": 0, "payload": {"note": "first"}},
    )
    assert created.status_code == 200
    conflict = client.put(
        "/v0.1/studio/drafts/default",
        headers=headers,
        json={"expectedRevision": 0, "payload": {"note": "stale"}},
    )
    assert conflict.status_code == 409


def test_studio_static_is_html_and_api_404_is_not() -> None:
    client = TestClient(create_app(load_services=True))
    page = client.get("/studio/")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    assert "SemaLoom" in page.text
    missing = client.get("/v0.1/does-not-exist")
    assert missing.status_code == 404
    assert "text/html" not in missing.headers.get("content-type", "")

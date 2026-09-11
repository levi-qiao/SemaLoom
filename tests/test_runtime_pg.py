from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from semaloom.app.bootstrap import build_services, compile_examples
from semaloom.app.factory import create_app
from semaloom.core.results import MetricSelect, ObjectSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.eval import evaluate_named_claim
from semaloom.runtime.fixtures import load_synthetic
from semaloom.runtime.query import QueryService

ANALYST = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
OTHER = RequestActor(tenant="tenant-b", subject="carol", roles=("analyst",))
DENIED = RequestActor(tenant="tenant-a", subject="eve", roles=("guest",))
APPROVER = RequestActor(tenant="tenant-a", subject="bob", roles=("approver", "analyst"))


def _metric_request(metric: str, **bindings: str | int) -> QueryRequest:
    return QueryRequest(
        api_version="semaloom/v0.1",
        select=(MetricSelect(metric=metric, bindings=bindings),),
        context=QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"}),
    )


def test_authorized_point_query_with_evidence() -> None:
    load_synthetic()
    services = build_services(load_data=False)
    envelope = services.query.execute(
        _metric_request(
            "tax.reportedIncome",
            taxpayer="TAXPAYER-A",
            taxYear=2024,
            perspective="TAX_RETURN",
        ),
        ANALYST,
    )
    assert envelope.status == "SUCCEEDED"
    assert envelope.observations[0].kind == "PRESENT"
    assert envelope.observations[0].value == "110.1000"
    assert Decimal(envelope.observations[0].value or "0") == Decimal("110.1000")
    assert envelope.source_activities
    assert envelope.source_activities[0].mapping_id == "tax.reportedIncome.pg"


def test_unauthorized_role_is_forbidden_not_missing() -> None:
    services = build_services(load_data=False)
    envelope = services.query.execute(
        _metric_request(
            "tax.reportedIncome", taxpayer="TAXPAYER-A", taxYear=2024, perspective="TAX_RETURN"
        ),
        DENIED,
    )
    assert envelope.observations[0].kind == "FORBIDDEN"
    assert envelope.status == "FAILED"


def test_other_tenant_does_not_see_tenant_a_amount() -> None:
    services = build_services(load_data=False)
    own = services.query.execute(
        _metric_request(
            "tax.reportedIncome", taxpayer="TAXPAYER-A", taxYear=2024, perspective="TAX_RETURN"
        ),
        OTHER,
    )
    assert own.observations[0].kind == "PRESENT"
    assert own.observations[0].value == "999.9900"


def test_sql_binding_is_rejected() -> None:
    services = build_services(load_data=False)
    envelope = services.query.execute(
        _metric_request("tax.reportedIncome", sql="drop table tax_metric", taxpayer="TAXPAYER-A"),
        ANALYST,
    )
    assert envelope.diagnostics[0].code == "INVALID_BINDINGS"


def test_two_database_link_composition() -> None:
    services = build_services(load_data=False)
    envelope = services.query.follow_link(
        link_id="procurement.orderSupplier",
        source_identity="PO-001",
        actor=ANALYST,
    )
    assert envelope.status == "SUCCEEDED"
    assert envelope.observations[0].kind == "PRESENT"
    assert envelope.observations[0].value == "Supplier One"
    assert envelope.extras["sourceSourceId"] == "orders_pg"
    assert envelope.extras["targetSourceId"] == "suppliers_pg"


def test_claim_true_false_unknown_and_error() -> None:
    services = build_services(load_data=False)
    true_claim, _, _, _ = evaluate_named_claim(
        services.bundle,
        services.query,
        ANALYST,
        claim_id="tax.incomeReconciles",
        bindings={"taxpayer": "TAXPAYER-A", "taxYear": 2024},
        period_from="2024-01-01",
        period_to="2025-01-01",
        dimensions={"jurisdiction": "CN"},
    )
    assert true_claim.truth == "TRUE"
    unknown_claim, _, _diagnostics, _ = evaluate_named_claim(
        services.bundle,
        services.query,
        ANALYST,
        claim_id="tax.incomeReconciles",
        bindings={"taxpayer": "TAXPAYER-A", "taxYear": 2025},
        period_from="2025-01-01",
        period_to="2026-01-01",
        dimensions={"jurisdiction": "CN"},
    )
    assert unknown_claim.truth == "UNKNOWN"
    assert (
        "NULL_INPUT" in unknown_claim.reason_codes or "MISSING_INPUT" in unknown_claim.reason_codes
    )


def test_release_activation_does_not_mix_in_flight_bundle() -> None:
    services = build_services(load_data=False)
    digest = services.registry.publish(services.bundle, publisher="tester")
    services.registry.activate("dev", digest, expected_revision=None)
    in_flight = QueryService(services.bundle, services.query.provider)
    services.registry.activate("dev", digest, expected_revision=1)
    envelope = in_flight.execute(
        _metric_request(
            "tax.reportedIncome", taxpayer="TAXPAYER-A", taxYear=2024, perspective="TAX_RETURN"
        ),
        ANALYST,
    )
    assert envelope.release_digest == services.bundle.digest


def test_action_plan_has_no_write_and_retry_is_one_effect() -> None:
    services = build_services(load_data=True)
    writes_before = services.drafts.writes
    plan = services.actions.plan(
        ANALYST,
        action_id="tax.CreateTaxAdjustmentDraft",
        target={"taxpayerId": "TAXPAYER-A"},
        parameters={"amount": "10.00", "taxYear": "2024"},
    )
    assert services.drafts.writes == writes_before
    try:
        services.actions.execute(ANALYST, plan.plan_id)
        raise AssertionError("unapproved execute must fail")
    except PermissionError:
        pass
    assert services.drafts.writes == writes_before
    services.actions.approve(APPROVER, plan.plan_id)
    first = services.actions.execute(ANALYST, plan.plan_id)
    second = services.actions.execute(ANALYST, plan.plan_id)
    assert first.execution_id == second.execution_id
    assert services.drafts.writes == writes_before + 1


def test_expired_or_retargeted_execute_does_not_write() -> None:
    services = build_services(load_data=False)
    plan = services.actions.plan(
        ANALYST,
        action_id="tax.CreateTaxAdjustmentDraft",
        target={"taxpayerId": "TAXPAYER-A"},
        parameters={"amount": "10.00", "taxYear": "2024"},
        expires_in_seconds=-1,
    )
    services.actions.approve(APPROVER, plan.plan_id)
    writes = services.drafts.writes
    try:
        services.actions.execute(ANALYST, plan.plan_id)
        raise AssertionError("expired plan must fail")
    except ValueError as exc:
        assert "EXPIRED" in str(exc)
    assert services.drafts.writes == writes
    fresh = services.actions.plan(
        ANALYST,
        action_id="tax.CreateTaxAdjustmentDraft",
        target={"taxpayerId": "TAXPAYER-A"},
        parameters={"amount": "10.00", "taxYear": "2024"},
    )
    services.actions.approve(APPROVER, fresh.plan_id)
    try:
        services.actions.execute(
            ANALYST, fresh.plan_id, parameters={"amount": "99.00", "taxYear": "2024"}
        )
        raise AssertionError("retargeted parameters must fail")
    except ValueError as exc:
        assert "STALE_PLAN" in str(exc)
    assert services.drafts.writes == writes


def test_rest_rejects_invalid_token_and_sql() -> None:
    client = TestClient(create_app(load_services=True))
    denied = client.post(
        "/v0.1/query",
        json={
            "metric": "tax.reportedIncome",
            "bindings": {"taxpayer": "TAXPAYER-A", "taxYear": 2024, "perspective": "TAX_RETURN"},
            "periodFrom": "2024-01-01",
            "periodTo": "2025-01-01",
        },
        headers={"Authorization": "Bearer nope"},
    )
    assert denied.status_code == 401
    sql = client.post(
        "/v0.1/query",
        json={
            "metric": "tax.reportedIncome",
            "bindings": {"sql": "1=1", "taxpayer": "TAXPAYER-A"},
            "periodFrom": "2024-01-01",
            "periodTo": "2025-01-01",
        },
        headers={"Authorization": "Bearer tenant-a-analyst"},
    )
    assert sql.status_code == 400
    ok = client.post(
        "/v0.1/query",
        json={
            "metric": "tax.reportedIncome",
            "bindings": {"taxpayer": "TAXPAYER-A", "taxYear": 2024, "perspective": "TAX_RETURN"},
            "periodFrom": "2024-01-01",
            "periodTo": "2025-01-01",
        },
        headers={"Authorization": "Bearer tenant-a-analyst"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["observations"][0]["kind"] == "PRESENT"
    tools = client.get("/v0.1/mcp/tools")
    assert tools.status_code == 200
    names = {item["name"] for item in tools.json()["tools"]}
    assert names == {"semantic_query", "evaluate_claim", "plan_action", "action_status"}


def test_object_query_and_compile_examples_stable() -> None:
    bundle = compile_examples()
    assert bundle.digest
    services = build_services(load_data=False)
    envelope = services.query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                ObjectSelect(
                    object_type="procurement.Order",
                    identity={"orderId": "PO-001"},
                    properties=("status",),
                ),
            ),
            context=QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"}),
        ),
        ANALYST,
    )
    assert envelope.observations[0].kind == "PRESENT"

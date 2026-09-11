from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient

from semaloom.app.bootstrap import AppServices, build_services, compile_examples
from semaloom.app.factory import create_app
from semaloom.compiler.digest import sha256_digest
from semaloom.core.bundle import CompiledBundle
from semaloom.core.results import MetricSelect, ObjectSelect, QueryContext, QueryRequest
from semaloom.runtime.action import ActionService, DraftStore
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.eval import evaluate_named_claim
from semaloom.runtime.fixtures import load_synthetic
from semaloom.runtime.query import QueryService

ANALYST = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
OTHER = RequestActor(tenant="tenant-b", subject="carol", roles=("analyst",))
DENIED = RequestActor(tenant="tenant-a", subject="eve", roles=("guest",))
APPROVER = RequestActor(tenant="tenant-a", subject="bob", roles=("approver", "analyst"))
OTHER_APPROVER = RequestActor(tenant="tenant-b", subject="mallory", roles=("approver", "analyst"))


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


def _claim(
    services: AppServices,
    *,
    taxpayer: str,
    year: int,
    query: QueryService | None = None,
    bundle: CompiledBundle | None = None,
) -> tuple:
    target = bundle if bundle is not None else services.bundle
    runner = query if query is not None else services.query
    return evaluate_named_claim(
        target,
        runner,
        ANALYST,
        claim_id="tax.incomeReconciles",
        bindings={"taxpayer": taxpayer, "taxYear": year},
        period_from=f"{year}-01-01",
        period_to=f"{year + 1}-01-01",
        dimensions={"jurisdiction": "CN"},
    )


def test_claim_true_false_unknown_and_error() -> None:
    services = build_services(load_data=True)
    true_claim, _, _, _ = _claim(services, taxpayer="TAXPAYER-A", year=2024)
    assert true_claim.truth == "TRUE"
    false_claim, _, _, _ = _claim(services, taxpayer="TAXPAYER-B", year=2024)
    assert false_claim.truth == "FALSE"
    unknown_claim, unknown_obs, _, _ = _claim(services, taxpayer="TAXPAYER-A", year=2025)
    assert unknown_claim.truth == "UNKNOWN"
    assert (
        "NULL_INPUT" in unknown_claim.reason_codes or "MISSING_INPUT" in unknown_claim.reason_codes
    )
    assert all(item.kind != "UNAVAILABLE" for item in unknown_obs)
    payload = services.bundle.model_dump(mode="json", by_alias=True, exclude_none=True)
    for mapping in payload["mappings"]:
        if mapping["id"] == "tax.reportedIncome.pg":
            mapping["physical"]["table"] = "no_such_relation"
    payload.pop("digest", None)
    payload["digest"] = sha256_digest(payload)
    broken = CompiledBundle.model_validate(payload)
    error_claim, error_obs, error_diags, _ = _claim(
        services,
        taxpayer="TAXPAYER-A",
        year=2024,
        query=QueryService(broken, services.provider),
        bundle=broken,
    )
    assert error_claim.truth == "UNKNOWN"
    assert any(item.kind == "UNAVAILABLE" for item in error_obs)
    assert any(item.code == "PROVIDER_ERROR" for item in error_diags)
    assert "UNAVAILABLE" in error_claim.reason_codes


def _relabel(bundle: CompiledBundle, label: str) -> CompiledBundle:
    payload = bundle.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload["packs"][0]["label"] = label
    payload.pop("digest", None)
    payload["digest"] = sha256_digest(payload)
    return CompiledBundle.model_validate(payload)


def test_release_activation_does_not_mix_in_flight_bundle() -> None:
    services = build_services(load_data=True)
    bundle_a = services.bundle
    bundle_b = _relabel(bundle_a, "release-B")
    assert bundle_a.digest != bundle_b.digest
    services.registry.publish(bundle_a, publisher="tester")
    services.registry.publish(bundle_b, publisher="tester")
    revision = services.registry.activate("dev", bundle_a.digest, expected_revision=None)
    in_flight = services.query_for_digest(bundle_a.digest)
    services.registry.activate("dev", bundle_b.digest, expected_revision=revision)
    request = _metric_request(
        "tax.reportedIncome", taxpayer="TAXPAYER-A", taxYear=2024, perspective="TAX_RETURN"
    )
    env_a = in_flight.execute(request, ANALYST)
    env_b = services.query_active().execute(request, ANALYST)
    assert env_a.release_digest == bundle_a.digest
    assert env_b.release_digest == bundle_b.digest
    assert env_a.observations[0].kind == "PRESENT"
    assert env_b.observations[0].kind == "PRESENT"


def test_registry_rejects_bundle_mutated_after_compilation() -> None:
    services = build_services(load_data=True)
    services.bundle.mappings[0].physical["table"] = "tampered_relation"

    with pytest.raises(ValueError, match="RELEASE_DIGEST_MISMATCH"):
        services.registry.publish(services.bundle, publisher="tester")


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


def test_action_plan_is_tenant_bound_and_inputs_are_typed() -> None:
    services = build_services(load_data=True)
    with pytest.raises(ValueError, match="INVALID_PARAMETERS"):
        services.actions.plan(
            ANALYST,
            action_id="tax.CreateTaxAdjustmentDraft",
            target={"taxpayerId": "TAXPAYER-A"},
            parameters={"amount": "not-a-decimal", "taxYear": "2024"},
        )
    plan = services.actions.plan(
        ANALYST,
        action_id="tax.CreateTaxAdjustmentDraft",
        target={"taxpayerId": "TAXPAYER-A"},
        parameters={"amount": "10.00", "taxYear": "2024"},
    )
    with pytest.raises(PermissionError, match="FORBIDDEN"):
        services.actions.approve(OTHER_APPROVER, plan.plan_id)
    services.actions.approve(APPROVER, plan.plan_id)
    with pytest.raises(PermissionError, match="FORBIDDEN"):
        services.actions.execute(OTHER, plan.plan_id)
    services.actions.execute(ANALYST, plan.plan_id)
    with pytest.raises(PermissionError, match="FORBIDDEN"):
        services.actions.status(OTHER, plan.plan_id)


def test_concurrent_action_execute_claims_one_external_effect() -> None:
    class PausedDraftStore(DraftStore):
        def __init__(self) -> None:
            super().__init__()
            self.entered = Event()
            self.release = Event()

        def create(
            self,
            *,
            idempotency_key: str,
            payload: dict[str, Any],
            expected_version: int | None = None,
        ) -> str:
            self.entered.set()
            assert self.release.wait(timeout=5)
            return super().create(
                idempotency_key=idempotency_key,
                payload=payload,
                expected_version=expected_version,
            )

    services = build_services(load_data=True)
    drafts = PausedDraftStore()
    actions = ActionService(services.bundle, services.registry.engine, drafts)
    plan = actions.plan(
        ANALYST,
        action_id="tax.CreateTaxAdjustmentDraft",
        target={"taxpayerId": "TAXPAYER-A"},
        parameters={"amount": "10.00", "taxYear": "2024"},
    )
    actions.approve(APPROVER, plan.plan_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(actions.execute, ANALYST, plan.plan_id)
        assert drafts.entered.wait(timeout=5)
        second = actions.execute(ANALYST, plan.plan_id)
        drafts.release.set()
        first = first_future.result(timeout=5)

    assert first.execution_id == second.execution_id
    assert first.status == "VERIFIED"
    assert second.status == "EXECUTING"
    assert drafts.writes == 1


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
    assert client.get("/v0.1/mcp/tools").status_code == 401
    tools = client.get("/v0.1/mcp/tools", headers={"Authorization": "Bearer tenant-a-analyst"})
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

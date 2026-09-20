"""HTTP uses the tenant release for both plans and facts, not the startup bundle."""

from __future__ import annotations

from fastapi.testclient import TestClient

from semaloom.app.bootstrap import build_services
from semaloom.app.factory import create_app
from semaloom.app.http import router
from semaloom.core.results import MetricSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.studio_control import documents_from_bundle
from semaloom.sdk import compile_documents


def test_tenant_activation_changes_public_query_claim_and_studio() -> None:
    services = build_services(load_data=True)
    app = create_app(load_services=False)
    app.state.services = services
    app.include_router(router)
    client = TestClient(app)
    headers = {"Authorization": "Bearer tenant-a-analyst"}
    body = {
        "metric": "tax.reportedIncome",
        "bindings": {"taxpayerId": "TAXPAYER-A", "taxYear": 2024},
        "periodFrom": "2024-01-01",
        "periodTo": "2025-01-01",
    }
    before = client.post("/v0.1/query", json=body, headers=headers).json()
    pinned = services.query_active("tenant-a")
    docs = documents_from_bundle(services.bundle)
    for doc in docs:
        if doc["id"] == "tax.reportedIncome.pg":
            doc["physical"]["filters"]["metric"] = "otherRevenue"
        if doc["id"] == "tax.Taxpayer":
            doc["label"] = "Activated company"
    result = compile_documents(docs)
    assert result.ok and result.bundle is not None
    active = result.bundle
    services.registry.publish(active, publisher="test-reviewer")
    services.registry.activate("tenant:tenant-a:dev", active.digest, expected_revision=0)
    try:
        after = client.post("/v0.1/query", json=body, headers=headers).json()
        assert after["releaseDigest"] == active.digest != before["releaseDigest"]
        assert after["observations"][0]["kind"] == "PRESENT"
        assert after["observations"][0]["value"] != before["observations"][0]["value"]
        canonical = QueryRequest(
            api_version="semaloom/v0.1",
            select=(MetricSelect(metric=body["metric"], bindings=body["bindings"]),),
            context=QueryContext(
                business_period={"from": body["periodFrom"], "to": body["periodTo"]}
            ),
        )
        modern = client.post(
            "/v0.1/query", json=canonical.model_dump(by_alias=True), headers=headers
        )
        assert modern.status_code == 200
        assert modern.json()["observations"][0]["value"] == after["observations"][0]["value"]
        old = pinned.execute(
            canonical, RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
        )
        assert old.release_digest == before["releaseDigest"]
        assert old.observations[0].value == before["observations"][0]["value"]
        other = client.post(
            "/v0.1/query", json=body, headers={"Authorization": "Bearer tenant-b-analyst"}
        )
        assert other.json()["releaseDigest"] == before["releaseDigest"]
        claim = client.post(
            "/v0.1/claims/evaluate",
            json={
                "claimId": "tax.incomeReconciles",
                "bindings": body["bindings"],
                "periodFrom": body["periodFrom"],
                "periodTo": body["periodTo"],
                "dimensions": {"jurisdiction": "CN"},
            },
            headers=headers,
        )
        assert claim.status_code == 200
        assert claim.json()["releaseDigest"] == active.digest
        assert claim.json()["claim"]["truth"] == "FALSE"
        graph = client.get(
            "/v0.1/studio/graph", headers={"Authorization": "Bearer tenant-a-model-viewer"}
        )
        assert any(n["label"] == "Activated company" for n in graph.json()["nodes"])
    finally:
        services.close()

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from semaloom.app.bootstrap import compile_examples
from semaloom.app.factory import create_app
from semaloom.app.http import router
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.discovery import SemanticDiscovery
from semaloom.runtime.studio_control import documents_from_bundle
from semaloom.sdk import compile_documents

ANALYST = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))


def test_search_exposes_meaning_and_ambiguity_without_physical_bindings() -> None:
    service = SemanticDiscovery(compile_examples())
    result = service.search("收入", ANALYST, limit=2)
    assert len(result["candidates"]) == 2
    assert result["hasMore"] and result["requiresSelection"]
    complete = service.search("收入", ANALYST)
    assert {"tax.reportedIncome", "tax.auditIncome"} <= {d["id"] for d in complete["candidates"]}
    metric = service.describe("tax.reportedIncome", ANALYST)
    assert metric["unit"] == "CNY" and metric["perspective"] == "TAX_RETURN"
    assert "taxYear" in metric["grain"]
    assert "physical" not in metric and "sourceId" not in metric
    assert metric["analysisCapabilities"]["collectionJoin"] is False
    link = service.describe("tax.filingTaxpayer", ANALYST)
    assert link["analysisCapabilities"] == {
        "pointLookup": False,
        "keyedFind": True,
        "collectionJoin": False,
    }
    with pytest.raises(KeyError):
        service.describe("tax.reportedIncome.pg", ANALYST)
    with pytest.raises(KeyError):
        service.describe("tax.postgres", ANALYST)
    assert service.search(" SELECT * FROM tax_metric ", ANALYST)["candidates"] == []
    assert (
        service.search("TAX.REPORTEDINCOME", ANALYST)["candidates"][0]["id"] == "tax.reportedIncome"
    )


def test_discovery_denies_unprivileged_identity_and_bounds_search() -> None:
    service = SemanticDiscovery(compile_examples())
    guest = RequestActor(tenant="tenant-a", subject="guest", roles=("guest",))
    with pytest.raises(PermissionError):
        service.search("收入", guest)
    with pytest.raises(PermissionError):
        service.describe("tax.Taxpayer", guest)
    for query, limit in ((" ", 20), ("x" * 201, 20), ("tax", 51), ("tax", 0)):
        with pytest.raises(ValueError):
            service.search(query, ANALYST, limit=limit)


def test_discovery_http_pins_tenant_bundle_and_does_not_expose_unknown_ids() -> None:
    base = compile_examples()
    documents = documents_from_bundle(base)
    for doc in documents:
        if doc["id"] == "tax.Taxpayer":
            doc["label"] = "Tenant A current entity"
    changed = compile_documents(documents)
    assert changed.bundle is not None
    app = create_app(load_services=False)
    app.state.services = SimpleNamespace(
        query_active=lambda tenant: SimpleNamespace(
            bundle=changed.bundle if tenant == "tenant-a" else base
        )
    )
    app.include_router(router)
    client = TestClient(app)
    headers = {"Authorization": "Bearer tenant-a-analyst"}
    own = client.get("/v0.1/describe", params={"semanticId": "tax.Taxpayer"}, headers=headers)
    assert own.status_code == 200 and own.json()["releaseDigest"] == changed.bundle.digest
    link = client.get(
        "/v0.1/describe", params={"semanticId": "tax.filingTaxpayer"}, headers=headers
    )
    assert link.status_code == 200
    assert link.json()["analysisCapabilities"]["collectionJoin"] is False
    search = client.get("/v0.1/search", params={"q": "申报纳税人"}, headers=headers)
    assert search.status_code == 200
    found = next(item for item in search.json()["candidates"] if item["id"] == "tax.filingTaxpayer")
    assert found["analysisCapabilities"]["pointLookup"] is False
    assert "physical" not in found
    other = client.get(
        "/v0.1/describe",
        params={"semanticId": "tax.Taxpayer"},
        headers={"Authorization": "Bearer tenant-b-analyst"},
    )
    assert other.json()["releaseDigest"] == base.digest
    for target in ("unknown", "tax.Taxpayer.pg"):
        assert (
            client.get("/v0.1/describe", params={"semanticId": target}, headers=headers).status_code
            == 404
        )
    assert client.get("/v0.1/search", params={"q": "收入"}, headers=headers).json()[
        "requiresSelection"
    ]
    assert client.get("/v0.1/search", params={"q": "收入"}).status_code == 401
    assert (
        client.get(
            "/v0.1/search",
            params={"q": "收入"},
            headers={"Authorization": "Bearer tenant-a-modeler"},
        ).status_code
        == 403
    )
    assert (
        client.get("/v0.1/search", params={"q": "收入", "limit": 51}, headers=headers).status_code
        == 422
    )

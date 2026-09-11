from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from semaloom.app.bootstrap import build_services
from semaloom.app.factory import create_app
from semaloom.runtime.fixtures import engines, load_synthetic
from semaloom.runtime.source_validation import resolve_environment_binding
from semaloom.runtime.studio_release import ReleaseGateError


def test_source_profiles_are_tenant_scoped_versioned_and_never_accept_secrets() -> None:
    client = TestClient(create_app(load_services=True, load_fixtures=True))
    client.post("/v0.1/studio/session/demo", json={"persona": "studio-admin"})
    admin = {
        "Origin": "http://testserver",
        "X-CSRF-Token": client.cookies["semaloom_csrf"],
    }

    profiles = client.get("/v0.1/studio/source-profiles")
    assert profiles.status_code == 200
    assert {item["sourceId"] for item in profiles.json()["profiles"]} >= {
        "orders_pg",
        "proc_draft_api",
    }

    saved = client.put(
        "/v0.1/studio/source-profiles/erp_api",
        headers=admin,
        json={
            "expectedRevision": 0,
            "label": "ERP read API",
            "provider": "openapi",
            "bindingRef": "env:ERP_API_URL",
            "secretRef": "vault:erp/read-token",
            "settings": {"healthPath": "/health"},
        },
    )
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert "must-not-store" not in str(saved.json())

    conflict = client.put(
        "/v0.1/studio/source-profiles/erp_api",
        headers=admin,
        json={
            "expectedRevision": 0,
            "label": "stale",
            "provider": "openapi",
            "bindingRef": "env:ERP_API_URL",
            "settings": {},
        },
    )
    assert conflict.status_code == 409
    viewer = TestClient(create_app(load_services=True, load_fixtures=False))
    viewer.post("/v0.1/studio/session/demo", json={"persona": "viewer"})
    viewer_headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": viewer.cookies["semaloom_csrf"],
    }
    forbidden = viewer.put(
        "/v0.1/studio/source-profiles/erp_api",
        headers=viewer_headers,
        json={
            "expectedRevision": 1,
            "label": "forbidden",
            "provider": "openapi",
            "bindingRef": "env:ERP_API_URL",
            "settings": {},
        },
    )
    assert forbidden.status_code == 403
    secret = client.put(
        "/v0.1/studio/source-profiles/erp_api",
        headers=admin,
        json={
            "expectedRevision": 1,
            "label": "secret",
            "provider": "openapi",
            "bindingRef": "env:ERP_API_URL",
            "settings": {"token": "must-not-store"},
        },
    )
    assert secret.status_code == 422
    nested_secret = client.put(
        "/v0.1/studio/source-profiles/erp_api",
        headers=admin,
        json={
            "expectedRevision": 1,
            "label": "secret",
            "provider": "openapi",
            "bindingRef": "env:ERP_API_URL",
            "settings": {"auth": {"apiToken": "must-not-store"}},
        },
    )
    assert nested_secret.status_code == 422


def test_source_online_validation_uses_environment_binding() -> None:
    client = TestClient(create_app(load_services=True, load_fixtures=True))
    client.post("/v0.1/studio/session/demo", json={"persona": "studio-admin"})
    response = client.post(
        "/v0.1/studio/source-profiles/orders_pg/validate",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": client.cookies["semaloom_csrf"],
        },
    )
    assert response.status_code == 200
    assert response.json()["validationStatus"] == "VALID"
    assert response.json()["reason"] == "READ_ONLY_CONNECTION_OK"


def test_arbitrary_environment_binding_is_resolved_server_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ERP_READ_API_URL", "https://erp.example.test")
    assert resolve_environment_binding("env:ERP_READ_API_URL", {}) == "https://erp.example.test"
    assert resolve_environment_binding("env:lowercase", {}) is None


def test_validation_approval_publish_and_edit_invalidation() -> None:
    services = build_services(load_data=True)
    for profile in services.source_profiles.list("tenant-a"):
        services.source_profiles.set_validation("tenant-a", profile.source_id, "VALID")
    snapshot = services.studio_drafts.load("tenant-a", "default")
    saved = services.studio_drafts.save(
        "tenant-a", "modeler", "default", list(snapshot.documents), snapshot.revision
    )
    history = services.studio_drafts.history("tenant-a", "default")
    assert [item["revision"] for item in history] == [saved.revision]
    historical = services.studio_drafts.load_revision("tenant-a", "default", saved.revision)
    assert historical.candidate_digest == saved.candidate_digest

    validation = services.studio_releases.validate("tenant-a", "modeler", "default", "dev")
    assert validation["status"] == "VALID"
    try:
        services.studio_releases.approve("tenant-a", "modeler", "default", "dev")
    except ReleaseGateError as exc:
        assert str(exc) == "INDEPENDENT_REVIEW_REQUIRED"
    else:
        raise AssertionError("the current draft author cannot approve their own candidate")
    approval = services.studio_releases.approve("tenant-a", "reviewer", "default", "dev")
    assert approval["candidateDigest"] == saved.candidate_digest
    _, environment_revision = services.studio_releases.pointer("tenant-a", "dev")
    source = services.source_profiles.get("tenant-a", "orders_pg")
    services.source_profiles.save(
        tenant="tenant-a",
        actor="source-admin",
        source_id=source.source_id,
        expected_revision=source.revision,
        label=source.label,
        provider=source.provider,
        binding_ref=source.binding_ref,
        secret_ref=source.secret_ref,
        settings=source.settings,
    )
    try:
        services.studio_releases.publish(
            "tenant-a", "publisher", "default", "dev", environment_revision
        )
    except ReleaseGateError as exc:
        assert str(exc) == "VALIDATION_REQUIRED"
    else:
        raise AssertionError("source changes must invalidate validation and approval")
    for profile in services.source_profiles.list("tenant-a"):
        services.source_profiles.set_validation("tenant-a", profile.source_id, "VALID")
    services.studio_releases.validate("tenant-a", "modeler", "default", "dev")
    try:
        services.studio_releases.publish(
            "tenant-a", "publisher", "default", "dev", environment_revision
        )
    except ReleaseGateError as exc:
        assert str(exc) == "APPROVAL_REQUIRED"
    else:
        raise AssertionError("a new validation must require a new approval")
    services.studio_releases.approve("tenant-a", "reviewer", "default", "dev")
    publication = services.studio_releases.publish(
        "tenant-a", "publisher", "default", "dev", environment_revision
    )
    assert publication["status"] == "ACTIVE"
    assert services.studio_releases.pointer("tenant-b", "dev") == (None, 0)
    assert services.studio_releases.history("tenant-a")[0]["digest"] == saved.candidate_digest

    documents = [dict(item) for item in saved.documents]
    order = next(item for item in documents if item["id"] == "procurement.Order")
    order["label"] = "Changed after approval"
    changed = services.studio_drafts.save(
        "tenant-a", "modeler", "default", documents, saved.revision
    )
    assert (
        services.studio_drafts.load_revision("tenant-a", "default", saved.revision).candidate_digest
        == saved.candidate_digest
    )
    assert changed.candidate_digest != saved.candidate_digest
    try:
        services.studio_releases.publish(
            "tenant-a", "publisher", "default", "dev", publication["environmentRevision"]
        )
    except ReleaseGateError as exc:
        assert str(exc) == "VALIDATION_REQUIRED"
    else:
        raise AssertionError("an approval for an older digest must not authorize publication")


def test_registry_refuses_unknown_release_activation() -> None:
    services = build_services(load_data=True)
    try:
        services.registry.activate("dev", "missing", expected_revision=1)
    except KeyError as exc:
        assert exc.args == ("missing",)
    else:
        raise AssertionError("unknown release activation must fail")


def test_studio_session_csrf_origin_capabilities_and_revocation() -> None:
    client = TestClient(create_app(load_services=True, load_fixtures=True))
    bearer_only = client.put(
        "/v0.1/studio/source-profiles/bypass",
        headers={"Authorization": "Bearer tenant-a-source-admin"},
        json={
            "expectedRevision": 0,
            "label": "Bypass",
            "provider": "postgres",
            "bindingRef": "env:BYPASS_URL",
            "settings": {},
        },
    )
    assert (bearer_only.status_code, bearer_only.json()["detail"]) == (
        401,
        "SESSION_REQUIRED",
    )
    login = client.post("/v0.1/studio/session/demo", json={"persona": "studio-admin"})
    assert login.status_code == 200
    assert "semaloom_session" in client.cookies
    current = client.get("/v0.1/studio/session")
    assert current.status_code == 200
    assert "publisher" in current.json()["roles"]

    draft = client.get("/v0.1/studio/drafts/default").json()
    rejected_origin = client.put(
        "/v0.1/studio/drafts/default",
        headers={"Origin": "https://forged.example"},
        json={"expectedRevision": draft["revision"], "documents": draft["documents"]},
    )
    assert (rejected_origin.status_code, rejected_origin.json()["detail"]) == (
        403,
        "INVALID_ORIGIN",
    )
    rejected_csrf = client.put(
        "/v0.1/studio/drafts/default",
        headers={"Origin": "http://testserver"},
        json={"expectedRevision": draft["revision"], "documents": draft["documents"]},
    )
    assert (rejected_csrf.status_code, rejected_csrf.json()["detail"]) == (
        403,
        "INVALID_CSRF",
    )

    csrf = client.cookies["semaloom_csrf"]
    trusted = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    saved = client.put(
        "/v0.1/studio/drafts/default",
        headers=trusted,
        json={"expectedRevision": draft["revision"], "documents": draft["documents"]},
    )
    assert saved.status_code == 200
    logout = client.delete("/v0.1/studio/session", headers=trusted)
    assert logout.status_code == 200
    assert client.get("/v0.1/studio/session").status_code == 401

    viewer = TestClient(create_app(load_services=True, load_fixtures=True))
    viewer.post("/v0.1/studio/session/demo", json={"persona": "viewer"})
    viewer_csrf = viewer.cookies["semaloom_csrf"]
    forbidden = viewer.put(
        "/v0.1/studio/source-profiles/viewer_source",
        headers={"Origin": "http://testserver", "X-CSRF-Token": viewer_csrf},
        json={
            "expectedRevision": 0,
            "label": "Viewer source",
            "provider": "postgres",
            "bindingRef": "env:VIEWER_SOURCE_URL",
            "settings": {},
        },
    )
    assert forbidden.status_code == 403
    sample_forbidden = viewer.post(
        "/v0.1/studio/sample",
        headers={"Origin": "http://testserver", "X-CSRF-Token": viewer_csrf},
        json={
            "objectId": "procurement.Order",
            "identity": "PO-001",
            "properties": ["status"],
        },
    )
    assert sample_forbidden.status_code == 403


def test_legacy_workspace_is_archived_and_migrated_to_canonical_documents() -> None:
    load_synthetic()
    engine = engines()["meta"]
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE studio_draft"))
        conn.execute(
            text(
                """
                CREATE TABLE studio_draft (
                  tenant_id TEXT NOT NULL, draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
                  payload JSONB NOT NULL, PRIMARY KEY (tenant_id, draft_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO studio_draft(tenant_id, draft_id, revision, payload)
                VALUES ('tenant-a', 'legacy', 3, CAST(:payload AS jsonb))
                """
            ),
            {"payload": '{"search":"old workspace state"}'},
        )
    services = build_services(load_data=False)
    try:
        snapshot = services.studio_drafts.load("tenant-a", "legacy")
        assert snapshot.revision == 3
        assert snapshot.candidate_digest == services.bundle.digest
        assert any(item["id"] == "procurement.Order" for item in snapshot.documents)
        with engine.connect() as conn:
            archived = conn.execute(
                text(
                    """
                    SELECT payload FROM studio_draft_legacy
                    WHERE tenant_id = 'tenant-a' AND draft_id = 'legacy' AND revision = 3
                    """
                )
            ).scalar_one()
        assert archived == {"search": "old workspace state"}
    finally:
        services.close()
        load_synthetic()

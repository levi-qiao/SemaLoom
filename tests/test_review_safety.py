"""Control-plane reads and fixture loading fail closed at their boundaries."""

import gc
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from semaloom.runtime.fixtures import LOCAL_URLS, load_synthetic
from semaloom.runtime.source_introspection import peek_source_rows


def test_preview_filters_tenant_even_when_column_is_not_displayed() -> None:
    columns = [f"c{i}" for i in range(24)] + ["tenant_id"]
    catalog = {
        "resources": [
            {"name": "records", "schema": "public", "columns": [{"name": c} for c in columns]}
        ]
    }
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value = []
    with (
        patch("semaloom.runtime.source_introspection.introspect_source", return_value=catalog),
        patch("semaloom.runtime.source_introspection.engine_from_url", return_value=engine),
    ):
        peek_source_rows("postgres", "unused", "records", "public", "tenant-a")
    statement, params = connection.execute.call_args.args
    assert "WHERE tenant_id = :tenant" in str(statement)
    assert params == {"tenant": "tenant-a"}


def test_preview_refuses_unknown_tenant_scope() -> None:
    catalog: dict[str, Any] = {
        "resources": [{"name": "records", "schema": "public", "columns": [{"name": "id"}]}]
    }
    with (
        patch("semaloom.runtime.source_introspection.introspect_source", return_value=catalog),
        patch("semaloom.runtime.source_introspection.engine_from_url") as connect,
    ):
        result = peek_source_rows("postgres", "unused", "records", "public", "tenant-a")
    assert result["rows"] == []
    assert result["reason"] == "TENANT_SCOPE_REQUIRED"
    connect.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pass@remote.example/semaloom_tax",
        "postgresql://user:pass@127.0.0.1/semaloom_samples",
        "postgresql://user:pass@127.0.0.1/business",
        "postgresql://user:pass@127.0.0.1/semaloom_tax?host=remote.example",
    ],
)
def test_fixture_target_is_checked_before_any_database_connect(url: str) -> None:
    urls = {**LOCAL_URLS, "meta": url}
    with patch("semaloom.runtime.fixtures.engines") as connect:
        with pytest.raises(ValueError, match="UNSAFE_FIXTURE_TARGET"):
            load_synthetic(urls)
    connect.assert_not_called()


def test_spec_import_rejects_unapproved_origins_redirects_and_large_bodies() -> None:
    import httpx

    from semaloom.adapters.spec_import import MAX_SPEC_BYTES, fetch_spec

    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/internal"})
        if request.url.path == "/large":
            return httpx.Response(200, content=b"x" * (MAX_SPEC_BYTES + 1))
        return httpx.Response(200, json={"openapi": "3.0.0"})

    def fetch(url: str) -> dict[str, Any]:
        return fetch_spec(
            url,
            allowed_origins=("https://approved.example",),
            headers={},
            params={},
            auth=None,
            transport=httpx.MockTransport(respond),
        )

    for url in (
        "http://169.254.169.254/internal",
        "https://approved.example.evil/spec",
        "https://user:secret@approved.example/spec",
    ):
        with pytest.raises(ValueError, match="SPEC_ORIGIN_NOT_ALLOWED"):
            fetch(url)
    assert seen == []
    with pytest.raises(ValueError, match="SPEC_REDIRECT_NOT_ALLOWED"):
        fetch("https://approved.example/redirect")
    assert len(seen) == 1
    with pytest.raises(ValueError, match="SPEC_TOO_LARGE"):
        fetch("https://approved.example/large")
    assert fetch("https://approved.example/spec")["spec"] == {"openapi": "3.0.0"}


def test_failed_activation_rolls_back_saved_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    from semaloom.app.bootstrap import build_services
    from semaloom.runtime.registry import StaleRevision

    services = build_services(load_data=True)
    try:
        before = services.studio_drafts.load("tenant-a", "default")
        documents = [dict(item) for item in before.documents]
        documents[0]["description"] = "must roll back"

        def fail(*args: Any, **kwargs: Any) -> int:
            raise StaleRevision("environment revision conflict")

        monkeypatch.setattr(services.registry, "activate_in", fail)
        with pytest.raises(StaleRevision):
            services.studio_releases.save_and_activate(
                "tenant-a", "modeler", "default", "dev", documents, before.revision
            )
        after = services.studio_drafts.load("tenant-a", "default")
        assert (after.revision, after.candidate_digest) == (
            before.revision,
            before.candidate_digest,
        )
    finally:
        services.close()


def test_request_keeps_source_binding_when_profile_is_changed() -> None:
    from semaloom.app.bootstrap import build_services
    from semaloom.runtime.auth import RequestActor
    from tests.test_runtime_pg import _metric_request

    services = build_services(load_data=True)
    actor = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
    try:
        pinned = services.query_active("tenant-a")
        profile = services.source_profiles.get("tenant-a", "tax_pg")
        services.source_profiles.save(
            tenant="tenant-a",
            actor="admin",
            source_id="tax_pg",
            expected_revision=profile.revision,
            label=profile.label,
            provider="postgres",
            binding_ref="env:UNCONFIGURED_REVIEW_SOURCE",
            secret_ref=None,
            settings={},
        )
        result = pinned.execute(
            _metric_request(
                "tax.reportedIncome",
                taxpayerId="TAXPAYER-A",
                taxYear=2024,
                perspective="TAX_RETURN",
            ),
            actor,
        )
        assert result.observations[0].kind == "PRESENT"
        assert result.source_activities[0].environment_binding_digest
        latest = services.query_active("tenant-a").execute(
            _metric_request(
                "tax.reportedIncome",
                taxpayerId="TAXPAYER-A",
                taxYear=2024,
                perspective="TAX_RETURN",
            ),
            actor,
        )
        assert latest.observations[0].kind == "UNAVAILABLE"
    finally:
        services.close()


def test_postgres_binding_snapshots_release_their_owned_pools() -> None:
    from semaloom.adapters.postgres import PostgresReadProvider

    root = PostgresReadProvider({})
    created: list[MagicMock] = []

    def build(url: str) -> MagicMock:
        engine = MagicMock()
        created.append(engine)
        return engine

    with patch("semaloom.adapters.postgres.engine_from_url", side_effect=build):
        for revision in range(65):
            pinned = root.bind_sources(
                "tenant-a", {"tax_pg": f"postgresql://localhost/revision-{revision}"}
            )
            assert pinned._engine("tax_pg", "tenant-a") is created[-1]
            del pinned
        gc.collect()

    assert len(created) == 65
    assert all(engine.dispose.called for engine in created)
    assert root._dynamic_engines == {}


def test_openapi_binding_snapshots_release_their_owned_clients() -> None:
    from semaloom.adapters.openapi import OpenApiReadProvider

    root = OpenApiReadProvider({})
    created: list[MagicMock] = []

    def build(**kwargs: Any) -> MagicMock:
        client = MagicMock()
        created.append(client)
        return client

    with patch("semaloom.adapters.openapi.httpx.Client", side_effect=build):
        for revision in range(65):
            pinned = root.bind_sources(
                "tenant-a", {"tax_api": f"https://example.test/revision-{revision}"}
            )
            assert pinned._client("tenant-a", "tax_api") is created[-1]
            del pinned
        gc.collect()

    assert len(created) == 65
    assert all(client.close.called for client in created)
    assert root._dynamic_clients == {}


def test_preview_endpoint_preserves_tenant_with_wide_real_table() -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from semaloom.app.factory import create_app
    from semaloom.runtime.fixtures import engines

    with TestClient(create_app(load_fixtures=True)) as client:
        client.post("/v0.1/studio/session/demo", json={"persona": "studio-admin"})
        pool = engines()
        engine = pool["orders_pg"]
        try:
            with engine.begin() as conn:
                columns = ", ".join(f"c{i} TEXT" for i in range(24))
                conn.execute(text(f"CREATE TABLE review_preview_scope ({columns}, tenant_id TEXT)"))
                conn.execute(
                    text(
                        "INSERT INTO review_preview_scope (c0,tenant_id) "
                        "VALUES ('visible','tenant-a'), ('hidden','tenant-b')"
                    )
                )
            result = client.post(
                "/v0.1/studio/source-profiles/orders_pg/rows",
                headers={
                    "Origin": "http://testserver",
                    "X-CSRF-Token": client.cookies["semaloom_csrf"],
                },
                json={"table": "review_preview_scope"},
            )
            assert result.status_code == 200
            assert [row["c0"] for row in result.json()["rows"]] == ["visible"]
            assert "tenant_id" not in result.json()["columns"]
        finally:
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS review_preview_scope"))
            for item in pool.values():
                item.dispose()


def test_concurrent_model_saves_publish_only_the_winning_revision() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from semaloom.app.bootstrap import build_services
    from semaloom.runtime.studio_control import RevisionConflict

    services = build_services(load_data=True)
    try:
        before = services.studio_drafts.load("tenant-a", "default")
        gate = Barrier(2)

        def save(label: str) -> str:
            documents = [dict(doc) for doc in before.documents]
            documents[0]["description"] = label
            gate.wait(timeout=5)
            try:
                snapshot, publication = services.studio_releases.save_and_activate(
                    "tenant-a", label, "default", "dev", documents, before.revision
                )
                assert publication["draftRevision"] == snapshot.revision
                assert publication["digest"] == snapshot.candidate_digest
                return publication["digest"]
            except RevisionConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save, ["first", "second"]))
        assert results.count("conflict") == 1
        winning = next(result for result in results if result != "conflict")
        assert services.studio_releases.pointer("tenant-a", "dev")[0] == winning
        assert services.studio_drafts.load("tenant-a", "default").candidate_digest == winning
        assert len(services.studio_releases.history("tenant-a")) == 1
    finally:
        services.close()

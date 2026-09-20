from __future__ import annotations

from pathlib import Path

import pytest

from semaloom.app.chat.tools import SemanticTools
from semaloom.core.model import MappingDef
from semaloom.core.provider import IdentityScalar, IdentityValue, ObjectRead, ObjectSearch
from semaloom.core.results import ObjectSelect, Observation, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService
from semaloom.runtime.studio import studio_mapping_preview
from semaloom.sdk import compile_documents

ROOT = Path(__file__).resolve().parents[1]
ACTOR = RequestActor(tenant="tenant-a", subject="reader", roles=("analyst",))


class FakeProvider:
    def __init__(self) -> None:
        self.identities: list[IdentityValue] = []
        self.rows: dict[tuple[str, str], str] = {
            ("0L", "E-1"): "Journal entry",
            ("0L", "E-2"): "Other entry",
        }

    @property
    def last_identity(self) -> IdentityValue | None:
        return self.identities[-1] if self.identities else None

    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
        bindings: dict[str, IdentityScalar] | None = None,
    ) -> Observation:
        raise AssertionError("metric read not expected")

    def fetch_object(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
    ) -> ObjectRead:
        self.identities.append(dict(identity_value))
        name = self.rows.get(
            (str(identity_value.get("ledger")), str(identity_value.get("entryId"))),
            "Journal entry",
        )
        return ObjectRead(
            kind="PRESENT",
            values={**identity_value, "name": name},
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            observed_at="2026-09-16T00:00:00Z",
        )

    def search_objects(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        filters: dict[str, object],
        properties: tuple[str, ...],
        limit: int,
    ) -> ObjectSearch:
        return ObjectSearch(
            kind="PRESENT",
            rows=({"ledger": "0L", "entryId": "E-1", "name": "Journal entry"},),
            observed_at="2026-09-16T00:00:00Z",
        )


def _documents() -> list[dict[str, object]]:
    return [
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "DomainPack",
            "id": "demo",
            "version": "1.0.0",
            "contractVersion": "v0.1",
            "namespace": "demo",
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "ObjectType",
            "id": "demo.Entry",
            "version": "1.0.0",
            "identityKeys": ["ledger", "entryId"],
            "properties": [
                {"id": "ledger", "valueType": "STRING", "required": True},
                {"id": "entryId", "valueType": "STRING", "required": True},
                {"id": "name", "valueType": "STRING"},
            ],
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Mapping",
            "id": "demo.Entry.pg",
            "version": "1.0.0",
            "target": "demo.Entry",
            "sourceId": "demo_pg",
            "provider": "postgres",
            "objectType": "demo.Entry",
            "expectedCardinality": "ONE",
            "physical": {
                "table": "entry",
                "grainColumns": {"ledger": "ledger", "entryId": "entry_id"},
                "propertyColumns": {"name": "name"},
            },
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "IntegrationBinding",
            "id": "demo.postgres",
            "version": "1.0.0",
            "provider": "postgres",
            "sourceId": "demo_pg",
            "mappings": ["demo.Entry.pg"],
        },
    ]


def _bundle():
    result = compile_documents(_documents())
    assert result.ok, result.diagnostics
    assert result.bundle is not None
    return result.bundle


def test_compiler_emits_neutral_mapping_ir() -> None:
    mapping = _bundle().mappings[0]
    assert mapping.identity_fields == ("ledger", "entryId")
    assert mapping.grain_fields == ("ledger", "entryId")
    assert mapping.property_fields == ("name",)
    assert mapping.capabilities == ("POINT_READ", "COLLECTION_READ", "EQUI_JOIN")


@pytest.mark.parametrize(
    "legacy_field",
    (
        "identityColumn",
        "identityColumns",
        "identityParameter",
        "identityParameters",
        "identityPointer",
        "identityPointers",
    ),
)
def test_compiler_rejects_legacy_identity_mapping_fields(legacy_field: str) -> None:
    docs = _documents()
    mapping = next(item for item in docs if item.get("kind") == "Mapping")
    physical = dict(mapping["physical"])
    physical[legacy_field] = "legacy_identity_binding"
    mapping["physical"] = physical
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "LEGACY_MAPPING_FIELD" for item in result.diagnostics)


def test_query_studio_and_ai_share_exact_composite_identity() -> None:
    bundle = _bundle()
    provider = FakeProvider()
    query = QueryService(bundle, provider)
    identity = {"ledger": "0L", "entryId": "E-1"}
    envelope = query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                ObjectSelect(object_type="demo.Entry", identity=identity, properties=("name",)),
            ),
            context=QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"}),
        ),
        ACTOR,
    )
    assert envelope.status == "SUCCEEDED"
    assert provider.last_identity == identity

    preview = studio_mapping_preview(
        bundle,
        provider,
        mapping_id="demo.Entry.pg",
        tenant="tenant-a",
        identity=identity,
    )
    assert preview is not None
    assert preview["kind"] == "PRESENT"
    assert preview["identity"] == identity

    tools = SemanticTools(query, ACTOR)
    found = tools.call(
        "find_objects",
        {
            "objectType": "demo.Entry",
            "filters": {"name": "Journal entry"},
            "properties": ["name"],
        },
    )
    assert found["objects"][0]["identity"] == identity
    tools.call(
        "semantic_query",
        {
            "apiVersion": "semaloom/v0.1",
            "select": [
                {
                    "objectType": "demo.Entry",
                    "identity": identity,
                    "properties": ["name"],
                }
            ],
            "context": {"businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"}},
        },
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_IDENTITY"):
        tools.call(
            "semantic_query",
            {
                "apiVersion": "semaloom/v0.1",
                "select": [
                    {
                        "objectType": "demo.Entry",
                        "identity": {"entryId": "E-1"},
                        "properties": ["name"],
                    }
                ],
                "context": {"businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"}},
            },
        )


def test_same_first_key_different_second_key_never_cross_objects() -> None:
    """Maturity P0 evidence: shared first key must not select the sibling object."""
    import json

    bundle = _bundle()
    provider = FakeProvider()
    query = QueryService(bundle, provider)
    period = QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"})
    first = query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                ObjectSelect(
                    object_type="demo.Entry",
                    identity={"ledger": "0L", "entryId": "E-1"},
                    properties=("name",),
                ),
            ),
            context=period,
        ),
        ACTOR,
    )
    second = query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                ObjectSelect(
                    object_type="demo.Entry",
                    identity={"ledger": "0L", "entryId": "E-2"},
                    properties=("name",),
                ),
            ),
            context=period,
        ),
        ACTOR,
    )
    assert first.status == "SUCCEEDED" and second.status == "SUCCEEDED"
    assert provider.identities == [
        {"ledger": "0L", "entryId": "E-1"},
        {"ledger": "0L", "entryId": "E-2"},
    ]
    assert json.loads(first.observations[0].value or "{}") == {"name": "Journal entry"}
    assert json.loads(second.observations[0].value or "{}") == {"name": "Other entry"}


def test_postgres_same_first_key_uses_full_composite_where() -> None:
    import json

    from sqlalchemy import create_engine, text

    from semaloom.adapters.postgres import PostgresReadProvider
    from semaloom.runtime.fixtures import engines

    engine = engines()["tax_pg"]
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA composite_identity_pg"))
        conn.execute(text("SET search_path TO composite_identity_pg"))
        conn.execute(
            text(
                """
                CREATE TABLE entry (
                  tenant_id TEXT,
                  ledger TEXT,
                  entry_id TEXT,
                  name TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO entry (tenant_id, ledger, entry_id, name) VALUES
                ('tenant-a', '0L', 'E-1', 'Journal entry'),
                ('tenant-a', '0L', 'E-2', 'Other entry')
                """
            )
        )
        conn.commit()
        read_engine = create_engine(
            engine.url, connect_args={"options": "-csearch_path=composite_identity_pg"}
        )
        try:
            query = QueryService(_bundle(), PostgresReadProvider({"demo_pg": read_engine}))
            period = QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"})
            first = query.execute(
                QueryRequest(
                    api_version="semaloom/v0.1",
                    select=(
                        ObjectSelect(
                            object_type="demo.Entry",
                            identity={"ledger": "0L", "entryId": "E-1"},
                            properties=("name",),
                        ),
                    ),
                    context=period,
                ),
                ACTOR,
            )
            second = query.execute(
                QueryRequest(
                    api_version="semaloom/v0.1",
                    select=(
                        ObjectSelect(
                            object_type="demo.Entry",
                            identity={"ledger": "0L", "entryId": "E-2"},
                            properties=("name",),
                        ),
                    ),
                    context=period,
                ),
                ACTOR,
            )
            assert first.status == "SUCCEEDED"
            assert second.status == "SUCCEEDED"
            assert json.loads(first.observations[0].value or "{}") == {"name": "Journal entry"}
            assert json.loads(second.observations[0].value or "{}") == {"name": "Other entry"}
        finally:
            read_engine.dispose()
            with engine.connect() as cleanup:
                cleanup.execute(text("DROP SCHEMA IF EXISTS composite_identity_pg CASCADE"))
                cleanup.commit()


def test_ai_object_identity_rejects_extra_components() -> None:
    bundle = _bundle()
    provider = FakeProvider()
    tools = SemanticTools(QueryService(bundle, provider), ACTOR)
    tools.call(
        "find_objects",
        {
            "objectType": "demo.Entry",
            "filters": {"name": "Journal entry"},
            "properties": ["name"],
        },
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_IDENTITY"):
        tools.call(
            "semantic_query",
            {
                "apiVersion": "semaloom/v0.1",
                "select": [
                    {
                        "objectType": "demo.Entry",
                        "identity": {
                            "ledger": "0L",
                            "entryId": "E-1",
                            "extra": "x",
                        },
                        "properties": ["name"],
                    }
                ],
                "context": {
                    "businessPeriod": {
                        "from": "2024-01-01",
                        "to": "2025-01-01",
                    }
                },
            },
        )


def test_frontend_editor_has_no_legacy_identity_mapping_fields() -> None:
    editor = (ROOT / "frontend/src/MappingEditor.tsx").read_text()
    forbidden = (
        "identityColumn",
        "identityColumns",
        "identityPointer",
        "identityPointers",
        "identityParameter",
    )
    assert all(token not in editor for token in forbidden)


def test_partial_composite_identity_is_rejected_by_postgres_adapter() -> None:
    from semaloom.adapters.postgres import _identity_columns

    mapping = _bundle().mappings[0]
    with pytest.raises(ValueError, match="identity does not match"):
        _identity_columns(mapping, {"ledger": "0L"})
    columns = _identity_columns(mapping, {"ledger": "0L", "entryId": "E-1"})
    assert columns == {"ledger": "ledger", "entryId": "entry_id"}


def test_action_draft_store_keeps_same_first_key_targets_distinct() -> None:
    from semaloom.runtime.action import DraftStore

    store = DraftStore()
    first = store.create(
        idempotency_key="plan-1",
        payload={"target": {"org": "A", "orderId": "1"}, "parameters": {"amount": "1"}},
    )
    second = store.create(
        idempotency_key="plan-2",
        payload={"target": {"org": "A", "orderId": "2"}, "parameters": {"amount": "1"}},
    )
    assert first != second
    assert store.writes == 2
    assert store.get({"org": "A", "orderId": "1"})["payload"]["target"] == {
        "org": "A",
        "orderId": "1",
    }
    assert store.get({"org": "A", "orderId": "2"})["payload"]["target"] == {
        "org": "A",
        "orderId": "2",
    }
    replay = store.create(
        idempotency_key="plan-1",
        payload={"target": {"org": "A", "orderId": "1"}, "parameters": {"amount": "1"}},
    )
    assert replay == first
    assert store.writes == 2


def test_action_execute_persists_full_structured_target(monkeypatch: pytest.MonkeyPatch) -> None:
    from semaloom.app.bootstrap import build_services
    from semaloom.runtime.auth import RequestActor

    services = build_services(load_data=True)
    captured: dict[str, object] = {}
    original_create = services.drafts.create

    def capture_create(*, idempotency_key: str, payload: dict, expected_version=None):
        captured["payload"] = payload
        return original_create(
            idempotency_key=idempotency_key,
            payload=payload,
            expected_version=expected_version,
        )

    monkeypatch.setattr(services.drafts, "create", capture_create)
    analyst = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
    approver = RequestActor(tenant="tenant-a", subject="bob", roles=("approver", "analyst"))
    plan = services.actions.plan(
        analyst,
        action_id="tax.CreateTaxAdjustmentDraft",
        target={"taxpayerId": "TAXPAYER-A"},
        parameters={"amount": "10.00", "taxYear": "2024"},
    )
    services.actions.approve(approver, plan.plan_id)
    services.actions.execute(analyst, plan.plan_id)
    assert captured["payload"]["target"] == {"taxpayerId": "TAXPAYER-A"}

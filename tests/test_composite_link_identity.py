from __future__ import annotations

from semaloom.compiler.api import compile_documents
from semaloom.core.model import MappingDef
from semaloom.core.provider import IdentityScalar, IdentityValue, ObjectRead, ObjectSearch
from semaloom.core.results import Observation
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService

ACTOR = RequestActor(tenant="tenant-a", subject="reader", roles=("analyst",))


class LinkProvider:
    def __init__(self) -> None:
        self.identities: list[IdentityValue] = []

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
        if mapping.target == "demo.Entry":
            values = {
                **identity_value,
                "targetLedger": "0L",
                "targetAccount": "A-7",
            }
        else:
            values = {**identity_value, "name": "Cash"}
        return ObjectRead(
            kind="PRESENT",
            values=values,
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            observed_at="2026-09-17T00:00:00Z",
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
        raise AssertionError("search not expected")


def documents() -> list[dict[str, object]]:
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
                {"id": "targetLedger", "valueType": "STRING"},
                {"id": "targetAccount", "valueType": "STRING"},
            ],
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "ObjectType",
            "id": "demo.Account",
            "version": "1.0.0",
            "identityKeys": ["ledger", "accountId"],
            "properties": [
                {"id": "ledger", "valueType": "STRING", "required": True},
                {"id": "accountId", "valueType": "STRING", "required": True},
                {"id": "name", "valueType": "STRING"},
            ],
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Link",
            "id": "demo.entryAccount",
            "version": "1.0.0",
            "source": "demo.Entry",
            "target": "demo.Account",
            "identity": [
                {"source": "targetLedger", "target": "ledger"},
                {"source": "targetAccount", "target": "accountId"},
            ],
            "cardinality": "ONE",
            "traversal": "FORWARD",
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
                "propertyColumns": {
                    "targetLedger": "account_ledger",
                    "targetAccount": "account_id",
                },
            },
        },
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Mapping",
            "id": "demo.Account.pg",
            "version": "1.0.0",
            "target": "demo.Account",
            "sourceId": "demo_pg",
            "provider": "postgres",
            "objectType": "demo.Account",
            "expectedCardinality": "ONE",
            "physical": {
                "table": "account",
                "grainColumns": {"ledger": "ledger", "accountId": "account_id"},
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
            "mappings": ["demo.Entry.pg", "demo.Account.pg"],
        },
    ]


def bundle():
    result = compile_documents(documents())
    assert result.ok, result.diagnostics
    assert result.bundle is not None
    return result.bundle


def test_composite_link_preserves_full_target_identity() -> None:
    provider = LinkProvider()
    query = QueryService(bundle(), provider)
    envelope = query.follow_link(
        link_id="demo.entryAccount",
        source_identity={"ledger": "0L", "entryId": "E-1"},
        actor=ACTOR,
    )
    assert envelope.status == "SUCCEEDED"
    assert provider.identities == [
        {"ledger": "0L", "entryId": "E-1"},
        {"ledger": "0L", "accountId": "A-7"},
    ]
    assert envelope.observations[0].bindings == {"ledger": "0L", "accountId": "A-7"}
    assert envelope.extras["targetIdentity"] == {"ledger": "0L", "accountId": "A-7"}


def test_link_must_cover_every_target_identity_component() -> None:
    docs = documents()
    link = next(item for item in docs if item["kind"] == "Link")
    link["identity"] = [{"source": "targetAccount", "target": "accountId"}]
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "MISSING_LINK_IDENTITY" for item in result.diagnostics)


def test_old_scalar_link_identity_shape_is_rejected() -> None:
    docs = documents()
    link = next(item for item in docs if item["kind"] == "Link")
    link["identity"] = {"source": "targetAccount", "target": "accountId"}
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "INVALID_DEFINITION" for item in result.diagnostics)


def test_discovery_does_not_advertise_collection_join_for_composite_links() -> None:
    from semaloom.runtime.auth import RequestActor
    from semaloom.runtime.discovery import SemanticDiscovery

    actor = RequestActor(tenant="tenant-a", subject="reader", roles=("analyst",))
    described = SemanticDiscovery(bundle()).describe("demo.entryAccount", actor)
    assert described["analysisCapabilities"]["pointLookup"] is True
    assert described["analysisCapabilities"]["collectionJoin"] is False


def test_studio_emitted_pair_array_covers_every_target_identity_key() -> None:
    """Studio create emits pair arrays covering every target identity key."""
    docs = documents()
    link = next(item for item in docs if item["kind"] == "Link")
    target = next(item for item in docs if item["id"] == "demo.Account")
    assert isinstance(link["identity"], list)
    assert {pair["target"] for pair in link["identity"]} == set(target["identityKeys"])
    assert len(link["identity"]) == len(target["identityKeys"])
    result = compile_documents(docs)
    assert result.ok, result.diagnostics

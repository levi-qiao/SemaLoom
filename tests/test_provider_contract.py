from __future__ import annotations

from typing import NoReturn

from semaloom.app.bootstrap import compile_examples
from semaloom.core.model import MappingDef
from semaloom.core.provider import ObjectRead
from semaloom.core.results import (
    ObjectSelect,
    Observation,
    QueryContext,
    QueryRequest,
)
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService

ACTOR = RequestActor(tenant="tenant-a", subject="reader", roles=("analyst",))


class UnavailableObjectProvider:
    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: str,
        extra_filters: dict[str, str] | None = None,
    ) -> Observation:
        raise AssertionError("metric read was not expected")

    def fetch_object(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: str,
    ) -> ObjectRead:
        return ObjectRead(
            kind="UNAVAILABLE",
            reason="PROVIDER_ERROR",
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            observed_at="2026-09-11T00:00:00Z",
        )


class NeverReadProvider(UnavailableObjectProvider):
    def fetch_object(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: str,
    ) -> NoReturn:
        raise AssertionError("ambiguous mapping must fail before source access")


def _object_request(*, properties: tuple[str, ...] = ()) -> QueryRequest:
    return QueryRequest(
        api_version="semaloom/v0.1",
        select=(
            ObjectSelect(
                object_type="procurement.Order",
                identity={"orderId": "PO-001"},
                properties=properties,
            ),
        ),
        context=QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"}),
    )


def test_object_provider_failure_is_not_reported_as_missing() -> None:
    envelope = QueryService(compile_examples(), UnavailableObjectProvider()).execute(
        _object_request(), ACTOR
    )

    assert envelope.status == "FAILED"
    assert envelope.observations[0].kind == "UNAVAILABLE"
    assert envelope.diagnostics[0].code == "PROVIDER_ERROR"


def test_runtime_rejects_ambiguous_object_mapping_before_source_access() -> None:
    bundle = compile_examples()
    original = next(item for item in bundle.mappings if item.target == "procurement.Order")
    duplicate = original.model_copy(update={"id": f"{original.id}.alternate"})
    ambiguous = bundle.model_copy(update={"mappings": (*bundle.mappings, duplicate)})

    envelope = QueryService(ambiguous, NeverReadProvider()).execute(_object_request(), ACTOR)

    assert envelope.status == "FAILED"
    assert envelope.observations[0].reason == "AMBIGUOUS_MAPPING"
    assert envelope.diagnostics[0].code == "AMBIGUOUS_MAPPING"


def test_runtime_rejects_unknown_object_property_before_source_access() -> None:
    envelope = QueryService(compile_examples(), NeverReadProvider()).execute(
        _object_request(properties=("physical_secret",)), ACTOR
    )

    assert envelope.status == "FAILED"
    assert envelope.observations[0].reason == "INVALID_BINDINGS"

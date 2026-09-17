from __future__ import annotations

import json
from typing import Any

import httpx

from semaloom.adapters.composite import CompositeReadProvider
from semaloom.adapters.openapi import OpenApiReadProvider
from semaloom.app.bootstrap import compile_examples
from semaloom.core.model import MappingDef
from semaloom.core.provider import IdentityScalar, IdentityValue, ObjectRead
from semaloom.core.results import (
    ObjectSelect,
    Observation,
    QueryContext,
    QueryRequest,
)
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService

ACTOR = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))


class PgOrderProvider:
    def fetch_object(
        self, mapping: MappingDef, *, tenant: str, identity_value: IdentityValue
    ) -> ObjectRead:
        return ObjectRead(
            kind="PRESENT",
            values={"orderId": identity_value["orderId"], "status": "APPROVED"},
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            observed_at="2026-01-01T00:00:00Z",
        )

    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
        bindings: dict[str, IdentityScalar] | None = None,
    ) -> Observation:
        raise AssertionError("metric access is not expected")


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(
        base_url="https://source.test", transport=httpx.MockTransport(handler), timeout=0.1
    )


def _object_mapping(**physical: Any) -> MappingDef:
    return MappingDef.model_validate(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Mapping",
            "id": "procurement.Order.apiTest",
            "version": "1.0.0",
            "target": "procurement.Order",
            "sourceId": "api",
            "provider": "openapi",
            "objectType": "procurement.Order",
            "expectedCardinality": "ONE",
            "identityFields": ["orderId"],
            "grainFields": ["orderId"],
            "propertyFields": ["deliveryRisk"],
            "capabilities": ["POINT_READ"],
            "physical": {
                "method": "GET",
                "path": "/orders",
                "parameterBindings": {"orderId": "orderId"},
                "grainPointers": {"orderId": "/orderId"},
                "propertyPointers": {"deliveryRisk": "/deliveryRisk"},
                **physical,
            },
        }
    )


def test_query_composes_postgres_and_api_properties_with_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["orderId"] == "PO-001"
        assert request.url.params["tenant"] == "tenant-a"
        return httpx.Response(200, json={"orderId": "PO-001", "deliveryRisk": "LOW"})

    provider = CompositeReadProvider(
        {
            "postgres": PgOrderProvider(),
            "openapi": OpenApiReadProvider({"proc_draft_api": _client(handler)}),
        }
    )
    envelope = QueryService(compile_examples(), provider).execute(
        QueryRequest(
            apiVersion="semaloom/v0.1",
            select=(
                ObjectSelect(
                    objectType="procurement.Order",
                    identity={"orderId": "PO-001"},
                    properties=("status", "deliveryRisk"),
                ),
            ),
            context=QueryContext(
                businessPeriod={"from": "2026-01-01", "to": "2027-01-01"}
            ),
        ),
        ACTOR,
    )

    assert envelope.status == "SUCCEEDED"
    assert json.loads(envelope.observations[0].value or "{}") == {
        "deliveryRisk": "LOW",
        "status": "APPROVED",
    }
    assert {item.source_id for item in envelope.source_activities} == {
        "orders_pg",
        "proc_draft_api",
    }


def test_api_object_failure_matrix() -> None:
    cases = [
        (lambda request: httpx.Response(404), "MISSING", "NO_ROW"),
        (
            lambda request: httpx.Response(
                200,
                json=[
                    {"orderId": "PO-001", "deliveryRisk": "LOW"},
                    {"orderId": "PO-001", "deliveryRisk": "HIGH"},
                ],
            ),
            "UNAVAILABLE",
            "CARDINALITY_VIOLATION",
        ),
        (
            lambda request: httpx.Response(
                200,
                json={"orderId": "WRONG", "deliveryRisk": "LOW"},
            ),
            "UNAVAILABLE",
            "IDENTITY_MISMATCH",
        ),
        (
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("late")),
            "UNAVAILABLE",
            "SOURCE_TIMEOUT",
        ),
    ]
    for handler, kind, reason in cases:
        result = OpenApiReadProvider({"api": _client(handler)}).fetch_object(
            _object_mapping(), tenant="tenant-a", identity_value={"orderId": "PO-001"}
        )
        assert (result.kind, result.reason) == (kind, reason)

    incomplete = OpenApiReadProvider(
        {
            "api": _client(
                lambda request: httpx.Response(
                    200,
                    json={
                        "items": [{"orderId": "PO-001", "deliveryRisk": "LOW"}],
                        "next": "cursor",
                    },
                )
            )
        }
    ).fetch_object(
        _object_mapping(recordsPointer="/items", nextPointer="/next"),
        tenant="tenant-a",
        identity_value={"orderId": "PO-001"},
    )
    assert (incomplete.kind, incomplete.reason) == ("UNAVAILABLE", "INCOMPLETE_PAGE")


def test_api_null_property_and_exact_decimal() -> None:
    null_result = OpenApiReadProvider(
        {
            "api": _client(
                lambda request: httpx.Response(
                    200, json={"orderId": "PO-001", "deliveryRisk": None}
                )
            )
        }
    ).fetch_object(
        _object_mapping(),
        tenant="tenant-a",
        identity_value={"orderId": "PO-001"},
    )
    assert null_result.kind == "PRESENT"
    assert null_result.values["deliveryRisk"] is None

    mapping = _object_mapping(valuePointer="/amount").model_copy(
        update={
            "id": "procurement.orderAmount.apiTest",
            "target": "procurement.orderAmount",
        }
    )
    exact = OpenApiReadProvider(
        {
            "api": _client(
                lambda request: httpx.Response(
                    200,
                    json={"orderId": "PO-001", "amount": "1234567890.0100"},
                )
            )
        }
    ).fetch_metric(
        mapping,
        tenant="tenant-a",
        identity_value={"orderId": "PO-001"},
    )
    assert (exact.kind, exact.value) == ("PRESENT", "1234567890.0100")

    inexact = OpenApiReadProvider(
        {
            "api": _client(
                lambda request: httpx.Response(
                    200, json={"orderId": "PO-001", "amount": 1.1}
                )
            )
        }
    ).fetch_metric(
        mapping,
        tenant="tenant-a",
        identity_value={"orderId": "PO-001"},
    )
    assert (inexact.kind, inexact.reason) == ("UNAVAILABLE", "INEXACT_NUMBER")

    non_finite = OpenApiReadProvider(
        {
            "api": _client(
                lambda request: httpx.Response(
                    200,
                    json={"orderId": "PO-001", "amount": "NaN"},
                )
            )
        }
    ).fetch_metric(
        mapping,
        tenant="tenant-a",
        identity_value={"orderId": "PO-001"},
    )
    assert (non_finite.kind, non_finite.reason) == (
        "UNAVAILABLE",
        "NON_FINITE_NUMBER",
    )


def test_api_caller_filters_cannot_override_tenant_or_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["tenant"] == "tenant-a"
        assert request.url.params["orderId"] == "PO-001"
        return httpx.Response(200, json={"orderId": "PO-001", "amount": "1.00"})

    mapping = _object_mapping(valuePointer="/amount").model_copy(
        update={
            "id": "procurement.orderAmount.apiTest",
            "target": "procurement.orderAmount",
        }
    )
    result = OpenApiReadProvider({"api": _client(handler)}).fetch_metric(
        mapping,
        tenant="tenant-a",
        identity_value={"orderId": "PO-001"},
        bindings={"orderId": "PO-999"},
    )
    assert (result.kind, result.reason) == ("UNAVAILABLE", "INVALID_BINDINGS")

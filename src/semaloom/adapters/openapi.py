"""Bounded read-only HTTP adapter for approved OpenAPI operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from threading import RLock
from typing import Any
from weakref import finalize

import httpx

from semaloom.core.model import MappingDef
from semaloom.core.provider import IdentityScalar, IdentityValue, ObjectRead, ObjectSearch
from semaloom.core.results import Observation


class OpenApiReadProvider:
    """Execute only GET mappings; URLs and response pointers come from releases."""

    def __init__(
        self,
        clients: dict[str, httpx.Client],
        base_url_resolver: Callable[[str, str], str | None] | None = None,
    ) -> None:
        self._clients = clients
        self._base_url_resolver = base_url_resolver
        self._dynamic_clients: dict[tuple[str, str, str], httpx.Client] = {}
        self._pool_lock = RLock()
        self._pool_finalizer = finalize(
            self, _close_dynamic_clients, self._dynamic_clients, self._pool_lock
        )

    def bind_sources(self, tenant: str, urls: dict[str, str]) -> OpenApiReadProvider:
        """Freeze destinations in a snapshot that owns its temporary clients."""
        destinations = dict(urls)
        return OpenApiReadProvider(
            {},
            lambda caller, source: destinations.get(source) if caller == tenant else None,
        )

    def fetch_object(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
    ) -> ObjectRead:
        observed = _now()
        outcome = self._get(mapping, tenant=tenant, identity_value=identity_value)
        if isinstance(outcome, str):
            return ObjectRead(
                kind="MISSING" if outcome == "NO_ROW" else "UNAVAILABLE",
                reason=outcome,
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        record, error = _single_record(outcome, mapping.physical)
        if error is not None:
            return ObjectRead(
                kind="MISSING" if error == "NO_ROW" else "UNAVAILABLE",
                reason=error,
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        assert record is not None
        try:
            pointers = _identity_pointers(mapping, identity_value)
        except ValueError:
            return ObjectRead(
                kind="UNAVAILABLE",
                reason="INVALID_MAPPING",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        if any(
            str(_pointer(record, pointers[key])) != str(value)
            for key, value in identity_value.items()
        ):
            return ObjectRead(
                kind="UNAVAILABLE",
                reason="IDENTITY_MISMATCH",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        property_pointers = mapping.physical.get("propertyPointers", {})
        if not isinstance(property_pointers, dict):
            property_pointers = {}
        values = {
            str(key): _pointer(record, str(pointer)) for key, pointer in property_pointers.items()
        }
        grain = mapping.physical.get("grainPointers", {})
        if isinstance(grain, dict):
            values.update(
                {str(key): _pointer(record, str(pointer)) for key, pointer in grain.items()}
            )
        return ObjectRead(
            kind="PRESENT",
            values=values,
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            observed_at=observed,
        )

    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
        bindings: dict[str, IdentityScalar] | None = None,
    ) -> Observation:
        observed = _now()
        outcome = self._get(
            mapping,
            tenant=tenant,
            identity_value=identity_value,
            bindings=bindings,
        )
        if isinstance(outcome, str):
            return _metric_outcome(mapping, observed, outcome)
        record, error = _single_record(outcome, mapping.physical)
        if error is not None:
            return _metric_outcome(mapping, observed, error)
        assert record is not None
        try:
            pointers = _identity_pointers(mapping, identity_value)
        except ValueError:
            return _metric_outcome(mapping, observed, "INVALID_MAPPING")
        if any(
            str(_pointer(record, pointers[key])) != str(value)
            for key, value in identity_value.items()
        ):
            return _metric_outcome(mapping, observed, "IDENTITY_MISMATCH")
        raw = _pointer(record, str(mapping.physical.get("valuePointer", "/value")))
        if raw is None:
            return Observation(
                kind="NULL",
                target=mapping.target,
                reason="NULL_INPUT",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        if isinstance(raw, float):
            return _metric_outcome(mapping, observed, "INEXACT_NUMBER")
        try:
            decimal_value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return _metric_outcome(mapping, observed, "TYPE_MISMATCH")
        if not decimal_value.is_finite():
            return _metric_outcome(mapping, observed, "NON_FINITE_NUMBER")
        value = format(decimal_value, "f")
        return Observation(
            kind="PRESENT",
            target=mapping.target,
            value=value,
            value_type="DECIMAL",
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            observed_at=observed,
        )

    def _get(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
        bindings: dict[str, IdentityScalar] | None = None,
    ) -> Any | str:
        if str(mapping.physical.get("method", "GET")).upper() != "GET":
            return "READ_METHOD_REQUIRED"
        if set(identity_value) != set(mapping.identity_fields):
            return "INVALID_MAPPING"
        client = self._client(tenant, mapping.source_id)
        path = mapping.physical.get("path")
        if (
            client is None
            or not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
        ):
            return "PROVIDER_NOT_CONFIGURED"
        parameter_bindings = mapping.physical.get("parameterBindings")
        if not isinstance(parameter_bindings, dict):
            return "INVALID_MAPPING"
        params: dict[str, Any] = {
            **dict(mapping.physical.get("fixedParameters") or {}),
            "tenant": tenant,
        }
        binding_values = bindings or {}
        if set(identity_value) & set(binding_values):
            return "INVALID_BINDINGS"
        semantic_values: dict[str, IdentityScalar] = {
            **identity_value,
            **binding_values,
        }
        for semantic, value in semantic_values.items():
            parameter = parameter_bindings.get(semantic)
            if (
                not isinstance(parameter, str)
                or not parameter
                or parameter == "tenant"
                or parameter in params
            ):
                return "INVALID_MAPPING"
            params[parameter] = value
        try:
            response = client.get(path, params=params)
        except httpx.TimeoutException:
            return "SOURCE_TIMEOUT"
        except httpx.HTTPError:
            return "PROVIDER_ERROR"
        if response.status_code == 404:
            return "NO_ROW"
        if response.status_code < 200 or response.status_code >= 300:
            return "PROVIDER_ERROR"
        try:
            return response.json()
        except ValueError:
            return "INVALID_RESPONSE"

    def search_objects(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        filters: dict[str, Any],
        properties: tuple[str, ...],
        limit: int,
    ) -> ObjectSearch:
        return ObjectSearch(kind="UNAVAILABLE", reason="SEARCH_NOT_SUPPORTED", observed_at=_now())

    def close(self) -> None:
        for client in set(self._clients.values()):
            client.close()
        _close_dynamic_clients(self._dynamic_clients, self._pool_lock)

    def _client(self, tenant: str, source_id: str) -> httpx.Client | None:
        if self._base_url_resolver is not None:
            base_url = self._base_url_resolver(tenant, source_id)
            if base_url is not None:
                key = (tenant, source_id, base_url)
                with self._pool_lock:
                    client = self._dynamic_clients.get(key)
                    if client is None:
                        if len(self._dynamic_clients) >= 64:
                            return None
                        client = httpx.Client(base_url=base_url, timeout=5.0)
                        self._dynamic_clients[key] = client
                    return client
        return self._clients.get(source_id)


def _close_dynamic_clients(clients: dict[tuple[str, str, str], httpx.Client], lock: RLock) -> None:
    with lock:
        owned = tuple(clients.values())
        clients.clear()
    for client in owned:
        client.close()


def _identity_pointers(mapping: MappingDef, identity_value: IdentityValue) -> dict[str, str]:
    if set(identity_value) != set(mapping.identity_fields):
        raise ValueError("identity does not match compiled mapping")
    grain = mapping.physical.get("grainPointers")
    if not isinstance(grain, dict):
        raise ValueError("grainPointers must be an object")
    pointers: dict[str, str] = {}
    for semantic in mapping.identity_fields:
        pointer = grain.get(semantic)
        if not isinstance(pointer, str) or not pointer:
            raise ValueError("invalid identity pointer")
        pointers[semantic] = pointer
    return pointers


def _single_record(
    payload: Any, physical: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    next_pointer = physical.get("nextPointer")
    if isinstance(next_pointer, str) and _pointer(payload, next_pointer) not in (None, "", False):
        return None, "INCOMPLETE_PAGE"
    records_pointer = physical.get("recordsPointer")
    value = _pointer(payload, str(records_pointer)) if isinstance(records_pointer, str) else payload
    records = value if isinstance(value, list) else [value]
    if not records or records == [None]:
        return None, "NO_ROW"
    if len(records) != 1:
        return None, "CARDINALITY_VIOLATION"
    if not isinstance(records[0], dict):
        return None, "INVALID_RESPONSE"
    return records[0], None


def _pointer(value: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return value
    current = value
    for token in pointer.removeprefix("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        else:
            return None
    return current


def _metric_outcome(mapping: MappingDef, observed: str, reason: str) -> Observation:
    return Observation(
        kind="MISSING" if reason == "NO_ROW" else "UNAVAILABLE",
        target=mapping.target,
        reason=reason,
        mapping_id=mapping.id,
        source_id=mapping.source_id,
        observed_at=observed,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()

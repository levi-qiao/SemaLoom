"""Provider routing kept at the integration boundary."""

from __future__ import annotations

from semaloom.core.model import MappingDef
from semaloom.core.provider import ObjectRead, ReadProvider
from semaloom.core.results import Observation


class CompositeReadProvider:
    """Dispatch an approved mapping to its protocol adapter."""

    def __init__(self, providers: dict[str, ReadProvider]) -> None:
        self._providers = providers

    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: str,
        extra_filters: dict[str, str] | None = None,
    ) -> Observation:
        provider = self._providers.get(mapping.provider)
        if provider is None:
            return Observation(
                kind="UNAVAILABLE",
                target=mapping.target,
                reason="PROVIDER_NOT_CONFIGURED",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
            )
        return provider.fetch_metric(
            mapping,
            tenant=tenant,
            identity_value=identity_value,
            extra_filters=extra_filters,
        )

    def fetch_object(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: str,
    ) -> ObjectRead:
        provider = self._providers.get(mapping.provider)
        if provider is None:
            return ObjectRead(
                kind="UNAVAILABLE",
                reason="PROVIDER_NOT_CONFIGURED",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at="",
            )
        return provider.fetch_object(mapping, tenant=tenant, identity_value=identity_value)

    def close(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if callable(close):
                close()

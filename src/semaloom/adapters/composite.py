"""Provider routing kept at the integration boundary."""

from __future__ import annotations

from typing import Any, cast

from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import MappingDef
from semaloom.core.provider import ObjectRead, ObjectSearch, ReadProvider
from semaloom.core.results import Observation
from semaloom.core.semantic_query import (
    AnalysisError,
    MetricRef,
    PlanRef,
    QueryResult,
    SemanticQuery,
)


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

    def search_objects(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        filters: dict[str, Any],
        properties: tuple[str, ...],
        limit: int,
    ) -> ObjectSearch:
        search = getattr(self._providers.get(mapping.provider), "search_objects", None)
        if not callable(search):
            return ObjectSearch(kind="UNAVAILABLE", reason="SEARCH_NOT_SUPPORTED")
        return cast(
            ObjectSearch,
            search(mapping, tenant=tenant, filters=filters, properties=properties, limit=limit),
        )

    def _analysis_provider(self, bundle: CompiledBundle, query: SemanticQuery) -> Any:
        targets = {ref.id for ref in query.metrics}
        for metric in bundle.metrics:
            if metric.id in targets:
                targets.update(metric.derived_from)
        kinds = {mapping.provider for mapping in bundle.mappings if mapping.target in targets}
        if len(kinds) != 1:
            raise AnalysisError("CROSS_SOURCE_SQL")
        provider = self._providers.get(next(iter(kinds)))
        if not callable(getattr(provider, "prepare_analysis", None)):
            raise AnalysisError("OPERATOR_NOT_SUPPORTED")
        return provider

    def prepare_analysis(self, bundle: CompiledBundle, query: SemanticQuery, tenant: str) -> str:
        return cast(
            str, self._analysis_provider(bundle, query).prepare_analysis(bundle, query, tenant)
        )

    def analysis_subjects(
        self, bundle: CompiledBundle, query: SemanticQuery, tenant: str
    ) -> list[tuple[str, str, str]]:
        return cast(
            list[tuple[str, str, str]],
            self._analysis_provider(bundle, query).analysis_subjects(bundle, query, tenant),
        )

    def execute_analysis(self, bundle: CompiledBundle, plan: PlanRef, tenant: str) -> QueryResult:
        return cast(
            QueryResult,
            self._analysis_provider(bundle, plan.query).execute_analysis(bundle, plan, tenant),
        )

    def analysis_years(self, bundle: CompiledBundle, metric_id: str, tenant: str) -> list[int]:
        query = SemanticQuery(api_version="semaloom/v0.1", metrics=(MetricRef(id=metric_id),))
        return cast(
            list[int],
            self._analysis_provider(bundle, query).analysis_years(bundle, metric_id, tenant),
        )

    def close(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if callable(close):
                close()

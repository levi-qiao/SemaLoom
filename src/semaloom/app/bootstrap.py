"""Wire the single-process composition root for local-dev."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from semaloom.adapters.composite import CompositeReadProvider
from semaloom.adapters.openapi import OpenApiReadProvider
from semaloom.adapters.postgres import PostgresReadProvider
from semaloom.compiler import compile_paths
from semaloom.core.bundle import CompiledBundle
from semaloom.core.provider import ReadProvider
from semaloom.runtime.action import ActionService, DraftStore
from semaloom.runtime.fixtures import (
    configured_urls,
    engines,
    ensure_control_schema,
    load_synthetic,
)
from semaloom.runtime.query import QueryService
from semaloom.runtime.registry import Registry
from semaloom.runtime.session import StudioSessionService
from semaloom.runtime.source_registry import SourceProfileService
from semaloom.runtime.source_validation import resolve_environment_binding
from semaloom.runtime.studio_control import StudioDraftService
from semaloom.runtime.studio_release import StudioReleaseService

REPO = Path(__file__).resolve().parents[3]


@dataclass
class AppServices:
    bundle: CompiledBundle
    query: QueryService
    registry: Registry
    actions: ActionService
    drafts: DraftStore
    provider: ReadProvider
    studio_drafts: StudioDraftService
    source_profiles: SourceProfileService
    environment_bindings: dict[str, str]
    studio_releases: StudioReleaseService
    sessions: StudioSessionService
    environment: str = "dev"

    def query_for_digest(self, digest: str) -> QueryService:
        return QueryService(self.registry.load(digest), self.provider)

    def query_active(self, tenant: str | None = None) -> QueryService:
        current = (
            self.studio_releases.pointer(tenant, self.environment)[0]
            if tenant is not None
            else self.registry.current(self.environment)
        )
        if current is None:
            return self.query
        return QueryService(self.registry.load(current), self.provider)

    def close(self) -> None:
        close = getattr(self.provider, "close", None)
        if callable(close):
            close()


def example_roots() -> list[Path]:
    configured = os.getenv("SEMALOOM_PACK_PATHS")
    if configured:
        paths = [Path(item).expanduser().resolve() for item in configured.split(os.pathsep)]
        if any(not path.is_dir() for path in paths):
            raise ValueError("SEMALOOM_PACK_PATHS must contain existing pack directories")
        return paths
    return [REPO / "examples" / "tax", REPO / "examples" / "procurement"]


def compile_examples() -> CompiledBundle:
    result = compile_paths(example_roots())
    if not result.ok or result.bundle is None:
        raise RuntimeError([item.model_dump() for item in result.diagnostics])
    return result.bundle


def build_services(*, load_data: bool = True) -> AppServices:
    if load_data:
        load_synthetic()
    bundle = compile_examples()
    pool = engines()
    ensure_control_schema(pool["meta"])
    source_profiles = SourceProfileService(pool["meta"])
    if not os.getenv("SEMALOOM_PACK_PATHS"):
        for tenant in ("tenant-a", "tenant-b"):
            source_profiles.ensure_defaults(tenant, "local-dev")
    environment_bindings = {
        "env:SEMALOOM_TAX_DATABASE_URL": configured_urls()["tax_pg"],
        "env:SEMALOOM_ORDERS_DATABASE_URL": configured_urls()["orders_pg"],
        "env:SEMALOOM_SUPPLIERS_DATABASE_URL": configured_urls()["suppliers_pg"],
        "env:SEMALOOM_PROCUREMENT_API_URL": os.getenv(
            "SEMALOOM_PROCUREMENT_API_URL", "http://127.0.0.1:8099"
        ),
        "env:SEMALOOM_TAX_API_URL": os.getenv("SEMALOOM_TAX_API_URL", "http://127.0.0.1:8099"),
    }

    def source_url(tenant: str, source_id: str, provider_name: str) -> str | None:
        try:
            profile = source_profiles.get(tenant, source_id)
        except KeyError:
            return None
        if profile.provider != provider_name:
            return None
        return resolve_environment_binding(profile.binding_ref, environment_bindings)

    provider = CompositeReadProvider(
        {
            "postgres": PostgresReadProvider(
                {}, url_resolver=lambda tenant, source_id: source_url(tenant, source_id, "postgres")
            ),
            "openapi": OpenApiReadProvider(
                {},
                base_url_resolver=lambda tenant, source_id: source_url(
                    tenant, source_id, "openapi"
                ),
            ),
        }
    )
    drafts = DraftStore()
    registry = Registry(pool["meta"])
    if load_data:
        with pool["meta"].connect() as conn:
            conn.execute(text("SELECT execution_id FROM action_execution LIMIT 1"))
        registry.publish(bundle, publisher="local-dev")
        if registry.current("dev") is None:
            registry.activate("dev", bundle.digest, expected_revision=None)
        current = registry.current("dev")
        if current is not None:
            bundle = registry.load(current)
    studio_drafts = StudioDraftService(pool["meta"], bundle)
    return AppServices(
        bundle=bundle,
        query=QueryService(bundle, provider),
        registry=registry,
        actions=ActionService(bundle, pool["meta"], drafts),
        drafts=drafts,
        provider=provider,
        studio_drafts=studio_drafts,
        source_profiles=source_profiles,
        environment_bindings=environment_bindings,
        studio_releases=StudioReleaseService(
            pool["meta"], studio_drafts, source_profiles, registry
        ),
        sessions=StudioSessionService(pool["meta"]),
    )


def source_urls() -> dict[str, str]:
    return configured_urls()

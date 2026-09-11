"""Wire the single-process composition root for local-dev."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from semaloom.adapters.postgres import PostgresReadProvider
from semaloom.compiler import compile_paths
from semaloom.core.bundle import CompiledBundle
from semaloom.runtime.action import ActionService, DraftStore
from semaloom.runtime.fixtures import DEFAULT_URLS, engines, load_synthetic
from semaloom.runtime.query import QueryService
from semaloom.runtime.registry import Registry

REPO = Path(__file__).resolve().parents[3]


@dataclass
class AppServices:
    bundle: CompiledBundle
    query: QueryService
    registry: Registry
    actions: ActionService
    drafts: DraftStore
    provider: PostgresReadProvider
    environment: str = "dev"

    def query_for_digest(self, digest: str) -> QueryService:
        return QueryService(self.registry.load(digest), self.provider)

    def query_active(self) -> QueryService:
        current = self.registry.current(self.environment)
        if current is None:
            return self.query
        return QueryService(self.registry.load(current), self.provider)


def example_roots() -> list[Path]:
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
    provider = PostgresReadProvider(
        {key: pool[key] for key in ("tax_pg", "orders_pg", "suppliers_pg")}
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
    return AppServices(
        bundle=bundle,
        query=QueryService(bundle, provider),
        registry=registry,
        actions=ActionService(bundle, pool["meta"], drafts),
        drafts=drafts,
        provider=provider,
    )


def source_urls() -> dict[str, str]:
    return dict(DEFAULT_URLS)

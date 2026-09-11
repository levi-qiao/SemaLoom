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
    if load_data:
        with pool["meta"].connect() as conn:
            conn.execute(text("SELECT execution_id FROM action_execution LIMIT 1"))
    return AppServices(
        bundle=bundle,
        query=QueryService(bundle, provider),
        registry=Registry(pool["meta"]),
        actions=ActionService(bundle, pool["meta"], drafts),
        drafts=drafts,
    )


def source_urls() -> dict[str, str]:
    return dict(DEFAULT_URLS)

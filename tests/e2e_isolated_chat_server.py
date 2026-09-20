"""Isolated Chat+Studio server for Playwright. Not shared :8000 or sample DBs."""

from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from semaloom.adapters.postgres import PostgresReadProvider
from semaloom.app.chat.service import ChatService
from semaloom.app.chat.store import ChatStore
from semaloom.app.factory import _mount_studio, create_app
from semaloom.app.http import router
from semaloom.core.bundle import CompiledBundle
from semaloom.runtime.action import ActionService, DraftStore
from semaloom.runtime.fixtures import ensure_control_schema
from semaloom.runtime.query import QueryService
from semaloom.runtime.registry import Registry
from semaloom.runtime.session import StudioSessionService
from semaloom.runtime.source_registry import SourceProfileService
from semaloom.runtime.studio_control import StudioDraftService
from semaloom.runtime.studio_release import StudioReleaseService
from semaloom.sdk import compile_paths

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "harness"
PG16 = Path("/opt/homebrew/opt/postgresql@16/bin")
HTTP_PORT = int(os.getenv("SEMALOOM_E2E_HTTP_PORT", "18082"))
PG_PORT = int(os.getenv("SEMALOOM_E2E_PG_PORT", "55433"))
SCRATCH = Path(
    os.getenv(
        "SEMALOOM_E2E_SCRATCH",
        "/var/folders/w6/c0cnf1y93l92d34q4bjq90r40000gn/T/grok-goal-14052e0ed963/implementer",
    )
)


@dataclass
class IsolatedServices:
    bundle: CompiledBundle
    query: QueryService
    registry: Registry
    actions: ActionService
    drafts: DraftStore
    provider: PostgresReadProvider
    studio_drafts: StudioDraftService
    source_profiles: SourceProfileService
    environment_bindings: dict[str, str]
    studio_releases: StudioReleaseService
    sessions: StudioSessionService
    environment: str = "dev"

    def query_active(self, tenant: str | None = None) -> QueryService:
        return self.query

    def close(self) -> None:
        self.provider.close()


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ensure_postgres() -> str:
    url = f"postgresql+psycopg://semaloom@127.0.0.1:{PG_PORT}/q3_e2e"
    pgdata = SCRATCH / "q3-pgdata"
    if not _port_open(PG_PORT):
        pgdata.mkdir(parents=True, exist_ok=True)
        if not (pgdata / "PG_VERSION").exists():
            subprocess.check_call(
                [
                    str(PG16 / "initdb"),
                    "-D",
                    str(pgdata),
                    "--auth=trust",
                    "--username=semaloom",
                    "--encoding=UTF8",
                    "--locale=C",
                    "--no-instructions",
                ]
            )
            conf = pgdata / "postgresql.conf"
            conf.write_text(
                conf.read_text(encoding="utf-8") + "\nlisten_addresses = '127.0.0.1'\n"
                f"port = {PG_PORT}\n"
                "unix_socket_directories = ''\n",
                encoding="utf-8",
            )
        subprocess.check_call(
            [
                str(PG16 / "pg_ctl"),
                "-D",
                str(pgdata),
                "-l",
                str(SCRATCH / "q3-pg.log"),
                "-w",
                "start",
            ]
        )
        time.sleep(0.3)
    probe = create_engine(
        f"postgresql+psycopg://semaloom@127.0.0.1:{PG_PORT}/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with probe.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname='q3_e2e'")).scalar()
        if not exists:
            conn.execute(text("CREATE DATABASE q3_e2e"))
    probe.dispose()
    return url


def load_review_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sample_financial_review (
                  tenant_id TEXT, id TEXT, company_name TEXT, tax_year INTEGER,
                  period_start DATE, period_to DATE, unique_pair BOOLEAN,
                  declared_profit NUMERIC, audit_profit NUMERIC, net_profit NUMERIC,
                  tax_expense NUMERIC, assets NUMERIC, liabilities NUMERIC, equity NUMERIC,
                  company_id TEXT, report_id TEXT, return_id TEXT
                )
                """
            )
        )
        conn.execute(text("DELETE FROM sample_financial_review"))
        conn.execute(
            text(
                """
                INSERT INTO sample_financial_review (
                  tenant_id,id,company_name,tax_year,period_start,period_to,unique_pair,
                  declared_profit,audit_profit,net_profit,tax_expense,assets,liabilities,equity,
                  company_id
                ) VALUES
                ('tenant-a','C1','示例甲',2024,'2024-01-01','2025-01-01',true,
                 100.01,100,80,20,1000,600,400,'C1'),
                ('tenant-a','C2','示例乙',2024,'2024-01-01','2025-01-01',true,
                 100.02,100,79,20,1002,600,400,'C2'),
                ('tenant-a','C3','示例丙',2024,'2024-01-01','2025-01-01',true,
                 100.00,NULL,80,20,NULL,600,400,'C3')
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sample_declaration (
                  tenant_id TEXT, id TEXT, taxpayer_id TEXT, tax_year INTEGER,
                  period_start DATE, period_end DATE,
                  revenue NUMERIC, total_profit NUMERIC, taxable_income NUMERIC, income_tax NUMERIC
                )
                """
            )
        )
        conn.execute(text("DELETE FROM sample_declaration"))
        conn.execute(
            text(
                """
                INSERT INTO sample_declaration (
                  tenant_id,id,taxpayer_id,tax_year,period_start,period_end,
                  revenue,total_profit,taxable_income,income_tax
                ) VALUES
                ('tenant-a','D1-23','C1',2023,'2023-01-01','2024-01-01',90.01,70,80.01,18),
                ('tenant-a','D2-23','C2',2023,'2023-01-01','2024-01-01',90.02,69,80.02,18),
                ('tenant-a','D3-23','C3',2023,'2023-01-01','2024-01-01',90.00,70,80.00,18),
                ('tenant-a','D1','C1',2024,'2024-01-01','2025-01-01',100.01,80,90.01,20),
                ('tenant-a','D2','C2',2024,'2024-01-01','2025-01-01',100.02,79,90.02,20),
                ('tenant-a','D3','C3',2024,'2024-01-01','2025-01-01',100.00,80,90.00,20),
                ('tenant-a','D1-25','C1',2025,'2025-01-01','2026-01-01',110.01,90,100.01,22),
                ('tenant-a','D2-25','C2',2025,'2025-01-01','2026-01-01',110.02,89,100.02,22),
                ('tenant-a','D3-25','C3',2025,'2025-01-01','2026-01-01',110.00,90,100.00,22)
                """
            )
        )


def build_app() -> FastAPI:
    url = ensure_postgres()
    engine = create_engine(url)
    ensure_control_schema(engine)
    load_review_table(engine)
    bundle = compile_paths([REPO / "examples" / "financial-review"]).bundle
    if bundle is None:
        raise RuntimeError("financial-review failed to compile")
    provider = PostgresReadProvider({"sample_pg": engine})
    query = QueryService(bundle, provider)
    registry = Registry(engine)
    drafts = DraftStore()
    source_profiles = SourceProfileService(engine)
    studio_drafts = StudioDraftService(engine, bundle)
    services = IsolatedServices(
        bundle=bundle,
        query=query,
        registry=registry,
        actions=ActionService(bundle, engine, drafts),
        drafts=drafts,
        provider=provider,
        studio_drafts=studio_drafts,
        source_profiles=source_profiles,
        environment_bindings={},
        studio_releases=StudioReleaseService(engine, studio_drafts, source_profiles, registry),
        sessions=StudioSessionService(engine),
    )
    config = SCRATCH / "q3-provider.json"
    config.write_text(
        '{"apiKey":"e2e-not-used","baseUrl":"https://example.invalid/v1","model":"faux-e2e"}',
        encoding="utf-8",
    )
    app = create_app(load_services=False)
    from semaloom.app.chat.http import router as chat_router

    app.include_router(router)
    app.include_router(chat_router)
    _mount_studio(app)
    app.state.services = services
    app.state.chat = ChatService(ChatStore(engine), config)
    app.state.chat.worker = HARNESS / "e2e-faux-worker.mjs"
    return app


def main() -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    app = build_app()
    import uvicorn

    print(f"Q3_E2E_READY http://127.0.0.1:{HTTP_PORT}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()

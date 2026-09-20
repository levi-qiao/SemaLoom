"""Isolated Chat+Studio server for Playwright. Not shared :8000 or sample DBs."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from semaloom.app.factory import create_app

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "harness"
HTTP_PORT = int(os.getenv("SEMALOOM_E2E_HTTP_PORT", "18082"))
PG_PORT = int(os.getenv("SEMALOOM_E2E_PG_PORT", "55433"))


def postgres_binary(name: str) -> str:
    bindir = os.getenv("SEMALOOM_E2E_PG_BINDIR")
    executable = str(Path(bindir) / name) if bindir else shutil.which(name)
    if not executable or not Path(executable).is_file():
        raise RuntimeError(f"Install PostgreSQL and set SEMALOOM_E2E_PG_BINDIR: missing {name}")
    return executable


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ensure_postgres(scratch: Path) -> str:
    if _port_open(PG_PORT):
        raise RuntimeError(f"Refusing to reuse occupied PostgreSQL port {PG_PORT}")
    url = f"postgresql+psycopg://semaloom@127.0.0.1:{PG_PORT}/q3_e2e"
    pgdata = scratch / "q3-pgdata"
    pgdata.mkdir(parents=True, exist_ok=True)
    if not (pgdata / "PG_VERSION").exists():
        subprocess.check_call(
            [
                postgres_binary("initdb"),
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
            postgres_binary("pg_ctl"),
            "-D",
            str(pgdata),
            "-l",
            str(scratch / "q3-pg.log"),
            "-w",
            "start",
        ]
    )
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
    fixture = REPO / "examples/financial-review/fixtures/demo.sql"
    with engine.begin() as conn:
        conn.exec_driver_sql(fixture.read_text(encoding="utf-8"))


def build_app(scratch: Path) -> FastAPI:
    url = ensure_postgres(scratch)
    # All source and metadata writes stay inside this task-owned PostgreSQL instance.
    for name in ("TAX", "ORDERS", "SUPPLIERS", "META"):
        os.environ[f"SEMALOOM_{name}_DATABASE_URL"] = url
    os.environ.pop("SEMALOOM_SAMPLE_DATABASE_URL", None)
    os.environ["SEMALOOM_PACK_PATHS"] = os.pathsep.join(
        str(REPO / "examples" / name) for name in ("tax", "procurement", "financial-review")
    )
    for name in ("TAX", "PROCUREMENT"):
        os.environ[f"SEMALOOM_{name}_API_URL"] = f"http://127.0.0.1:{HTTP_PORT}"
    config = scratch / "provider.json"
    config.write_text(
        '{"apiKey":"e2e-not-used","baseUrl":"https://example.invalid/v1","model":"faux-e2e"}',
        encoding="utf-8",
    )
    os.environ["SEMALOOM_CHAT_CONFIG"] = str(config)
    app = create_app(profile="local-dev", load_fixtures=True)
    services = app.state.services
    load_review_table(services.studio_drafts.engine)
    services.environment_bindings["env:SEMALOOM_E2E_REVIEW_URL"] = url
    for tenant in ("tenant-a", "tenant-b"):
        services.source_profiles.save(
            tenant=tenant,
            actor="e2e",
            source_id="sample_pg",
            expected_revision=0,
            label="Synthetic financial review",
            provider="postgres",
            binding_ref="env:SEMALOOM_E2E_REVIEW_URL",
            secret_ref=None,
            settings={},
        )
    from semaloom.app.local_mock import sample_mock_router

    app.include_router(sample_mock_router(services.studio_drafts.engine))
    services.environment_bindings["env:SEMALOOM_E2E_SAMPLE_API"] = f"http://127.0.0.1:{HTTP_PORT}"
    for tenant in ("tenant-a", "tenant-b"):
        services.source_profiles.save(
            tenant=tenant,
            actor="e2e",
            source_id="sample_api",
            expected_revision=0,
            label="Synthetic review workflow",
            provider="openapi",
            binding_ref="env:SEMALOOM_E2E_SAMPLE_API",
            secret_ref=None,
            settings={},
        )
    live_config = os.getenv("SEMALOOM_E2E_CHAT_CONFIG")
    if live_config:
        from semaloom.app.chat.service import ChatService

        app.state.chat = ChatService(app.state.chat.store, Path(live_config))
    else:
        app.state.chat.worker = HARNESS / "e2e-faux-worker.mjs"
    return app


def main() -> None:
    import uvicorn

    # Uvicorn re-raises SIGTERM after shutdown; unwind our owned database lifecycle too.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with TemporaryDirectory(prefix="semaloom-e2e-", dir=os.getenv("SEMALOOM_E2E_SCRATCH")) as root:
        scratch = Path(root)
        try:
            app = build_app(scratch)
            print(f"E2E_READY http://127.0.0.1:{HTTP_PORT}", flush=True)
            uvicorn.run(app, host="127.0.0.1", port=HTTP_PORT, log_level="warning")
        finally:
            pgdata = scratch / "q3-pgdata"
            if (pgdata / "postmaster.pid").exists():
                subprocess.run(
                    [postgres_binary("pg_ctl"), "-D", str(pgdata), "-m", "fast", "-w", "stop"],
                    check=True,
                )


if __name__ == "__main__":
    main()

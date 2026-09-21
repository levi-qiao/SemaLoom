"""FastAPI composition root for the local-development profile."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from semaloom.app.authentication import (
    BearerAuthenticator,
    DemoTokenAuthenticator,
    JwtAuthenticator,
)
from semaloom.app.http import TOKENS, router
from semaloom.identity import BuildIdentity, build_identity


def create_app(
    *,
    profile: str | None = None,
    load_services: bool = True,
    load_fixtures: bool = False,
    authenticator: BearerAuthenticator | None = None,
) -> FastAPI:
    """Build the single application process.

    Local-dev does not require production credentials. Fixture loading remains
    an explicit development action so application startup never deletes state.
    """

    identity = build_identity(profile=profile)
    resolved_authenticator: BearerAuthenticator
    if authenticator is None:
        resolved_authenticator = (
            DemoTokenAuthenticator(TOKENS)
            if identity.profile == "local-dev"
            else JwtAuthenticator.from_environment()
        )
    else:
        resolved_authenticator = authenticator
    if identity.profile != "local-dev" and isinstance(
        resolved_authenticator, DemoTokenAuthenticator
    ):
        raise RuntimeError("production profile cannot use local demonstration tokens")

    mcp_server = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if mcp_server is not None:
                await stack.enter_async_context(mcp_server.session_manager.run())
            yield
            if getattr(app.state, "chat", None) is not None:
                await app.state.chat.close()
            if load_services:
                app.state.services.close()
            if sample_engine is not None:
                sample_engine.dispose()

    app = FastAPI(
        title="SemaLoom",
        version=identity.version,
        summary="Enterprise business semantic layer",
        lifespan=lifespan,
    )
    app.state.identity = identity
    app.state.profile = identity.profile
    app.state.authenticator = resolved_authenticator
    sample_engine = None

    @app.get("/identity")
    def identity_endpoint() -> dict[str, str]:
        current: BuildIdentity = app.state.identity
        return current.to_dict()

    if identity.profile == "local-dev":
        sample_url = os.getenv("SEMALOOM_SAMPLE_DATABASE_URL")
        if sample_url:
            from sqlalchemy.engine import make_url

            from semaloom.adapters.postgres import engine_from_url
            from semaloom.app.local_mock import sample_mock_router

            parsed = make_url(sample_url)
            if (
                parsed.host not in {"localhost", "127.0.0.1", "::1"}
                or parsed.database != "semaloom_samples"
                or parsed.query
            ):
                raise ValueError("sample mock requires the local semaloom_samples database")
            sample_engine = engine_from_url(sample_url)
            app.include_router(sample_mock_router(sample_engine))

        @app.get("/health")
        def local_source_health() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/order-risk")
        def local_order_risk(orderId: str, tenant: str) -> dict[str, str]:
            if tenant != "tenant-a" or orderId != "PO-001":
                return {"orderId": orderId, "deliveryRisk": "UNKNOWN"}
            return {"orderId": orderId, "deliveryRisk": "LOW"}

    if load_services:
        from semaloom.app.bootstrap import build_services

        app.state.services = build_services(load_data=load_fixtures)
        app.include_router(router)
        from semaloom.app.mcp_server import build_mcp_server

        mcp_server = build_mcp_server(app.state.services, resolved_authenticator)
        app.mount("/mcp", mcp_server.streamable_http_app(), name="mcp")
        from semaloom.app.chat.http import router as chat_router

        app.state.chat = None
        if config_path := os.getenv("SEMALOOM_CHAT_CONFIG"):
            from semaloom.app.chat.service import ChatService
            from semaloom.app.chat.store import ChatStore

            app.state.chat = ChatService(
                ChatStore(app.state.services.studio_drafts.engine), Path(config_path).resolve()
            )
        app.include_router(chat_router)
        _mount_studio(app)

    return app


class StudioStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            # Revalidate the entry point so a rebuilt UI cannot keep stale asset references.
            response.headers["Cache-Control"] = "no-cache"
        return response


def _mount_studio(app: FastAPI) -> None:
    packaged = Path(__file__).resolve().parent / "static"
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    root = packaged if (packaged / "index.html").is_file() else dist
    if root.is_dir():
        app.mount("/studio", StudioStaticFiles(directory=root, html=True), name="studio")

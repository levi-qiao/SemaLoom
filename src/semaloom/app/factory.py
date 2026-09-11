"""FastAPI composition root for the local-development profile."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from semaloom.app.http import router
from semaloom.identity import BuildIdentity, build_identity


def create_app(
    *, profile: str | None = None, load_services: bool = True, load_fixtures: bool = False
) -> FastAPI:
    """Build the single application process.

    Local-dev does not require production credentials. Fixture loading remains
    an explicit development action so application startup never deletes state.
    """

    identity = build_identity(profile=profile)
    if load_services and identity.profile != "local-dev":
        raise RuntimeError(
            "only the local-dev profile is implemented; configure trusted identity and adapters "
            "before enabling another profile"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if load_services:
            app.state.services.close()

    app = FastAPI(
        title="SemaLoom",
        version=identity.version,
        summary="Enterprise business semantic layer",
        lifespan=lifespan,
    )
    app.state.identity = identity
    app.state.profile = identity.profile

    @app.get("/identity")
    def identity_endpoint() -> dict[str, str]:
        current: BuildIdentity = app.state.identity
        return current.to_dict()

    if identity.profile == "local-dev":

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
        _mount_studio(app)

    return app


def _mount_studio(app: FastAPI) -> None:
    packaged = Path(__file__).resolve().parent / "static"
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    root = packaged if (packaged / "index.html").is_file() else dist
    if root.is_dir():
        app.mount("/studio", StaticFiles(directory=root, html=True), name="studio")

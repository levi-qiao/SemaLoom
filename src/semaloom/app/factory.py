"""FastAPI composition root for the local-development profile."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from semaloom.app.http import router
from semaloom.identity import BuildIdentity, build_identity


def create_app(*, profile: str | None = None, load_services: bool = True) -> FastAPI:
    """Build the single application process.

    Local-dev does not require production credentials. Synthetic PostgreSQL
    fixtures are used when load_services is true.
    """

    identity = build_identity(profile=profile)
    if load_services and identity.profile != "local-dev":
        raise RuntimeError(
            "only the local-dev profile is implemented; configure trusted identity and adapters "
            "before enabling another profile"
        )
    app = FastAPI(
        title="SemaLoom",
        version=identity.version,
        summary="Enterprise business semantic layer",
    )
    app.state.identity = identity
    app.state.profile = identity.profile

    @app.get("/identity")
    def identity_endpoint() -> dict[str, str]:
        current: BuildIdentity = app.state.identity
        return current.to_dict()

    if load_services:
        from semaloom.app.bootstrap import build_services

        app.state.services = build_services()
        app.include_router(router)
        _mount_studio(app)

    return app


def _mount_studio(app: FastAPI) -> None:
    packaged = Path(__file__).resolve().parent / "static"
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    root = packaged if (packaged / "index.html").is_file() else dist
    if root.is_dir():
        app.mount("/studio", StaticFiles(directory=root, html=True), name="studio")

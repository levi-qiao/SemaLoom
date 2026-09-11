"""FastAPI composition root for the local-development profile."""

from __future__ import annotations

from fastapi import FastAPI

from semaloom.identity import BuildIdentity, build_identity


def create_app(*, profile: str | None = None) -> FastAPI:
    """Build the single application process without source credentials.

    Later tasks attach query, action, and recovery routes to this app.
    T00 only exposes build identity so the entry is observable.
    """

    identity = build_identity(profile=profile)
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

    return app

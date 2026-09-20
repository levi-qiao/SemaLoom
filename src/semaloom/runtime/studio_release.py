"""Activate the saved Studio model as the live query release."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from semaloom.runtime.registry import Registry
from semaloom.runtime.source_registry import SourceProfileService
from semaloom.runtime.studio_control import StudioDraftService


class StudioReleaseService:
    def __init__(
        self,
        engine: Engine,
        drafts: StudioDraftService,
        sources: SourceProfileService,
        registry: Registry,
    ) -> None:
        self.engine = engine
        self.drafts = drafts
        self.sources = sources
        self.registry = registry

    def pointer(self, tenant: str, environment: str) -> tuple[str | None, int]:
        return self.registry.pointer(_tenant_environment(tenant, environment))

    def apply_live(
        self,
        tenant: str,
        actor: str,
        draft_id: str,
        environment: str,
    ) -> dict[str, Any]:
        """Compile the saved model, publish it, and activate it for queries."""
        snapshot = self.drafts.load(tenant, draft_id)
        bundle = self.drafts.bundle(tenant, draft_id)
        publication_id = uuid.uuid4().hex
        with self.registry.transaction() as conn:
            digest = self.registry.publish_in(conn, bundle, publisher=actor)
            environment_revision = self.registry.activate_in(
                conn,
                _tenant_environment(tenant, environment),
                digest,
                expected_revision=None,
            )
            conn.execute(
                text(
                    """
                    INSERT INTO studio_publication(
                      publication_id, tenant_id, draft_id, draft_revision, digest,
                      environment, environment_revision, publisher
                    ) VALUES (
                      :publication_id, :tenant_id, :draft_id, :draft_revision, :digest,
                      :environment, :environment_revision, :publisher
                    )
                    """
                ),
                {
                    "publication_id": publication_id,
                    "tenant_id": tenant,
                    "draft_id": draft_id,
                    "draft_revision": snapshot.revision,
                    "digest": digest,
                    "environment": environment,
                    "environment_revision": environment_revision,
                    "publisher": actor,
                },
            )
        return {
            "publicationId": publication_id,
            "digest": digest,
            "environment": environment,
            "environmentRevision": environment_revision,
            "status": "ACTIVE",
            "draftRevision": snapshot.revision,
            "candidateDigest": snapshot.candidate_digest,
        }

    def history(self, tenant: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT publication_id, draft_id, draft_revision, digest, environment,
                           environment_revision, publisher, created_at
                    FROM studio_publication WHERE tenant_id = :tenant_id
                    ORDER BY created_at DESC
                    """
                ),
                {"tenant_id": tenant},
            ).all()
        return [
            {
                "publicationId": str(row.publication_id),
                "draftId": str(row.draft_id),
                "draftRevision": int(row.draft_revision),
                "digest": str(row.digest),
                "environment": str(row.environment),
                "environmentRevision": int(row.environment_revision),
                "publisher": str(row.publisher),
                "createdAt": row.created_at.isoformat(),
            }
            for row in rows
        ]


def _tenant_environment(tenant: str, environment: str) -> str:
    return f"tenant:{tenant}:{environment}"

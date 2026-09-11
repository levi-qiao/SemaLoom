"""Validation, approval and immutable publication for Studio drafts."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from semaloom.runtime.registry import Registry
from semaloom.runtime.source_registry import SourceProfileService
from semaloom.runtime.studio_control import StudioDraftService, documents_from_bundle


class ReleaseGateError(RuntimeError):
    pass


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

    def review(self, tenant: str, draft_id: str) -> dict[str, Any]:
        snapshot = self.drafts.load(tenant, draft_id)
        base = {
            (str(item["kind"]), str(item["id"])): item
            for item in documents_from_bundle(self.drafts.base_bundle)
        }
        candidate = {(str(item["kind"]), str(item["id"])): item for item in snapshot.documents}
        return {
            **snapshot.to_dict(),
            "changes": {
                "added": [key[1] for key in sorted(candidate.keys() - base.keys())],
                "removed": [key[1] for key in sorted(base.keys() - candidate.keys())],
                "changed": [
                    key[1]
                    for key in sorted(candidate.keys() & base.keys())
                    if candidate[key] != base[key]
                ],
            },
        }

    def pointer(self, tenant: str, environment: str) -> tuple[str | None, int]:
        return self.registry.pointer(_tenant_environment(tenant, environment))

    def validate(self, tenant: str, actor: str, draft_id: str, environment: str) -> dict[str, Any]:
        snapshot = self.drafts.load(tenant, draft_id)
        bundle = self.drafts.bundle(tenant, draft_id)
        source_status = self._source_state(tenant, bundle)
        valid = all(item["status"] == "VALID" for item in source_status.values())
        status = "VALID" if valid else "INVALID"
        validation_id = uuid.uuid4().hex
        details = {"sources": source_status, "compiler": "VALID"}
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO studio_validation(
                      validation_id, tenant_id, draft_id, draft_revision, candidate_digest,
                      environment, status, details, validator
                    ) VALUES (
                      :validation_id, :tenant_id, :draft_id, :draft_revision, :candidate_digest,
                      :environment, :status, CAST(:details AS jsonb), :validator
                    )
                    """
                ),
                {
                    "validation_id": validation_id,
                    "tenant_id": tenant,
                    "draft_id": draft_id,
                    "draft_revision": snapshot.revision,
                    "candidate_digest": snapshot.candidate_digest,
                    "environment": environment,
                    "status": status,
                    "details": json.dumps(details),
                    "validator": actor,
                },
            )
        return {
            "validationId": validation_id,
            "draftRevision": snapshot.revision,
            "candidateDigest": snapshot.candidate_digest,
            "environment": environment,
            "status": status,
            "details": details,
        }

    def approve(self, tenant: str, actor: str, draft_id: str, environment: str) -> dict[str, Any]:
        snapshot = self.drafts.load(tenant, draft_id)
        if self.drafts.current_author(tenant, draft_id) == actor:
            raise ReleaseGateError("INDEPENDENT_REVIEW_REQUIRED")
        bundle = self.drafts.bundle(tenant, draft_id)
        with self.engine.begin() as conn:
            valid = conn.execute(
                text(
                    """
                    SELECT validation_id, details FROM studio_validation
                    WHERE tenant_id = :tenant_id AND draft_id = :draft_id
                      AND draft_revision = :draft_revision
                      AND candidate_digest = :candidate_digest
                      AND environment = :environment AND status = 'VALID'
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant,
                    "draft_id": draft_id,
                    "draft_revision": snapshot.revision,
                    "candidate_digest": snapshot.candidate_digest,
                    "environment": environment,
                },
            ).first()
            if valid is None or _json_object(valid.details).get("sources") != self._source_state(
                tenant, bundle
            ):
                raise ReleaseGateError("VALIDATION_REQUIRED")
            approval_id = uuid.uuid4().hex
            conn.execute(
                text(
                    """
                    INSERT INTO studio_release_approval(
                      approval_id, tenant_id, draft_id, draft_revision, candidate_digest,
                      environment, validation_id, approver
                    ) VALUES (
                      :approval_id, :tenant_id, :draft_id, :draft_revision, :candidate_digest,
                      :environment, :validation_id, :approver
                    )
                    """
                ),
                {
                    "approval_id": approval_id,
                    "tenant_id": tenant,
                    "draft_id": draft_id,
                    "draft_revision": snapshot.revision,
                    "candidate_digest": snapshot.candidate_digest,
                    "environment": environment,
                    "validation_id": valid.validation_id,
                    "approver": actor,
                },
            )
        return {
            "approvalId": approval_id,
            "draftRevision": snapshot.revision,
            "candidateDigest": snapshot.candidate_digest,
            "environment": environment,
            "status": "APPROVED",
        }

    def publish(
        self,
        tenant: str,
        actor: str,
        draft_id: str,
        environment: str,
        expected_environment_revision: int,
    ) -> dict[str, Any]:
        snapshot = self.drafts.load(tenant, draft_id)
        bundle = self.drafts.bundle(tenant, draft_id)
        with self.engine.connect() as conn:
            validation = conn.execute(
                text(
                    """
                    SELECT validation_id, details FROM studio_validation
                    WHERE tenant_id = :tenant_id AND draft_id = :draft_id
                      AND draft_revision = :draft_revision
                      AND candidate_digest = :candidate_digest
                      AND environment = :environment AND status = 'VALID'
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant,
                    "draft_id": draft_id,
                    "draft_revision": snapshot.revision,
                    "candidate_digest": snapshot.candidate_digest,
                    "environment": environment,
                },
            ).first()
            approval = conn.execute(
                text(
                    """
                    SELECT approval_id, validation_id FROM studio_release_approval
                    WHERE tenant_id = :tenant_id AND draft_id = :draft_id
                      AND draft_revision = :draft_revision
                      AND candidate_digest = :candidate_digest AND environment = :environment
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant,
                    "draft_id": draft_id,
                    "draft_revision": snapshot.revision,
                    "candidate_digest": snapshot.candidate_digest,
                    "environment": environment,
                },
            ).first()
        if validation is None or _json_object(validation.details).get(
            "sources"
        ) != self._source_state(tenant, bundle):
            raise ReleaseGateError("VALIDATION_REQUIRED")
        if approval is None or approval.validation_id != validation.validation_id:
            raise ReleaseGateError("APPROVAL_REQUIRED")
        publication_id = uuid.uuid4().hex
        with self.registry.transaction() as conn:
            digest = self.registry.publish_in(conn, bundle, publisher=actor)
            environment_revision = self.registry.activate_in(
                conn,
                _tenant_environment(tenant, environment),
                digest,
                expected_revision=expected_environment_revision,
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

    def _source_state(self, tenant: str, bundle: Any) -> dict[str, dict[str, Any]]:
        profiles = {item.source_id: item for item in self.sources.list(tenant)}
        required = sorted({item.source_id for item in bundle.integration_bindings})
        return {
            source_id: {
                "revision": profiles[source_id].revision if source_id in profiles else None,
                "status": (
                    profiles[source_id].validation_status
                    if source_id in profiles
                    else "NOT_CONFIGURED"
                ),
            }
            for source_id in required
        }


def _tenant_environment(tenant: str, environment: str) -> str:
    return f"tenant:{tenant}:{environment}"


def _json_object(value: object) -> dict[str, Any]:
    decoded = value if isinstance(value, dict) else json.loads(str(value))
    return dict(decoded) if isinstance(decoded, dict) else {}

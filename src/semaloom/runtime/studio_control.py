"""Versioned semantic drafts backed by the canonical compiler."""

from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from semaloom.adapters.mapping import BuiltinMappingCompiler
from semaloom.compiler import compile_documents
from semaloom.core.bundle import CompiledBundle
from semaloom.core.diagnostics import Diagnostic

Document = dict[str, Any]

_BUNDLE_COLLECTIONS = (
    "packs",
    "object_types",
    "metrics",
    "links",
    "rules",
    "policies",
    "actions",
    "authorization_profiles",
    "mappings",
    "action_bindings",
    "integration_bindings",
)


@dataclass(frozen=True)
class DraftSnapshot:
    draft_id: str
    revision: int
    base_digest: str
    documents: tuple[Document, ...]
    candidate_digest: str
    exists: bool

    def compile(self) -> CompiledBundle:
        return _compile(self.documents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "draftId": self.draft_id,
            "revision": self.revision,
            "baseDigest": self.base_digest,
            "candidateDigest": self.candidate_digest,
            "documents": list(self.documents),
            "exists": self.exists,
        }


class RevisionConflict(RuntimeError):
    pass


class InvalidDraft(ValueError):
    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        super().__init__("INVALID_DRAFT")
        self.diagnostics = diagnostics


class StudioDraftService:
    def __init__(self, engine: Engine, base_bundle: CompiledBundle) -> None:
        self.engine = engine
        self.base_bundle = base_bundle
        self._migrate_legacy_workspace()

    def _migrate_legacy_workspace(self) -> None:
        """Preserve the pre-canonical workspace payload and upgrade it in place."""

        with self.engine.connect() as conn:
            columns = {
                str(row.column_name)
                for row in conn.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'studio_draft'
                        """
                    )
                )
            }
        if "payload" not in columns:
            return
        encoded = json.dumps(documents_from_bundle(self.base_bundle))
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS studio_draft_legacy (
                      tenant_id TEXT NOT NULL, draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
                      payload JSONB NOT NULL, migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      PRIMARY KEY (tenant_id, draft_id, revision)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO studio_draft_legacy(tenant_id, draft_id, revision, payload)
                    SELECT tenant_id, draft_id, revision, payload FROM studio_draft
                    ON CONFLICT (tenant_id, draft_id, revision) DO NOTHING
                    """
                )
            )
            for statement in (
                "ALTER TABLE studio_draft ADD COLUMN IF NOT EXISTS base_digest TEXT",
                "ALTER TABLE studio_draft ADD COLUMN IF NOT EXISTS candidate_digest TEXT",
                "ALTER TABLE studio_draft ADD COLUMN IF NOT EXISTS documents JSONB",
                "ALTER TABLE studio_draft ADD COLUMN IF NOT EXISTS updated_by TEXT",
                (
                    "ALTER TABLE studio_draft ADD COLUMN IF NOT EXISTS "
                    "updated_at TIMESTAMPTZ DEFAULT now()"
                ),
            ):
                conn.execute(text(statement))
            conn.execute(
                text(
                    """
                    UPDATE studio_draft
                    SET base_digest = COALESCE(base_digest, :digest),
                        candidate_digest = COALESCE(candidate_digest, :digest),
                        documents = COALESCE(documents, CAST(:documents AS jsonb)),
                        updated_by = COALESCE(updated_by, 'legacy-migration'),
                        updated_at = COALESCE(updated_at, now())
                    """
                ),
                {"digest": self.base_bundle.digest, "documents": encoded},
            )
            for column in (
                "base_digest",
                "candidate_digest",
                "documents",
                "updated_by",
                "updated_at",
            ):
                conn.execute(text(f"ALTER TABLE studio_draft ALTER COLUMN {column} SET NOT NULL"))
            conn.execute(
                text(
                    """
                    INSERT INTO studio_draft_revision(
                      tenant_id, draft_id, revision, base_digest, candidate_digest,
                      documents, author, created_at
                    )
                    SELECT tenant_id, draft_id, revision, base_digest, candidate_digest,
                           documents, updated_by, updated_at
                    FROM studio_draft
                    ON CONFLICT (tenant_id, draft_id, revision) DO NOTHING
                    """
                )
            )
            conn.execute(text("ALTER TABLE studio_draft DROP COLUMN payload"))

    def load(
        self, tenant: str, draft_id: str, *, connection: Connection | None = None
    ) -> DraftSnapshot:
        with nullcontext(connection) if connection is not None else self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT revision, base_digest, documents
                    FROM studio_draft
                    WHERE tenant_id = :tenant_id AND draft_id = :draft_id
                    """
                    + (" FOR UPDATE" if connection is not None else "")
                ),
                {"tenant_id": tenant, "draft_id": draft_id},
            ).first()
        if row is None:
            documents = documents_from_bundle(self.base_bundle)
            return DraftSnapshot(
                draft_id=draft_id,
                revision=0,
                base_digest=self.base_bundle.digest,
                documents=documents,
                candidate_digest=self.base_bundle.digest,
                exists=False,
            )
        documents = _decode_documents(row.documents)
        candidate = _compile(documents)
        return DraftSnapshot(
            draft_id=draft_id,
            revision=int(row.revision),
            base_digest=str(row.base_digest),
            documents=documents,
            candidate_digest=candidate.digest,
            exists=True,
        )

    def save(
        self,
        tenant: str,
        actor: str,
        draft_id: str,
        documents: list[Document],
        expected_revision: int,
        *,
        connection: Connection | None = None,
    ) -> DraftSnapshot:
        candidate = _compile(tuple(dict(item) for item in documents))
        encoded = json.dumps(documents)
        with nullcontext(connection) if connection is not None else self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    WITH updated AS (
                        UPDATE studio_draft
                        SET revision = revision + 1,
                            documents = CAST(:documents AS jsonb),
                            candidate_digest = :candidate_digest,
                            updated_by = :actor,
                            updated_at = now()
                        WHERE tenant_id = :tenant_id
                          AND draft_id = :draft_id
                          AND revision = :expected_revision
                        RETURNING revision, base_digest
                    ),
                    inserted AS (
                        INSERT INTO studio_draft(
                            tenant_id, draft_id, revision, base_digest, candidate_digest,
                            documents, updated_by
                        )
                        SELECT :tenant_id, :draft_id, 1, :base_digest, :candidate_digest,
                               CAST(:documents AS jsonb), :actor
                        WHERE :expected_revision = 0
                          AND NOT EXISTS (
                              SELECT 1 FROM studio_draft
                              WHERE tenant_id = :tenant_id AND draft_id = :draft_id
                          )
                        ON CONFLICT (tenant_id, draft_id) DO NOTHING
                        RETURNING revision, base_digest
                    )
                    SELECT revision, base_digest FROM updated
                    UNION ALL
                    SELECT revision, base_digest FROM inserted
                    """
                ),
                {
                    "tenant_id": tenant,
                    "draft_id": draft_id,
                    "actor": actor,
                    "documents": encoded,
                    "candidate_digest": candidate.digest,
                    "base_digest": self.base_bundle.digest,
                    "expected_revision": expected_revision,
                },
            ).first()
            if row is None:
                raise RevisionConflict("REVISION_CONFLICT")
            conn.execute(
                text(
                    """
                    INSERT INTO studio_draft_revision(
                      tenant_id, draft_id, revision, base_digest, candidate_digest,
                      documents, author
                    ) VALUES (
                      :tenant_id, :draft_id, :revision, :base_digest, :candidate_digest,
                      CAST(:documents AS jsonb), :actor
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "draft_id": draft_id,
                    "revision": int(row.revision),
                    "base_digest": str(row.base_digest),
                    "candidate_digest": candidate.digest,
                    "documents": encoded,
                    "actor": actor,
                },
            )
        return DraftSnapshot(
            draft_id=draft_id,
            revision=int(row.revision),
            base_digest=str(row.base_digest),
            documents=tuple(documents),
            candidate_digest=candidate.digest,
            exists=True,
        )

    def impacts(self, tenant: str, draft_id: str, semantic_id: str) -> list[dict[str, str]]:
        snapshot = self.load(tenant, draft_id)
        return definition_impacts(snapshot.documents, semantic_id)

    def bundle(self, tenant: str, draft_id: str) -> CompiledBundle:
        return self.load(tenant, draft_id).compile()

    def history(self, tenant: str, draft_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT revision, candidate_digest, author, created_at
                    FROM studio_draft_revision
                    WHERE tenant_id = :tenant_id AND draft_id = :draft_id
                    ORDER BY revision DESC
                    """
                ),
                {"tenant_id": tenant, "draft_id": draft_id},
            ).all()
        return [
            {
                "revision": int(row.revision),
                "candidateDigest": str(row.candidate_digest),
                "author": str(row.author),
                "createdAt": row.created_at.isoformat(),
            }
            for row in rows
        ]

    def load_revision(self, tenant: str, draft_id: str, revision: int) -> DraftSnapshot:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT base_digest, candidate_digest, documents
                    FROM studio_draft_revision
                    WHERE tenant_id = :tenant_id AND draft_id = :draft_id AND revision = :revision
                    """
                ),
                {"tenant_id": tenant, "draft_id": draft_id, "revision": revision},
            ).first()
        if row is None:
            raise KeyError(revision)
        return DraftSnapshot(
            draft_id=draft_id,
            revision=revision,
            base_digest=str(row.base_digest),
            documents=_decode_documents(row.documents),
            candidate_digest=str(row.candidate_digest),
            exists=True,
        )


def documents_from_bundle(bundle: CompiledBundle) -> tuple[Document, ...]:
    documents: list[Document] = []
    for collection in _BUNDLE_COLLECTIONS:
        for item in getattr(bundle, collection):
            dumped = item.model_dump(mode="json", by_alias=True, exclude_none=True)
            document = dict(dumped)
            if document.get("kind") == "Mapping":
                for field in (
                    "identityFields",
                    "grainFields",
                    "propertyFields",
                    "capabilities",
                ):
                    document.pop(field, None)
            documents.append(document)
    return tuple(sorted(documents, key=lambda item: (str(item["kind"]), str(item["id"]))))


def definition_impacts(documents: tuple[Document, ...], semantic_id: str) -> list[dict[str, str]]:
    impacts: list[dict[str, str]] = []
    for document in documents:
        if document.get("id") == semantic_id:
            continue
        if _contains(document, semantic_id):
            impacts.append({"kind": str(document.get("kind")), "id": str(document.get("id"))})
    return sorted(impacts, key=lambda item: (item["kind"], item["id"]))


def _contains(value: object, expected: str) -> bool:
    if isinstance(value, dict):
        return any(_contains(item, expected) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains(item, expected) for item in value)
    return value == expected


def _decode_documents(value: object) -> tuple[Document, ...]:
    decoded = value if isinstance(value, list) else json.loads(str(value))
    if not isinstance(decoded, list) or not all(isinstance(item, dict) for item in decoded):
        raise ValueError("INVALID_STORED_DRAFT")
    return tuple(dict(item) for item in decoded)


def _compile(documents: tuple[Document, ...]) -> CompiledBundle:
    inputs = [(f"draft/{index}.json", document) for index, document in enumerate(documents)]
    result = compile_documents(inputs, mapping_compiler=BuiltinMappingCompiler())
    if not result.ok or result.bundle is None:
        raise InvalidDraft(result.diagnostics)
    return result.bundle

"""Immutable release registry on PostgreSQL metadata."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.engine import Engine

from semaloom.core.bundle import CompiledBundle
from semaloom.core.digest import sha256_digest


class StaleRevision(RuntimeError):
    pass


class Registry:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def publish(self, bundle: CompiledBundle, *, publisher: str) -> str:
        payload = bundle.model_dump(mode="json", by_alias=True, exclude_none=True)
        _verify_digest(payload, bundle.digest)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO semantic_release(digest, payload, publisher)
                    VALUES (:digest, CAST(:payload AS jsonb), :publisher)
                    ON CONFLICT (digest) DO NOTHING
                    """
                ),
                {
                    "digest": bundle.digest,
                    "payload": json.dumps(payload),
                    "publisher": publisher,
                },
            )
        return bundle.digest

    def activate(self, environment: str, digest: str, *, expected_revision: int | None) -> int:
        with self.engine.begin() as conn:
            row = conn.execute(
                text("SELECT digest, revision FROM environment_pointer WHERE environment = :env"),
                {"env": environment},
            ).first()
            if row is None:
                conn.execute(
                    text(
                        """
                        INSERT INTO environment_pointer(environment, digest, revision)
                        VALUES (:env, :digest, 1)
                        """
                    ),
                    {"env": environment, "digest": digest},
                )
                return 1
            if expected_revision is not None and int(row.revision) != expected_revision:
                raise StaleRevision("environment revision conflict")
            conn.execute(
                text(
                    """
                    UPDATE environment_pointer
                    SET digest = :digest, revision = revision + 1
                    WHERE environment = :env
                    """
                ),
                {"env": environment, "digest": digest},
            )
            return int(row.revision) + 1

    def current(self, environment: str) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT digest FROM environment_pointer WHERE environment = :env"),
                {"env": environment},
            ).first()
        return None if row is None else str(row.digest)

    def load(self, digest: str) -> CompiledBundle:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT payload FROM semantic_release WHERE digest = :digest"),
                {"digest": digest},
            ).first()
        if row is None:
            raise KeyError(digest)
        payload = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
        bundle = CompiledBundle.model_validate(payload)
        _verify_digest(payload, digest)
        return bundle


def _verify_digest(payload: dict[str, object], expected: str) -> None:
    unsigned = dict(payload)
    claimed = unsigned.pop("digest", None)
    if claimed != expected or sha256_digest(unsigned) != expected:
        raise ValueError("RELEASE_DIGEST_MISMATCH")

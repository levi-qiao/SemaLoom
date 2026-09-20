"""Immutable release registry on PostgreSQL metadata."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from semaloom.core.bundle import CompiledBundle
from semaloom.core.digest import verify_release_digest


class StaleRevision(RuntimeError):
    pass


class Registry:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def publish(self, bundle: CompiledBundle, *, publisher: str) -> str:
        with self.engine.begin() as conn:
            return self.publish_in(conn, bundle, publisher=publisher)

    def publish_in(self, conn: Connection, bundle: CompiledBundle, *, publisher: str) -> str:
        payload = bundle.model_dump(mode="json", by_alias=True, exclude_none=True)
        verify_release_digest(payload, bundle.digest)
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
            return self.activate_in(conn, environment, digest, expected_revision=expected_revision)

    def activate_in(
        self,
        conn: Connection,
        environment: str,
        digest: str,
        *,
        expected_revision: int | None,
    ) -> int:
        exists = conn.execute(
            text("SELECT 1 FROM semantic_release WHERE digest = :digest"),
            {"digest": digest},
        ).first()
        if exists is None:
            raise KeyError(digest)
        row = conn.execute(
            text("SELECT digest, revision FROM environment_pointer WHERE environment = :env"),
            {"env": environment},
        ).first()
        if row is None:
            if expected_revision not in (None, 0):
                raise StaleRevision("environment revision conflict")
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
        updated = conn.execute(
            text(
                """
                UPDATE environment_pointer
                SET digest = :digest, revision = revision + 1
                WHERE environment = :env AND revision = :expected_revision
                """
            ),
            {
                "env": environment,
                "digest": digest,
                "expected_revision": int(row.revision),
            },
        )
        if updated.rowcount != 1:
            raise StaleRevision("environment revision conflict")
        return int(row.revision) + 1

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.begin() as conn:
            yield conn

    def pointer(self, environment: str) -> tuple[str | None, int]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT digest, revision FROM environment_pointer WHERE environment = :env"),
                {"env": environment},
            ).first()
        return (None, 0) if row is None else (str(row.digest), int(row.revision))

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
        verify_release_digest(payload, digest)
        return bundle

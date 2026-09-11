"""Opaque, revocable Studio sessions stored in the control-plane database."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from semaloom.runtime.auth import RequestActor


@dataclass(frozen=True)
class NewSession:
    token: str
    csrf_token: str
    actor: RequestActor
    expires_at: datetime


class StudioSessionService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create(
        self, *, tenant: str, subject: str, roles: tuple[str, ...], ttl_minutes: int = 60
    ) -> NewSession:
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO studio_session(
                      session_hash, tenant_id, subject, roles, csrf_hash, expires_at
                    ) VALUES (
                      :session_hash, :tenant_id, :subject, CAST(:roles AS jsonb),
                      :csrf_hash, :expires_at
                    )
                    """
                ),
                {
                    "session_hash": _digest(token),
                    "tenant_id": tenant,
                    "subject": subject,
                    "roles": json.dumps(roles),
                    "csrf_hash": _digest(csrf_token),
                    "expires_at": expires_at,
                },
            )
        return NewSession(
            token=token,
            csrf_token=csrf_token,
            actor=RequestActor(tenant=tenant, subject=subject, roles=roles),
            expires_at=expires_at,
        )

    def resolve(self, token: str) -> RequestActor | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT tenant_id, subject, roles FROM studio_session
                    WHERE session_hash = :session_hash AND revoked_at IS NULL
                      AND expires_at > now()
                    """
                ),
                {"session_hash": _digest(token)},
            ).first()
        if row is None:
            return None
        roles = row.roles if isinstance(row.roles, list) else json.loads(row.roles)
        return RequestActor(
            tenant=str(row.tenant_id),
            subject=str(row.subject),
            roles=tuple(str(item) for item in roles),
        )

    def verify_csrf(self, token: str, csrf_token: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT 1 FROM studio_session
                    WHERE session_hash = :session_hash AND csrf_hash = :csrf_hash
                      AND revoked_at IS NULL AND expires_at > now()
                    """
                ),
                {"session_hash": _digest(token), "csrf_hash": _digest(csrf_token)},
            ).first()
        return row is not None

    def revoke(self, token: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE studio_session SET revoked_at = now()
                    WHERE session_hash = :session_hash AND revoked_at IS NULL
                    """
                ),
                {"session_hash": _digest(token)},
            )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

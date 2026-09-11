"""Tenant-scoped integration profiles without stored secret values."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

SOURCE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,63}$")
REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{1,127}$")


@dataclass(frozen=True)
class SourceProfile:
    source_id: str
    revision: int
    label: str
    provider: str
    binding_ref: str
    secret_ref: str | None
    settings: dict[str, Any]
    validation_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "revision": self.revision,
            "label": self.label,
            "provider": self.provider,
            "bindingRef": self.binding_ref,
            "secretRef": self.secret_ref,
            "settings": self.settings,
            "validationStatus": self.validation_status,
        }


class SourceRevisionConflict(RuntimeError):
    pass


class SourceProfileService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self, tenant: str) -> list[SourceProfile]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT source_id, revision, label, provider, binding_ref, secret_ref,
                           settings, validation_status
                    FROM studio_source_profile
                    WHERE tenant_id = :tenant_id
                    ORDER BY source_id
                    """
                ),
                {"tenant_id": tenant},
            ).all()
        return [_profile(row) for row in rows]

    def get(self, tenant: str, source_id: str) -> SourceProfile:
        profiles = [item for item in self.list(tenant) if item.source_id == source_id]
        if not profiles:
            raise KeyError(source_id)
        return profiles[0]

    def set_validation(self, tenant: str, source_id: str, status: str) -> SourceProfile:
        if status not in {"VALID", "INVALID", "UNAVAILABLE"}:
            raise ValueError("INVALID_VALIDATION_STATUS")
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE studio_source_profile SET validation_status = :status, updated_at = now()
                    WHERE tenant_id = :tenant_id AND source_id = :source_id
                    RETURNING source_id, revision, label, provider, binding_ref, secret_ref,
                              settings, validation_status
                    """
                ),
                {"tenant_id": tenant, "source_id": source_id, "status": status},
            ).first()
        if row is None:
            raise KeyError(source_id)
        return _profile(row)

    def ensure_defaults(self, tenant: str, actor: str) -> None:
        defaults = (
            ("tax_pg", "Tax PostgreSQL", "postgres", "env:SEMALOOM_TAX_DATABASE_URL"),
            ("orders_pg", "Orders PostgreSQL", "postgres", "env:SEMALOOM_ORDERS_DATABASE_URL"),
            (
                "suppliers_pg",
                "Suppliers PostgreSQL",
                "postgres",
                "env:SEMALOOM_SUPPLIERS_DATABASE_URL",
            ),
            (
                "proc_draft_api",
                "Procurement API",
                "openapi",
                "env:SEMALOOM_PROCUREMENT_API_URL",
            ),
            ("tax_draft_api", "Tax action API", "openapi", "env:SEMALOOM_TAX_API_URL"),
        )
        existing = {item.source_id for item in self.list(tenant)}
        for source_id, label, provider, binding_ref in defaults:
            if source_id in existing:
                continue
            self.save(
                tenant=tenant,
                actor=actor,
                source_id=source_id,
                expected_revision=0,
                label=label,
                provider=provider,
                binding_ref=binding_ref,
                secret_ref=None,
                settings={"healthPath": "/health"} if provider == "openapi" else {},
            )

    def save(
        self,
        *,
        tenant: str,
        actor: str,
        source_id: str,
        expected_revision: int,
        label: str,
        provider: str,
        binding_ref: str,
        secret_ref: str | None,
        settings: dict[str, Any],
    ) -> SourceProfile:
        if SOURCE_ID.fullmatch(source_id) is None:
            raise ValueError("INVALID_SOURCE_ID")
        if provider not in {"postgres", "openapi"}:
            raise ValueError("INVALID_PROVIDER")
        if REFERENCE.fullmatch(binding_ref) is None:
            raise ValueError("INVALID_BINDING_REF")
        if secret_ref is not None and REFERENCE.fullmatch(secret_ref) is None:
            raise ValueError("INVALID_SECRET_REF")
        if _contains_secret_field(settings):
            raise ValueError("SECRET_VALUE_NOT_ALLOWED")
        encoded = json.dumps(settings)
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    WITH updated AS (
                      UPDATE studio_source_profile
                      SET revision = revision + 1, label = :label, provider = :provider,
                          binding_ref = :binding_ref, secret_ref = :secret_ref,
                          settings = CAST(:settings AS jsonb), validation_status = 'UNVALIDATED',
                          updated_by = :actor, updated_at = now()
                      WHERE tenant_id = :tenant_id AND source_id = :source_id
                        AND revision = :expected_revision
                      RETURNING source_id, revision, label, provider, binding_ref, secret_ref,
                                settings, validation_status
                    ), inserted AS (
                      INSERT INTO studio_source_profile(
                        tenant_id, source_id, revision, label, provider, binding_ref, secret_ref,
                        settings, validation_status, updated_by
                      )
                      SELECT :tenant_id, :source_id, 1, :label, :provider, :binding_ref,
                             :secret_ref, CAST(:settings AS jsonb), 'UNVALIDATED', :actor
                      WHERE :expected_revision = 0 AND NOT EXISTS (
                        SELECT 1 FROM studio_source_profile
                        WHERE tenant_id = :tenant_id AND source_id = :source_id
                      )
                      ON CONFLICT (tenant_id, source_id) DO NOTHING
                      RETURNING source_id, revision, label, provider, binding_ref, secret_ref,
                                settings, validation_status
                    )
                    SELECT * FROM updated UNION ALL SELECT * FROM inserted
                    """
                ),
                {
                    "tenant_id": tenant,
                    "source_id": source_id,
                    "expected_revision": expected_revision,
                    "label": label.strip() or source_id,
                    "provider": provider,
                    "binding_ref": binding_ref,
                    "secret_ref": secret_ref,
                    "settings": encoded,
                    "actor": actor,
                },
            ).first()
        if row is None:
            raise SourceRevisionConflict("REVISION_CONFLICT")
        return _profile(row)


def _profile(row: Any) -> SourceProfile:
    settings = row.settings if isinstance(row.settings, dict) else json.loads(row.settings)
    return SourceProfile(
        source_id=str(row.source_id),
        revision=int(row.revision),
        label=str(row.label),
        provider=str(row.provider),
        binding_ref=str(row.binding_ref),
        secret_ref=None if row.secret_ref is None else str(row.secret_ref),
        settings=dict(settings),
        validation_status=str(row.validation_status),
    )


def _contains_secret_field(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z]", "", str(key).lower())
            if any(
                marker in normalized
                for marker in ("password", "token", "secret", "credential", "authorization")
            ):
                return True
            if _contains_secret_field(nested):
                return True
    if isinstance(value, list | tuple):
        return any(_contains_secret_field(item) for item in value)
    return False

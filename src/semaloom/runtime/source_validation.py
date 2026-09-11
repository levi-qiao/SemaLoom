"""Online checks for environment-bound source profiles."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import text

from semaloom.adapters.postgres import engine_from_url
from semaloom.runtime.source_registry import SourceProfile


def validate_source(profile: SourceProfile, bindings: dict[str, str]) -> tuple[str, str]:
    value = resolve_environment_binding(profile.binding_ref, bindings)
    if value is None:
        return "INVALID", "BINDING_NOT_RESOLVED"
    if profile.provider == "postgres":
        engine = engine_from_url(value)
        try:
            with engine.connect() as conn, conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout = 5000"))
                conn.execute(text("SELECT 1"))
            return "VALID", "READ_ONLY_CONNECTION_OK"
        except Exception:  # adapter boundary normalizes driver-specific failures
            return "UNAVAILABLE", "SOURCE_UNAVAILABLE"
        finally:
            engine.dispose()
    health_path = profile.settings.get("healthPath", "/health")
    if not isinstance(health_path, str) or not health_path.startswith("/"):
        return "INVALID", "INVALID_HEALTH_PATH"
    try:
        response = httpx.get(f"{value.rstrip('/')}{health_path}", timeout=5.0)
    except httpx.HTTPError:
        return "UNAVAILABLE", "SOURCE_UNAVAILABLE"
    if response.status_code < 200 or response.status_code >= 300:
        return "INVALID", "HEALTH_CHECK_FAILED"
    return "VALID", "HEALTH_CHECK_OK"


def validate_sources(
    profiles: list[SourceProfile], bindings: dict[str, str]
) -> list[tuple[SourceProfile, str, str]]:
    if not profiles:
        return []
    with ThreadPoolExecutor(max_workers=min(4, len(profiles))) as executor:
        outcomes = list(executor.map(lambda item: validate_source(item, bindings), profiles))
    return [
        (profile, status, reason)
        for profile, (status, reason) in zip(profiles, outcomes, strict=True)
    ]


def resolve_environment_binding(reference: str, bindings: dict[str, str]) -> str | None:
    configured = bindings.get(reference)
    if configured is not None:
        return configured
    if not reference.startswith("env:"):
        return None
    variable = reference.removeprefix("env:")
    if re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", variable) is None:
        return None
    return os.getenv(variable)

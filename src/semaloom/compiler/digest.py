"""Stable bundle digest. Field order in source YAML does not change the hash."""

from __future__ import annotations

from typing import Any

from semaloom.core.digest import canonical_json as canonical_json
from semaloom.core.digest import sha256_digest as sha256_digest


def physical_digest(physical: dict[str, Any]) -> str:
    return sha256_digest(physical)

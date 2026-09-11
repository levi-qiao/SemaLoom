"""Stable bundle digest. Field order in source YAML does not change the hash."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_digest(payload: object) -> str:
    encoded = canonical_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def physical_digest(physical: dict[str, Any]) -> str:
    return sha256_digest(physical)

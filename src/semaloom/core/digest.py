"""Canonical hashing shared by compilation and immutable release verification."""

from __future__ import annotations

import hashlib
import json


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def verify_release_digest(payload: dict[str, object], expected: str) -> None:
    """Verify integrity, not publisher identity or deployment approval."""
    unsigned = dict(payload)
    claimed = unsigned.pop("digest", None)
    if claimed != expected or sha256_digest(unsigned) != expected:
        raise ValueError("RELEASE_DIGEST_MISMATCH")

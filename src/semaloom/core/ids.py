"""Semantic identifiers and version strings."""

from __future__ import annotations

import re

SEMANTIC_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
PACK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
API_VERSION = "semaloom/v0.1"
CONTRACT_VERSION = "v0.1"
BUNDLE_FORMAT = "semaloom-bundle/v0.1"
IR_VERSION = "semaloom-ir/v0.1"


def is_semantic_id(value: str) -> bool:
    return SEMANTIC_ID_RE.fullmatch(value) is not None


def is_pack_id(value: str) -> bool:
    return PACK_ID_RE.fullmatch(value) is not None


def namespace_of(semantic_id: str) -> str:
    return semantic_id.split(".", 1)[0]


def belongs_to_namespace(semantic_id: str, namespace: str) -> bool:
    return semantic_id == namespace or semantic_id.startswith(f"{namespace}.")

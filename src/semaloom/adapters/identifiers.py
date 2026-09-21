"""Provider-owned validation for physical SQL identifiers; no SQL runtime imports."""

from __future__ import annotations

import re

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def require_ident(value: object, *, field: str) -> str:
    if not isinstance(value, str) or IDENT_RE.fullmatch(value) is None:
        raise ValueError(f"illegal identifier for {field}")
    return value

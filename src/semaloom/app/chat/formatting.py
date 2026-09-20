"""Exact decimal display shared by prose and browser projections."""

from typing import Any


def natural_number(value: Any) -> str:
    raw = str(value)
    if "." not in raw:
        return raw
    whole, fractional = raw.split(".", 1)
    if not whole.lstrip("-").isdigit() or not fractional.isdigit():
        return raw
    compact = f"{whole}.{fractional.rstrip('0')}".rstrip(".")
    return "0" if compact == "-0" else compact

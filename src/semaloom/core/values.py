"""Finite scalar values shared by the compiler and deterministic evaluator."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

Scalar = Decimal | bool | str | date | datetime


def scalar_value(value: str, value_type: str) -> Scalar:
    if len(value) > 4096:
        raise ValueError("scalar value exceeds size limit")
    if value_type in {"DECIMAL", "INTEGER"}:
        if len(value) > 128:
            raise ValueError("number exceeds size limit")
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid number") from exc
        if not number.is_finite() or (number != 0 and abs(number.adjusted()) > 128):
            raise ValueError("number outside supported range")
        if value_type == "INTEGER" and number != number.to_integral_value():
            raise ValueError("integer requires a whole number")
        return number
    if value_type == "BOOLEAN":
        if value.lower() not in {"true", "false"}:
            raise ValueError("boolean requires true or false")
        return value.lower() == "true"
    if value_type == "STRING":
        return value
    if value_type == "DATE":
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("date requires YYYY-MM-DD")
        return parsed
    if value_type == "DATETIME":
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            raise ValueError("datetime requires a timezone")
        return timestamp
    raise ValueError("unsupported value type")

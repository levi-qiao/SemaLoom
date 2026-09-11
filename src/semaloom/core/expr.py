"""Bounded typed expression IR stored as normalized dicts. No eval/exec."""

from __future__ import annotations

from typing import Any, Literal, cast

RoundingMode = Literal["ROUND_HALF_UP", "ROUND_HALF_EVEN"]
ARITHMETIC_OPS = frozenset({"add", "sub", "mul", "div"})
COMPARE_OPS = frozenset({"eq", "ne", "lt", "le", "gt", "ge"})
BOOL_OPS = frozenset({"and", "or"})
LEAF_OPS = frozenset({"decimal", "bool", "ref"})
ALLOWED_OPS = ARITHMETIC_OPS | COMPARE_OPS | BOOL_OPS | LEAF_OPS | {"not", "round"}
Expr = dict[str, Any]


def parse_expr(data: object) -> Expr:
    if not isinstance(data, dict):
        raise ValueError("expression must be a mapping")
    unknown = set(data) - {"op", "value", "name", "args", "arg", "places", "mode"}
    if unknown:
        raise ValueError(f"unknown expression fields: {sorted(unknown)}")
    op = data.get("op")
    if op not in ALLOWED_OPS:
        raise ValueError(f"unsupported op {op!r}")
    if op == "decimal":
        value = data.get("value")
        if not isinstance(value, str) or value.strip() == "":
            raise ValueError("decimal value must be a non-empty string")
        return {"op": "decimal", "value": value}
    if op == "bool":
        value = data.get("value")
        if not isinstance(value, bool):
            raise ValueError("bool value must be boolean")
        return {"op": "bool", "value": value}
    if op == "ref":
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("ref name is required")
        return {"op": "ref", "name": name}
    if op == "not":
        return {"op": "not", "arg": parse_expr(data.get("arg"))}
    if op == "round":
        places = data.get("places")
        mode = data.get("mode", "ROUND_HALF_UP")
        if not isinstance(places, int) or places < 0:
            raise ValueError("round places must be a non-negative int")
        if mode not in {"ROUND_HALF_UP", "ROUND_HALF_EVEN"}:
            raise ValueError("unsupported rounding mode")
        return {
            "op": "round",
            "value": parse_expr(data.get("value")),
            "places": places,
            "mode": mode,
        }
    args = data.get("args")
    if not isinstance(args, list) or len(args) < 2:
        raise ValueError(f"{op} requires at least two args")
    if op in COMPARE_OPS and len(args) != 2:
        raise ValueError(f"{op} requires exactly two args")
    return {"op": op, "args": [parse_expr(item) for item in args]}


def collect_refs(expr: Expr) -> tuple[str, ...]:
    names: list[str] = []
    _walk_refs(expr, names)
    return tuple(dict.fromkeys(names))


def _walk_refs(expr: Expr, names: list[str]) -> None:
    op = expr.get("op")
    if op == "ref":
        names.append(cast(str, expr["name"]))
        return
    if op == "not":
        _walk_refs(cast(Expr, expr["arg"]), names)
        return
    if op == "round":
        _walk_refs(cast(Expr, expr["value"]), names)
        return
    for child in expr.get("args", []):
        _walk_refs(cast(Expr, child), names)

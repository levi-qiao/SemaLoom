"""Bounded typed expression IR stored as normalized dicts. No eval/exec."""

from __future__ import annotations

from typing import Any, Literal, cast

from semaloom.core.values import scalar_value

RoundingMode = Literal["ROUND_HALF_UP", "ROUND_HALF_EVEN"]
ARITHMETIC_OPS = frozenset({"add", "sub", "mul", "div"})
COMPARE_OPS = frozenset({"eq", "ne", "lt", "le", "gt", "ge"})
BOOL_OPS = frozenset({"and", "or"})
LEAF_OPS = frozenset({"decimal", "bool", "string", "date", "datetime", "ref"})
ALLOWED_OPS = ARITHMETIC_OPS | COMPARE_OPS | BOOL_OPS | LEAF_OPS | {"not", "round"}
Expr = dict[str, Any]


def parse_expr(data: object) -> Expr:
    return _parse_expr(data, 0, [256])


def _parse_expr(data: object, depth: int, budget: list[int]) -> Expr:
    budget[0] -= 1
    if depth > 32 or budget[0] < 0:
        raise ValueError("expression exceeds depth or node budget")
    if not isinstance(data, dict):
        raise ValueError("expression must be a mapping")
    unknown = set(data) - {"op", "value", "name", "args", "arg", "places", "mode"}
    if unknown:
        raise ValueError(f"unknown expression fields: {sorted(unknown)}")
    op = data.get("op")
    if op not in ALLOWED_OPS:
        raise ValueError(f"unsupported op {op!r}")
    if op in {"decimal", "string", "date", "datetime"}:
        value = data.get("value")
        if not isinstance(value, str):
            raise ValueError("scalar literal must be a string")
        scalar_value(value, str(op).upper())
        return {"op": op, "value": value}
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
        return {"op": "not", "arg": _parse_expr(data.get("arg"), depth + 1, budget)}
    if op == "round":
        places = data.get("places")
        mode = data.get("mode", "ROUND_HALF_UP")
        if type(places) is not int or not 0 <= places <= 28:
            raise ValueError("round places must be an integer in 0..28")
        if mode not in {"ROUND_HALF_UP", "ROUND_HALF_EVEN"}:
            raise ValueError("unsupported rounding mode")
        return {
            "op": "round",
            "value": _parse_expr(data.get("value"), depth + 1, budget),
            "places": places,
            "mode": mode,
        }
    args = data.get("args")
    if not isinstance(args, list) or len(args) < 2:
        raise ValueError(f"{op} requires at least two args")
    if op in COMPARE_OPS and len(args) != 2:
        raise ValueError(f"{op} requires exactly two args")
    return {"op": op, "args": [_parse_expr(item, depth + 1, budget) for item in args]}


def expression_type(expr: Expr, inputs: dict[str, str]) -> str:
    op = expr["op"]
    if op == "ref":
        if expr["name"] not in inputs:
            raise ValueError("unknown input reference")
        return inputs[expr["name"]]
    if op in {"decimal", "bool", "string", "date", "datetime"}:
        return "BOOLEAN" if op == "bool" else str(op).upper()
    children = [expr["arg"]] if op == "not" else [expr["value"]] if op == "round" else expr["args"]
    types = [expression_type(child, inputs) for child in children]
    numeric = all(t in {"DECIMAL", "INTEGER"} for t in types)
    if op in ARITHMETIC_OPS | {"round"}:
        if not numeric:
            raise ValueError("arithmetic requires numeric inputs")
        return "DECIMAL"
    if op in BOOL_OPS | {"not"}:
        if any(t != "BOOLEAN" for t in types):
            raise ValueError("boolean operation requires boolean inputs")
        return "BOOLEAN"
    if not numeric and len(set(types)) != 1:
        raise ValueError("comparison requires matching input types")
    if op not in {"eq", "ne"} and types[0] == "BOOLEAN":
        raise ValueError("boolean values are not ordered")
    return "BOOLEAN"


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

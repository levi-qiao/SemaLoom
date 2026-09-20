"""Reject ``Field(alias=...)``, which poisons Pyright constructors."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FieldAliasUse:
    path: Path
    line: int
    alias: str


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal_str(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return "<non-literal>"


def collect_field_alias_uses(scan_root: Path) -> list[FieldAliasUse]:
    found: list[FieldAliasUse] = []
    if not scan_root.exists():
        return found
    for path in sorted(scan_root.rglob("*.py")):
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node.func) != "Field":
                continue
            for keyword in node.keywords:
                if keyword.arg != "alias":
                    continue
                found.append(
                    FieldAliasUse(path=path, line=node.lineno, alias=_literal_str(keyword.value))
                )
    return found

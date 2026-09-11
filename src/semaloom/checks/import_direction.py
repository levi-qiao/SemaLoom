"""Reject core and shared-compiler imports of adapters or domain packs."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import semaloom

FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "semaloom.adapters",
    "semaloom.domains",
    "examples",
)

PROTECTED_PACKAGES: tuple[str, ...] = (
    "semaloom.core",
    "semaloom.compiler",
)


@dataclass(frozen=True, slots=True)
class ImportViolation:
    module: str
    path: Path
    line: int
    imported: str


def package_root() -> Path:
    """Return the directory that contains the installed `semaloom` package."""

    init_file = getattr(semaloom, "__file__", None)
    if init_file is None:
        raise RuntimeError("semaloom package has no __file__; cannot scan imports")
    return Path(init_file).resolve().parent


def is_forbidden_import(imported: str) -> bool:
    return any(
        imported == prefix or imported.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES
    )


def is_protected_module(module: str, protected: Sequence[str] = PROTECTED_PACKAGES) -> bool:
    return any(module == package or module.startswith(f"{package}.") for package in protected)


def module_name_for(file_path: Path, *, scan_root: Path, top_level: str) -> str:
    relative = file_path.resolve().relative_to(scan_root.resolve())
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((top_level, *parts)) if parts else top_level


def _package_parts(module: str, *, is_init: bool) -> list[str]:
    parts = module.split(".")
    if not is_init:
        parts = parts[:-1]
    return parts


def _absolute_from_import(module: str, node: ast.ImportFrom, *, is_init: bool) -> list[str]:
    if node.level == 0:
        base = node.module or ""
        names = [base] if base else []
        if base:
            names.extend(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        return names

    parts = _package_parts(module, is_init=is_init)
    up = node.level - 1
    if up > len(parts):
        return []
    if up:
        parts = parts[:-up]
    base = ".".join(parts)
    if node.module:
        abs_module = f"{base}.{node.module}" if base else node.module
    else:
        abs_module = base
    names = [abs_module] if abs_module else []
    if abs_module:
        names.extend(f"{abs_module}.{alias.name}" for alias in node.names if alias.name != "*")
    elif node.module is None:
        names.extend(alias.name for alias in node.names if alias.name != "*")
    return names


def imported_modules(source: str, *, module: str, is_init: bool) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.extend(
                (node.lineno, imported)
                for imported in _absolute_from_import(module, node, is_init=is_init)
                if imported
            )
    return found


def iter_python_files(root: Path) -> Iterable[Path]:
    yield from sorted(path for path in root.rglob("*.py") if path.is_file())


def resolve_package_dir(scan_root: Path, *, top_level: str = "semaloom") -> Path:
    """Accept either the package directory or a parent that contains it."""

    nested = scan_root / top_level
    if nested.is_dir() and (nested / "__init__.py").is_file():
        return nested
    return scan_root


def collect_violations(
    scan_root: Path,
    *,
    top_level: str = "semaloom",
    protected: Sequence[str] = PROTECTED_PACKAGES,
) -> list[ImportViolation]:
    """Scan a source tree and return forbidden imports from protected packages."""

    violations: list[ImportViolation] = []
    if not scan_root.exists():
        return violations
    package_dir = resolve_package_dir(scan_root, top_level=top_level)
    for file_path in iter_python_files(package_dir):
        module = module_name_for(file_path, scan_root=package_dir, top_level=top_level)
        if not is_protected_module(module, protected):
            continue
        source = file_path.read_text(encoding="utf-8")
        is_init = file_path.name == "__init__.py"
        for line, imported in imported_modules(source, module=module, is_init=is_init):
            if is_forbidden_import(imported):
                violations.append(
                    ImportViolation(
                        module=module,
                        path=file_path,
                        line=line,
                        imported=imported,
                    )
                )
    return violations


def check_import_direction(scan_root: Path | None = None) -> list[ImportViolation]:
    """Check the real installed or editable `semaloom` package."""

    root = scan_root if scan_root is not None else package_root()
    return collect_violations(root)

"""Repository static checks run at the start of a pytest session."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from semaloom.checks.field_alias import collect_field_alias_uses


class StaticCheckError(RuntimeError):
    pass


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd()):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "semaloom").is_dir():
            return candidate
    raise StaticCheckError("cannot locate the SemaLoom repository root")


def _run(argv: Sequence[str], *, cwd: Path) -> None:
    print(f"static: {' '.join(argv)}", flush=True)
    completed = subprocess.run(list(argv), cwd=cwd, check=False)
    if completed.returncode != 0:
        raise StaticCheckError(f"{argv[0]} failed with exit {completed.returncode}")


def run_static_checks(root: Path | None = None, *, frontend: bool = True) -> None:
    root = root if root is not None else repo_root()
    package = root / "src" / "semaloom"
    uses = collect_field_alias_uses(package)
    if uses:
        listing = "\n".join(f"{item.path}:{item.line} Field(alias={item.alias!r})" for item in uses)
        raise StaticCheckError(
            "Field(alias=...) makes Pyright/basedpyright treat the JSON name as "
            "the constructor keyword. Use wire_config()/alias_generator, or "
            "validation_alias+serialization_alias when the wire name is not "
            f"to_camel(field):\n{listing}"
        )
    python = sys.executable
    _run([python, "-m", "ruff", "format", "--check", "."], cwd=root)
    _run([python, "-m", "ruff", "check", "."], cwd=root)
    _run([python, "-m", "mypy"], cwd=root)
    if frontend:
        _run_frontend(root)


def _run_frontend(root: Path) -> None:
    frontend = root / "frontend"
    if not (frontend / "package.json").is_file():
        return
    if not (frontend / "node_modules").is_dir():
        print("static: skip frontend tsc (frontend/node_modules missing)", flush=True)
        return
    pnpm = shutil.which("pnpm")
    if pnpm is not None:
        _run([pnpm, "check"], cwd=frontend)
        return
    corepack = shutil.which("corepack")
    if corepack is not None:
        _run([corepack, "pnpm", "check"], cwd=frontend)
        return
    print("static: skip frontend tsc (pnpm not on PATH)", flush=True)

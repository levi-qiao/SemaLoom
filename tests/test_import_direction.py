from __future__ import annotations

from pathlib import Path

import pytest

from semaloom.checks.import_direction import check_import_direction, collect_violations


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_shipped_package_has_no_import_direction_violations() -> None:
    assert check_import_direction() == []


def test_collect_violations_rejects_core_importing_adapters(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        {
            "core/__init__.py": "from semaloom.adapters.postgres import connect\n",
        },
    )

    violations = collect_violations(tmp_path)

    assert violations
    assert any("adapters" in violation.imported for violation in violations)


def test_collect_violations_rejects_core_importing_domains(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        {
            "core/__init__.py": "from semaloom.domains.tax import pack\n",
        },
    )

    violations = collect_violations(tmp_path)

    assert violations
    assert any("domains" in violation.imported for violation in violations)


def test_collect_violations_rejects_compiler_importing_examples(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        {
            "compiler/__init__.py": "from examples.tax.domain import objects\n",
        },
    )

    violations = collect_violations(tmp_path)

    assert violations
    assert any(
        violation.imported == "examples" or violation.imported.startswith("examples.")
        for violation in violations
    )


def test_collect_violations_rejects_relative_core_import_of_adapters(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        {
            "core/widget.py": "from ..adapters import x\n",
        },
    )

    violations = collect_violations(tmp_path)

    assert violations
    assert any("adapters" in violation.imported for violation in violations)


@pytest.mark.parametrize("package", ["core", "compiler"])
@pytest.mark.parametrize("dependency", ["semaloom.sdk", "semaloom.app", "sqlalchemy", "httpx"])
def test_core_cannot_reach_infrastructure_through_another_entry(
    tmp_path: Path, package: str, dependency: str
) -> None:
    _write_tree(tmp_path, {f"{package}/bad.py": f"import {dependency}\n"})
    assert collect_violations(tmp_path)

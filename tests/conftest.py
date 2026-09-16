"""Run repository static checks once per pytest session."""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--no-static",
        action="store_true",
        default=False,
        help="Skip ruff, mypy, Field(alias=) and frontend tsc session checks.",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    if session.config.option.collectonly:
        return
    if session.config.getoption("--no-static") or os.environ.get("SEMALOOM_NO_STATIC") == "1":
        return
    from semaloom.checks.static import StaticCheckError, run_static_checks

    try:
        run_static_checks()
    except StaticCheckError as exc:
        pytest.exit(str(exc), returncode=1)

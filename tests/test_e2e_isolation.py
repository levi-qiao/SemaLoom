"""The disposable browser server must never reuse a running database."""

from pathlib import Path
from unittest.mock import patch

import pytest

from tests import e2e_isolated_chat_server as server


def test_occupied_database_port_is_rejected_before_any_write(tmp_path: Path) -> None:
    with (
        patch.object(server, "_port_open", return_value=True),
        patch.object(server.subprocess, "check_call") as spawn,
        patch.object(server, "create_engine") as connect,
        pytest.raises(RuntimeError, match="Refusing to reuse occupied"),
    ):
        server.ensure_postgres(tmp_path)
    spawn.assert_not_called()
    connect.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_postgres_binary_uses_explicit_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "pg_ctl"
    executable.touch()
    monkeypatch.setenv("SEMALOOM_E2E_PG_BINDIR", str(tmp_path))
    assert server.postgres_binary("pg_ctl") == str(executable)
    with pytest.raises(RuntimeError, match="missing initdb"):
        server.postgres_binary("initdb")

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from semaloom.app.cli import main
from semaloom.app.factory import create_app
from semaloom.identity import build_identity, distribution_version


def test_build_identity_local_dev_observable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEMALOOM_PROFILE", raising=False)

    identity = build_identity()

    assert identity.product == "semaloom"
    assert identity.version == distribution_version()
    assert identity.semantic_contract == "v0.1"
    assert identity.profile == "local-dev"


def test_cli_identity_matches_build_identity(capsys: pytest.CaptureFixture[str]) -> None:
    expected = build_identity().to_dict()
    exit_code = main(["identity"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload == expected


def test_cli_default_prints_identity(capsys: pytest.CaptureFixture[str]) -> None:
    expected = build_identity().to_dict()
    exit_code = main([])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload == expected


def test_identity_http_endpoint_matches_build_identity() -> None:
    expected = build_identity().to_dict()
    client = TestClient(create_app(load_services=False))

    response = client.get("/identity")

    assert response.status_code == 200
    assert response.json() == expected


def test_non_demo_http_profile_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="production identity requires"):
        create_app(profile="production", load_services=True)

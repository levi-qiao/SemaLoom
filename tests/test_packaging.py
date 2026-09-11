"""A49 T00: built artifacts include LICENSE and install as the shipped package."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from semaloom.identity import build_identity


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    out_dir = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        ["uv", "build", "--out-dir", str(out_dir)],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"uv build failed:\n{result.stdout}\n{result.stderr}")
    wheels = list(out_dir.glob("*.whl"))
    sdists = list(out_dir.glob("*.tar.gz"))
    assert wheels, "uv build produced no wheel"
    assert sdists, "uv build produced no sdist"
    return sdists[0], wheels[0]


def test_sdist_contains_license(built_artifacts: tuple[Path, Path]) -> None:
    sdist, _wheel = built_artifacts
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
    assert any(name.endswith("LICENSE") for name in names), names


def test_wheel_contains_license(built_artifacts: tuple[Path, Path]) -> None:
    _sdist, wheel = built_artifacts
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    assert any(name.endswith("LICENSE") for name in names), names


def test_wheel_installs_and_prints_identity(
    built_artifacts: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    _sdist, wheel = built_artifacts
    venv = tmp_path / "venv"
    python = venv / "bin" / "python"
    subprocess.run(["uv", "venv", str(venv), "--python", "3.13"], check=True, capture_output=True)
    install = subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(wheel)],
        check=False,
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:
        pytest.fail(f"wheel install failed:\n{install.stdout}\n{install.stderr}")
    env = os.environ.copy()
    env["SEMALOOM_PROFILE"] = "local-dev"
    launched = subprocess.run(
        [str(venv / "bin" / "semaloom")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if launched.returncode != 0:
        pytest.fail(f"installed semaloom failed:\n{launched.stdout}\n{launched.stderr}")
    assert json.loads(launched.stdout) == build_identity(profile="local-dev").to_dict()

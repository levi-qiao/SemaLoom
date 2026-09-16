"""A49 T00/T08A: built artifacts include LICENSE, Studio static, and no private dumps."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from semaloom.identity import build_identity

PRIVATE_FILENAMES = frozenset(
    {
        "runtime.env",
        "pseudonym.key",
        "remote.env",
    }
)
PRIVATE_NAME_FRAGMENTS = (
    "sample_taxpayer",
    "sample_declaration",
)
OMITTED_FROM_SDIST = (
    "docs/local-business-samples.md",
    "ops/data/import_remote_dev.py",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _archive_names(sdist: Path, wheel: Path) -> tuple[list[str], list[str]]:
    with tarfile.open(sdist, "r:gz") as archive:
        sdist_names = archive.getnames()
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
    return sdist_names, wheel_names


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


def test_sdist_contains_linked_contributor_instructions(
    built_artifacts: tuple[Path, Path],
) -> None:
    sdist, _wheel = built_artifacts
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
    assert any(name.endswith("AGENTS.md") for name in names), names
    assert any(name.endswith("docs/DESIGN.md") for name in names), names


def test_sdist_contains_public_synthetic_examples(built_artifacts: tuple[Path, Path]) -> None:
    sdist, _wheel = built_artifacts
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
    assert any(name.endswith("examples/tax/domain/pack.yaml") for name in names), names
    assert any(name.endswith("examples/procurement/domain/pack.yaml") for name in names), names


def test_wheel_contains_license(built_artifacts: tuple[Path, Path]) -> None:
    _sdist, wheel = built_artifacts
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    assert any(name.endswith("LICENSE") for name in names), names


def test_wheel_contains_built_studio_assets(built_artifacts: tuple[Path, Path]) -> None:
    _sdist, wheel = built_artifacts
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        html = archive.read("semaloom/app/static/index.html").decode("utf-8")
    assert "semaloom/app/static/index.html" in names
    assert any(
        name.startswith("semaloom/app/static/assets/") and name.endswith(".js") for name in names
    )
    assert any(
        name.startswith("semaloom/app/static/assets/") and name.endswith(".css") for name in names
    )
    assert "SemaLoom Studio" in html
    assert "/studio/assets/" in html
    assert ".js" in html
    assert ".css" in html


def test_artifacts_exclude_private_agent_state_and_dumps(
    built_artifacts: tuple[Path, Path],
) -> None:
    sdist, wheel = built_artifacts
    sdist_names, wheel_names = _archive_names(sdist, wheel)
    for label, names in (("sdist", sdist_names), ("wheel", wheel_names)):
        assert not any(".agents" in Path(name).parts for name in names), (label, names)
        assert not any(Path(name).name in PRIVATE_FILENAMES for name in names), (label, names)
        lowered = "\n".join(names).lower()
        for fragment in PRIVATE_NAME_FRAGMENTS:
            assert fragment not in lowered, (label, fragment)
        assert ".agents/" not in "\n".join(names)


def test_sdist_omits_private_sample_instructions(built_artifacts: tuple[Path, Path]) -> None:
    sdist, _wheel = built_artifacts
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
    for suffix in OMITTED_FROM_SDIST:
        assert not any(name.endswith(suffix) for name in names), names


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

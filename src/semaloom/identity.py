"""Runtime build identity for the local-development composition root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import metadata

from semaloom import __version__ as package_version

PRODUCT = "semaloom"
SEMANTIC_CONTRACT = "v0.1"
DEFAULT_PROFILE = "local-dev"
PROFILE_ENV = "SEMALOOM_PROFILE"


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    """Stable product identity for a running process.

    Timestamps and trace IDs are excluded so two launches of the same
    install produce the same observable.
    """

    product: str
    version: str
    semantic_contract: str
    profile: str

    def to_dict(self) -> dict[str, str]:
        return {
            "product": self.product,
            "profile": self.profile,
            "semantic_contract": self.semantic_contract,
            "version": self.version,
        }


def distribution_version() -> str:
    """Return the installed distribution version, falling back to the package constant."""

    try:
        return metadata.version("semaloom")
    except metadata.PackageNotFoundError:
        return package_version


def resolve_profile(profile: str | None = None) -> str:
    if profile is not None and profile != "":
        return profile
    env_profile = os.environ.get(PROFILE_ENV, "").strip()
    if env_profile:
        return env_profile
    return DEFAULT_PROFILE


def build_identity(*, profile: str | None = None) -> BuildIdentity:
    """Return the runtime/build identity for the current process."""

    return BuildIdentity(
        product=PRODUCT,
        version=distribution_version(),
        semantic_contract=SEMANTIC_CONTRACT,
        profile=resolve_profile(profile),
    )

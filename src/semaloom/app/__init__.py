"""Application composition root: assemble adapters and runtime in one process."""

from semaloom.app.cli import main
from semaloom.app.factory import create_app

__all__ = ["create_app", "main"]

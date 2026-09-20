"""Compile and runtime diagnostics. Truth values are not diagnostics."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    path: str
    message: str
    severity: Literal["error", "warning"] = "error"

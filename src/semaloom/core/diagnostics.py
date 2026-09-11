"""Compile and runtime diagnostics. Truth values are not diagnostics."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    path: str
    message: str
    severity: Literal["error", "warning"] = "error"


class DiagnosticList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[Diagnostic, ...] = Field(default_factory=tuple)

    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.items if item.severity == "error")

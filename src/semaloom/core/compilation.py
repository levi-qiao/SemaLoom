"""Protocol-neutral seam for trusted integration mapping compilers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from semaloom.core.diagnostics import Diagnostic
from semaloom.core.model import MappingDef, MetricDef, ObjectTypeDef


class MappingCompiler(Protocol):
    """Validate physical bindings and return their neutral semantic capabilities."""

    def compile_mappings(
        self,
        objects: Sequence[ObjectTypeDef],
        mappings: Sequence[MappingDef],
        diagnostics: list[Diagnostic],
    ) -> list[MappingDef]: ...

    def derive_metric(
        self, source: MappingDef, metric: MetricDef, mapping_id: str
    ) -> MappingDef: ...

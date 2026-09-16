"""Protocol-neutral read-provider contract used by the runtime."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from semaloom.core.model import MappingDef
from semaloom.core.results import Observation


class ObjectRead(BaseModel):
    """Normalized outcome of reading one business object from a source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["PRESENT", "MISSING", "UNAVAILABLE"]
    values: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    mapping_id: str
    source_id: str
    observed_at: str


class ReadProvider(Protocol):
    """Small runtime seam implemented by database and API adapters."""

    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: str,
        extra_filters: dict[str, str] | None = None,
    ) -> Observation: ...

    def fetch_object(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: str,
    ) -> ObjectRead: ...


class ObjectSearch(BaseModel):
    """A bounded page of source objects; has_more is never a completeness claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["PRESENT", "UNAVAILABLE"]
    rows: tuple[dict[str, Any], ...] = ()
    has_more: bool = False
    reason: str | None = None
    observed_at: str = ""

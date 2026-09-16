"""Compatibility translator from PopulationRequest onto SemanticQuery prepare/execute.

Deprecated: prefer SemanticQuery prepare/execute (Chat: prepare_semantic_query).
POST /v0.1/analyze remains only as a thin facade for legacy clients.
"""

from __future__ import annotations

from typing import Any

from semaloom.core.results import PopulationRequest
from semaloom.runtime.analysis import AnalysisError, execute_population
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService


def analyze_population(
    query: QueryService, request: PopulationRequest, actor: RequestActor
) -> dict[str, Any]:
    """Deprecated facade: translates PopulationRequest onto SemanticQuery."""
    try:
        return execute_population(query, request, actor)
    except AnalysisError as exc:
        raise ValueError(str(exc)) from exc

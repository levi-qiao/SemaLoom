"""Embedded read-only integration: one release, existing runtime, no app bootstrap."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from semaloom.adapters.mapping import BuiltinMappingCompiler
from semaloom.compiler import CompileResult, document_schemas
from semaloom.compiler import compile_documents as _compile_documents
from semaloom.compiler import compile_paths as _compile_paths
from semaloom.core.bundle import CompiledBundle
from semaloom.core.compilation import MappingCompiler
from semaloom.core.digest import verify_release_digest
from semaloom.core.ids import BUNDLE_FORMAT, IR_VERSION
from semaloom.core.provider import IdentityScalar, ReadProvider
from semaloom.core.results import (
    EvidenceEnvelope,
    MetricSelect,
    ObjectSearchRequest,
    ObjectSelect,
    QueryContext,
    QueryRequest,
)
from semaloom.core.semantic_query import (
    AnalysisError,
    PlanRef,
    PrepareResult,
    QueryResult,
    SemanticQuery,
)
from semaloom.runtime import analysis
from semaloom.runtime.auth import RequestActor, authorize_query
from semaloom.runtime.discovery import SemanticDiscovery
from semaloom.runtime.eval import EvaluationError, evaluate_claim_with_evidence
from semaloom.runtime.query import QueryService

__all__ = [
    "AnalysisError",
    "CompileResult",
    "CompiledBundle",
    "EvaluationError",
    "EvidenceEnvelope",
    "MappingCompiler",
    "MetricSelect",
    "ObjectSearchRequest",
    "ObjectSelect",
    "PlanRef",
    "PrepareResult",
    "QueryContext",
    "QueryRequest",
    "QueryResult",
    "ReadProvider",
    "RequestActor",
    "SemanticEngine",
    "SemanticQuery",
    "compile_documents",
    "compile_paths",
    "document_schemas",
]


def compile_paths(
    roots: Sequence[Path],
    *,
    mapping_compiler: MappingCompiler | None = None,
    catalog_snapshot: Mapping[str, Any] | None = None,
) -> CompileResult:
    """Compile trusted YAML with built-in profiles or an explicitly supplied compiler."""
    return _compile_paths(
        roots,
        mapping_compiler=mapping_compiler
        if mapping_compiler is not None
        else BuiltinMappingCompiler(),
        catalog_snapshot=catalog_snapshot,
    )


def compile_documents(
    documents: Sequence[object],
    *,
    mapping_compiler: MappingCompiler | None = None,
    catalog_snapshot: Mapping[str, Any] | None = None,
) -> CompileResult:
    """Compile canonical documents; compilation does not approve a release."""
    return _compile_documents(
        documents,
        mapping_compiler=mapping_compiler
        if mapping_compiler is not None
        else BuiltinMappingCompiler(),
        catalog_snapshot=catalog_snapshot,
    )


class SemanticEngine:
    """Read-only runtime bound to a private copy of one trusted semantic release.

    The host supplies approved definitions, authenticated actors and a trusted read
    provider. The host owns provider cleanup and current identity validation on
    every call. No credentials, metadata tables, fixtures or HTTP server are created.
    The existing tenant/role profile is reused; this is not a production IAM layer.
    """

    def __init__(self, bundle: CompiledBundle, provider: ReadProvider) -> None:
        payload = bundle.model_dump(mode="json", by_alias=True, exclude_none=True)
        verify_release_digest(payload, bundle.digest)
        pinned = CompiledBundle.model_validate(payload)
        if pinned.format_version != BUNDLE_FORMAT or pinned.ir_version != IR_VERSION:
            raise ValueError("UNSUPPORTED_RELEASE_VERSION")
        self._query = QueryService(pinned, provider)
        self._discovery = SemanticDiscovery(pinned)

    @property
    def release_digest(self) -> str:
        return self._query.bundle.digest

    def query(self, request: QueryRequest, *, actor: RequestActor) -> EvidenceEnvelope:
        """Read exact objects/metrics; missing, forbidden and source failure stay distinct."""
        return self._query.execute(request, actor)

    def prepare(self, request: SemanticQuery, *, actor: RequestActor) -> PrepareResult:
        """Return a plan, a clarification, an unsupported capability or a source failure."""
        return analysis.prepare(self._query, request, actor)

    def execute(self, plan: PlanRef, *, actor: RequestActor) -> QueryResult:
        """Recheck authorization and plan bindings before executing collection analysis."""
        return analysis.execute(self._query, plan, actor)

    def evaluate_claim(
        self,
        claim_id: str,
        *,
        actor: RequestActor,
        bindings: dict[str, IdentityScalar],
        period_from: str,
        period_to: str,
        dimensions: dict[str, str],
    ) -> EvidenceEnvelope:
        """Evaluate the declared policy/rule with source evidence, never model-generated truth."""
        if not authorize_query(actor, "query").allowed:
            raise PermissionError("FORBIDDEN")
        claim, observations, diagnostics, digest, activities = evaluate_claim_with_evidence(
            self._query.bundle,
            self._query,
            actor,
            claim_id=claim_id,
            bindings=bindings,
            period_from=period_from,
            period_to=period_to,
            dimensions=dimensions,
        )
        return EvidenceEnvelope(
            request_id=uuid.uuid4().hex,
            release_digest=digest,
            claims=(claim,),
            observations=observations,
            diagnostics=diagnostics,
            source_activities=activities,
            status="FAILED"
            if any(item.severity == "error" for item in diagnostics)
            else "SUCCEEDED",
        )

    def find_objects(self, request: ObjectSearchRequest, *, actor: RequestActor) -> dict[str, Any]:
        return self._query.find_objects(request, actor)

    def search(self, text: str, *, actor: RequestActor, limit: int = 20) -> dict[str, Any]:
        return self._discovery.search(text, actor, limit=limit)

    def describe(self, semantic_id: str, *, actor: RequestActor) -> dict[str, Any]:
        return self._discovery.describe(semantic_id, actor)

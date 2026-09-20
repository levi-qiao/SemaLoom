"""Embedded consumers use the same execution and failure semantics as the application."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from semaloom.compiler import compile_documents as compile_core
from semaloom.compiler.yaml_load import load_yaml_documents
from semaloom.core.diagnostics import Diagnostic
from semaloom.core.digest import sha256_digest
from semaloom.core.model import MappingDef, MetricDef, ObjectTypeDef
from semaloom.runtime.fixtures import configured_urls, load_synthetic
from semaloom.sdk import (
    AnalysisError,
    CompiledBundle,
    MetricSelect,
    QueryContext,
    QueryRequest,
    RequestActor,
    SemanticEngine,
    SemanticQuery,
    compile_documents,
    compile_paths,
)
from tests.test_business_analysis import ACTOR, financial_query  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
DENIED = RequestActor(tenant="tenant-a", subject="denied", roles=("guest",))
OTHER = RequestActor(tenant="tenant-b", subject="other", roles=("analyst",))


def point_request(identity: str) -> QueryRequest:
    return QueryRequest(
        api_version="semaloom/v0.1",
        select=(
            MetricSelect(metric="finance.review.declared_profit", bindings={"caseId": identity}),
        ),
        context=QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"}),
    )


def collection_request() -> SemanticQuery:
    return SemanticQuery.model_validate(
        {
            "apiVersion": "semaloom/v0.1",
            "metrics": [{"id": "finance.review.declared_profit", "aggregation": "SUM"}],
            "filters": {
                "kind": "PRED",
                "field": "taxYear",
                "op": "EQ",
                "value": {"valueType": "INTEGER", "value": 2024},
            },
            "missingPolicy": "reject",
        }
    )


def test_sdk_import_does_not_bootstrap_web_database_or_chat() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import semaloom.sdk; "
            "assert not any(n in sys.modules for n in "
            "('fastapi', 'sqlalchemy', 'semaloom.app.bootstrap', 'semaloom.runtime.fixtures'))",
        ],
        check=True,
    )


def test_documented_sdk_example_runs() -> None:
    load_synthetic()
    example = re.search(r"```python\n(.*?)\n```", (ROOT / "docs/python-sdk.md").read_text(), re.S)
    assert example is not None
    env = {**os.environ, "SEMALOOM_TAX_DATABASE_URL": configured_urls()["tax_pg"]}
    result = subprocess.run(
        [sys.executable, "-c", example.group(1)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "110.1000"


def test_sdk_point_reads_evidence_missing_and_tenant_isolation(financial_query: Any) -> None:  # noqa: F811
    engine = SemanticEngine(financial_query.bundle, financial_query.provider)
    result = engine.query(point_request("C1"), actor=ACTOR)
    assert result.status == "SUCCEEDED"
    assert result.observations[0].value == "100.01"
    assert result.source_activities
    assert result.release_digest == engine.release_digest
    assert engine.query(point_request("absent"), actor=ACTOR).observations[0].kind == "MISSING"
    assert engine.query(point_request("C1"), actor=OTHER).observations[0].value == "999"
    assert engine.query(point_request("C1"), actor=DENIED).observations[0].kind == "FORBIDDEN"
    with pytest.raises(PermissionError):
        engine.describe("finance.review.declared_profit", actor=DENIED)
    with pytest.raises(PermissionError):
        engine.evaluate_claim(
            "unknown.claim",
            actor=DENIED,
            bindings={},
            period_from="2024-01-01",
            period_to="2025-01-01",
            dimensions={},
        )
    assert "physical" not in engine.describe("finance.review.declared_profit", actor=ACTOR)


def test_sdk_prepare_execute_refuses_ambiguity_and_plan_retargeting(financial_query: Any) -> None:  # noqa: F811
    with financial_query.provider._engines["sample_pg"].begin() as conn:
        conn.execute(text("UPDATE sample_financial_review SET company_id=id"))
    engine = SemanticEngine(financial_query.bundle, financial_query.provider)
    incomplete = collection_request().model_copy(update={"filters": None})
    assert engine.prepare(incomplete, actor=ACTOR).status == "NEEDS_INPUT"
    prepared = engine.prepare(collection_request(), actor=ACTOR)
    assert prepared.status == "READY" and prepared.plan is not None
    result = engine.execute(prepared.plan, actor=ACTOR)
    assert result.values[0]["value"] == "300.03"
    with pytest.raises(PermissionError):
        engine.execute(prepared.plan, actor=DENIED)
    with pytest.raises(AnalysisError):
        engine.execute(prepared.plan, actor=OTHER)
    with pytest.raises(AnalysisError, match="VERSION_INVALID"):
        engine.execute(prepared.plan.model_copy(update={"release_digest": "other"}), actor=ACTOR)


def test_sdk_pins_nested_release_data_and_rejects_tampering(financial_query: Any) -> None:  # noqa: F811
    bundle = financial_query.bundle
    engine = SemanticEngine(bundle, financial_query.provider)
    mapping = next(m for m in bundle.mappings if m.id == "finance.review.declared_profit.pg")
    mapping.physical["table"] = "missing_table"
    assert engine.query(point_request("C1"), actor=ACTOR).observations[0].value == "100.01"
    with pytest.raises(ValueError, match="RELEASE_DIGEST_MISMATCH"):
        SemanticEngine(bundle, financial_query.provider)
    payload = bundle.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload["irVersion"] = "future"
    payload.pop("digest")
    payload["digest"] = sha256_digest(payload)
    with pytest.raises(ValueError, match="UNSUPPORTED_RELEASE_VERSION"):
        SemanticEngine(CompiledBundle.model_validate(payload), financial_query.provider)


def test_sdk_claims_keep_false_missing_and_source_error_distinct(financial_query: Any) -> None:  # noqa: F811
    engine = SemanticEngine(financial_query.bundle, financial_query.provider)
    for identity, truth in (("C1", "TRUE"), ("C2", "FALSE"), ("C3", "UNKNOWN")):
        result = engine.evaluate_claim(
            "finance.review.profitMatches",
            actor=ACTOR,
            bindings={"caseId": identity},
            period_from="2024-01-01",
            period_to="2025-01-01",
            dimensions={},
        )
        assert result.claims[0].truth == truth
        assert result.source_activities
        assert result.status == "SUCCEEDED"
    documents = [doc for _, doc in load_yaml_documents(ROOT / "examples/financial-review")]
    for doc in documents:
        if doc["kind"] == "Mapping" and doc["objectType"] == "finance.ReviewCase":
            doc["physical"]["table"] = "missing_relation"
    compiled = compile_documents(documents)
    assert compiled.bundle is not None, compiled.diagnostics
    broken = SemanticEngine(compiled.bundle, financial_query.provider)
    result = broken.evaluate_claim(
        "finance.review.profitMatches",
        actor=ACTOR,
        bindings={"caseId": "C1"},
        period_from="2024-01-01",
        period_to="2025-01-01",
        dimensions={},
    )
    assert result.status == "FAILED"
    assert result.claims[0].truth == "UNKNOWN"
    assert any(item.kind == "UNAVAILABLE" for item in result.observations)


class MemoryMappingCompiler:
    """A genuinely different physical protocol, with no SQL columns or API pointers."""

    def compile_mappings(
        self,
        objects: Sequence[ObjectTypeDef],
        mappings: Sequence[MappingDef],
        diagnostics: list[Diagnostic],
    ) -> list[MappingDef]:
        obj = objects[0]
        return [
            mapping.model_copy(
                update={
                    "identity_fields": obj.identity_keys,
                    "grain_fields": obj.identity_keys,
                    "property_fields": tuple(prop.id for prop in obj.properties),
                    "capabilities": ("POINT_READ",),
                }
            )
            for mapping in mappings
        ]

    def derive_metric(self, source: MappingDef, metric: MetricDef, mapping_id: str) -> MappingDef:
        return source.model_copy(update={"id": mapping_id, "target": metric.id})


def test_new_protocol_does_not_modify_shared_compiler() -> None:
    docs = [doc for _, doc in load_yaml_documents(ROOT / "examples/warehouse")]
    for doc in docs:
        if doc["kind"] in {"Mapping", "IntegrationBinding"}:
            doc["provider"] = "memory"
        if doc["kind"] == "Mapping":
            doc["physical"] = {"collection": "inventory"}
    compiled = compile_core(docs, mapping_compiler=MemoryMappingCompiler())
    assert compiled.ok, compiled.diagnostics
    assert compiled.bundle is not None
    assert all(mapping.provider == "memory" for mapping in compiled.bundle.mappings)
    assert compiled.bundle.metrics
    assert not compile_documents(docs).ok  # Built-in profiles must not guess a new protocol.


@pytest.mark.parametrize("pack", ["tax", "procurement", "warehouse", "financial-review"])
def test_sdk_compiles_every_shipped_domain(pack: str) -> None:
    result = compile_paths([ROOT / "examples" / pack])
    assert result.ok, result.diagnostics
    assert result.online_validation == "NOT_RUN"

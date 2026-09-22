"""Invalid semantic releases fail before touching business sources."""

from pathlib import Path
from typing import Any

import pytest

from semaloom.core.results import Observation
from semaloom.runtime.eval import evaluate_rule
from semaloom.sdk import compile_documents, compile_paths
from tests.test_compile import PROCUREMENT, TAX, _load


def rejected(documents: list[dict[str, Any]], code: str) -> None:
    result = compile_documents(documents)
    assert not result.ok
    assert code in {item.code for item in result.diagnostics}


def test_incompatible_currency_cannot_be_compiled_or_evaluated() -> None:
    documents = _load(TAX)
    metric = next(d for d in documents if d.get("id") == "tax.auditIncome")
    metric["unit"] = "USD"
    rejected(documents, "UNIT_MISMATCH")
    bundle = compile_paths([TAX]).bundle
    assert bundle is not None
    rule = next(r for r in bundle.rules if r.claim)
    observations = {
        spec.name: Observation(
            kind="PRESENT",
            target=spec.metric or "",
            value="100",
            value_type="DECIMAL",
            unit="CNY" if i == 0 else "USD",
        )
        for i, spec in enumerate(rule.inputs)
    }
    claim, diagnostics = evaluate_rule(rule, observations)
    assert claim.truth == "UNKNOWN"
    assert any(d.code == "UNIT_MISMATCH" for d in diagnostics)


@pytest.mark.parametrize("keys", [[], ["taxpayerId", "taxpayerId"]])
def test_identity_keys_must_be_nonempty_and_unique(keys: list[str]) -> None:
    documents = _load(TAX)
    obj = next(d for d in documents if d.get("id") == "tax.Taxpayer")
    obj["identityKeys"] = keys
    rejected(documents, "INVALID_DEFINITION")


def test_metric_grain_covers_complete_identity() -> None:
    documents = _load(TAX)
    metric = next(d for d in documents if d.get("id") == "tax.adjustmentAmount")
    metric["grain"] = ["taxYear"]
    rejected(documents, "INCOMPLETE_GRAIN")


@pytest.mark.parametrize("start,end", [("banana", "carrot"), ("2024-02-30", "2025-01-01")])
def test_policy_dates_are_real_dates(start: str, end: str) -> None:
    documents = _load(TAX)
    for doc in documents:
        if doc.get("kind") == "Policy":
            doc["interval"] = {"effectiveFrom": start, "effectiveTo": end}
    rejected(documents, "INVALID_DEFINITION")


def test_policy_dimensions_are_declared_and_typed() -> None:
    documents = _load(TAX)
    policy = next(d for d in documents if d.get("kind") == "Policy")
    policy["dimensions"] = {"undeclared": "CN"}
    rejected(documents, "UNDECLARED_DIMENSION")
    policy["dimensions"] = {"taxYear": "not-an-integer"}
    rejected(documents, "TYPE_MISMATCH")


def test_cross_pack_reference_requires_exact_declared_dependency() -> None:
    documents = _load(TAX, PROCUREMENT)
    rule = next(d for d in documents if d.get("id") == "tax.roundedTaxableIncome")
    rule["inputs"][0]["metric"] = "procurement.orderAmount"
    rejected(documents, "UNDECLARED_CROSS_PACK_REF")
    pack = next(d for d in documents if d.get("kind") == "DomainPack" and d["id"] == "tax")
    pack["dependencies"] = [{"id": "procurement", "version": "99.0.0"}]
    rejected(documents, "DEPENDENCY_VERSION_MISMATCH")
    pack["dependencies"][0]["version"] = "1.0.0"
    result = compile_documents(documents)
    assert result.ok, result.diagnostics


def test_missing_and_empty_pack_paths_fail(tmp_path: Path) -> None:
    for path in (tmp_path / "missing", tmp_path):
        result = compile_paths([path])
        assert not result.ok
        assert result.bundle is None


@pytest.mark.parametrize("output_unit", ["USD", "EA", "1"])
def test_derived_metric_cannot_relabel_currency(output_unit: str) -> None:
    documents = _load(TAX)
    metric = next(d for d in documents if d.get("id") == "tax.adjustmentAmount")
    metric["unit"] = output_unit
    rejected(documents, "UNIT_MISMATCH")


def test_dimensionless_ratio_and_contextual_threshold_still_compile() -> None:
    result = compile_paths([TAX, PROCUREMENT])
    assert result.ok, result.diagnostics
    assert result.bundle is not None
    ratio = next(m for m in result.bundle.metrics if m.id == "procurement.contractUtilization")
    assert ratio.unit == "1"

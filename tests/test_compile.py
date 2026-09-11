from __future__ import annotations

from pathlib import Path
from typing import Any

from semaloom.checks.import_direction import check_import_direction
from semaloom.compiler import compile_documents, compile_paths, document_schemas
from semaloom.compiler.yaml_load import load_yaml_documents

REPO = Path(__file__).resolve().parents[1]
TAX = REPO / "examples" / "tax"
PROCUREMENT = REPO / "examples" / "procurement"


def _load(*roots: Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for root in roots:
        for _path, data in load_yaml_documents(root):
            documents.append(data)
    return documents


def _reorder(value: Any) -> Any:
    if isinstance(value, dict):
        items = list(value.items())
        items.reverse()
        return {key: _reorder(item) for key, item in items}
    if isinstance(value, list):
        return [_reorder(item) for item in value]
    return value


def test_real_packs_compile_with_stable_digest() -> None:
    first = compile_paths([TAX, PROCUREMENT])
    second = compile_paths([PROCUREMENT, TAX])
    assert first.ok, [item.model_dump() for item in first.diagnostics]
    assert first.bundle is not None
    assert first.online_validation == "NOT_RUN"
    assert second.bundle is not None
    assert len(first.bundle.digest) == 64
    assert first.bundle.digest == second.bundle.digest


def test_field_reorder_does_not_change_digest() -> None:
    original = _load(TAX, PROCUREMENT)
    reordered = [_reorder(doc) for doc in original]
    first = compile_documents(original)
    second = compile_documents(reordered)
    assert first.ok and second.ok
    assert first.bundle is not None and second.bundle is not None
    assert first.bundle.digest == second.bundle.digest


def test_catalog_snapshot_does_not_forge_online_pass() -> None:
    result = compile_paths([TAX], catalog_snapshot={"tables": ["tax_metric"]})
    assert result.ok
    assert result.online_validation == "NOT_RUN"
    assert any(item.code == "ONLINE_VALIDATION_NOT_RUN" for item in result.diagnostics)


def test_approval_in_dsl_is_rejected() -> None:
    docs = _load(TAX)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Metric",
            "id": "tax.forged",
            "version": "1.0.0",
            "objectType": "tax.Taxpayer",
            "valueType": "DECIMAL",
            "unit": "CNY",
            "grain": ["taxpayerId"],
            "approvedBy": "self",
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "APPROVAL_IN_DSL" for item in result.diagnostics)


def test_duplicate_id_is_rejected() -> None:
    docs = _load(TAX)
    clone = next(doc for doc in docs if doc.get("kind") == "Metric")
    docs.append(dict(clone))
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "DUPLICATE_ID" for item in result.diagnostics)


def test_dangling_ref_is_rejected() -> None:
    docs = _load(TAX)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Metric",
            "id": "tax.missingObject",
            "version": "1.0.0",
            "objectType": "tax.Unknown",
            "valueType": "DECIMAL",
            "unit": "CNY",
            "grain": ["taxpayerId"],
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "DANGLING_REF" for item in result.diagnostics)


def test_unknown_core_field_is_rejected() -> None:
    docs = _load(PROCUREMENT)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "ObjectType",
            "id": "procurement.Ghost",
            "version": "1.0.0",
            "identityKeys": ["ghostId"],
            "properties": [{"id": "ghostId", "valueType": "STRING"}],
            "tableName": "do_not_accept",
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "UNKNOWN_CORE_FIELD" for item in result.diagnostics)


def test_rule_cycle_is_rejected() -> None:
    docs = _load(PROCUREMENT)
    docs.extend(
        [
            {
                "apiVersion": "semaloom/v0.1",
                "kind": "Metric",
                "id": "procurement.cycleA",
                "version": "1.0.0",
                "objectType": "procurement.Order",
                "valueType": "DECIMAL",
                "unit": "CNY",
                "grain": ["orderId"],
                "derivedFrom": ["procurement.cycleB"],
            },
            {
                "apiVersion": "semaloom/v0.1",
                "kind": "Metric",
                "id": "procurement.cycleB",
                "version": "1.0.0",
                "objectType": "procurement.Order",
                "valueType": "DECIMAL",
                "unit": "CNY",
                "grain": ["orderId"],
                "derivedFrom": ["procurement.cycleA"],
            },
        ]
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "RULE_CYCLE" for item in result.diagnostics)


def test_object_link_cycle_is_allowed() -> None:
    docs = _load(PROCUREMENT)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Link",
            "id": "procurement.supplierOrders",
            "version": "1.0.0",
            "source": "procurement.Supplier",
            "target": "procurement.Order",
            "cardinality": "MANY",
            "identity": {"source": "supplierId", "target": "supplierId"},
        }
    )
    result = compile_documents(docs)
    assert result.ok, [item.model_dump() for item in result.diagnostics]


def test_missing_link_identity_is_rejected() -> None:
    docs = _load(PROCUREMENT)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Link",
            "id": "procurement.brokenLink",
            "version": "1.0.0",
            "source": "procurement.Order",
            "target": "procurement.Supplier",
            "cardinality": "ONE",
            "identity": {"source": "missing", "target": "supplierId"},
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "MISSING_LINK_IDENTITY" for item in result.diagnostics)


def test_missing_unit_is_rejected() -> None:
    docs = _load(TAX)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Metric",
            "id": "tax.noUnit",
            "version": "1.0.0",
            "objectType": "tax.Taxpayer",
            "valueType": "DECIMAL",
            "unit": "",
            "grain": ["taxpayerId"],
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "MISSING_UNIT" for item in result.diagnostics)


def test_omitted_unit_is_rejected() -> None:
    docs = _load(TAX)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Metric",
            "id": "tax.omittedUnit",
            "version": "1.0.0",
            "objectType": "tax.Taxpayer",
            "valueType": "DECIMAL",
            "grain": ["taxpayerId"],
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code in {"MISSING_UNIT", "INVALID_DEFINITION"} for item in result.diagnostics)


def test_invalid_value_type_is_rejected() -> None:
    docs = _load(TAX)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Metric",
            "id": "tax.badType",
            "version": "1.0.0",
            "objectType": "tax.Taxpayer",
            "valueType": "FLOAT",
            "unit": "CNY",
            "grain": ["taxpayerId"],
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "INVALID_DEFINITION" for item in result.diagnostics)


def test_undeclared_context_dimension_is_rejected() -> None:
    docs = _load(TAX)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Metric",
            "id": "tax.unknownDim",
            "version": "1.0.0",
            "objectType": "tax.Taxpayer",
            "valueType": "DECIMAL",
            "unit": "CNY",
            "grain": ["taxpayerId", "notADimension"],
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "INVALID_DIMENSION_TYPE" for item in result.diagnostics)


def test_incomplete_grain_is_rejected() -> None:
    docs = _load(TAX)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Metric",
            "id": "tax.noGrain",
            "version": "1.0.0",
            "objectType": "tax.Taxpayer",
            "valueType": "DECIMAL",
            "unit": "CNY",
            "grain": [],
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "INCOMPLETE_GRAIN" for item in result.diagnostics)


def test_ambiguous_mapping_is_rejected() -> None:
    docs = _load(TAX)
    existing = next(doc for doc in docs if doc.get("id") == "tax.reportedIncome.pg")
    clone = dict(existing)
    clone["id"] = "tax.reportedIncome.pgAlt"
    docs.append(clone)
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "AMBIGUOUS_MAPPING" for item in result.diagnostics)


def test_policy_overlap_is_rejected() -> None:
    docs = _load(TAX)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Policy",
            "id": "tax.incomeReconcilesOverlap",
            "version": "1.0.0",
            "rule": "tax.incomeReconciles",
            "dimensions": {"jurisdiction": "CN"},
            "interval": {"effectiveFrom": "2024-06-01", "effectiveTo": "2025-06-01"},
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "POLICY_OVERLAP" for item in result.diagnostics)


def test_undeclared_namespace_is_rejected() -> None:
    docs = _load(TAX)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "ObjectType",
            "id": "hr.Person",
            "version": "1.0.0",
            "identityKeys": ["personId"],
            "properties": [{"id": "personId", "valueType": "STRING"}],
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "UNDECLARED_CROSS_PACK_REF" for item in result.diagnostics)


def test_schema_export_covers_core_kinds() -> None:
    schemas = document_schemas()
    assert "ObjectTypeDef" in schemas
    assert "RuleDef" in schemas
    assert schemas["MetricDef"]["additionalProperties"] is False


def test_import_direction_still_holds() -> None:
    assert check_import_direction() == []

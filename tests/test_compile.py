from __future__ import annotations

from pathlib import Path
from typing import Any

from semaloom.checks.import_direction import check_import_direction
from semaloom.compiler.yaml_load import load_yaml_documents
from semaloom.sdk import compile_documents, compile_paths, document_schemas

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
    assert {item.id for item in first.bundle.integration_bindings} == {
        "procurement.draft-api",
        "procurement.postgres",
        "procurement.suppliers",
        "tax.draft-api",
        "tax.postgres",
    }


def test_procurement_contract_demo_is_entirely_declarative() -> None:
    result = compile_paths([PROCUREMENT])
    assert result.ok and result.bundle is not None
    bundle = result.bundle
    assert any(item.id == "procurement.Contract" for item in bundle.object_types)
    assert {
        "procurement.contractValue",
        "procurement.committedSpend",
        "procurement.remainingCommitment",
        "procurement.contractUtilization",
    } <= {item.id for item in bundle.metrics}
    assert {"procurement.contractSupplier", "procurement.contractOrganization"} <= {
        item.id for item in bundle.links
    }
    utilization = next(
        item for item in bundle.metrics if item.id == "procurement.contractUtilization"
    )
    assert utilization.additivity == "NONE"


def test_integration_binding_ownership_is_validated() -> None:
    original = _load(TAX)
    changed = _load(TAX)
    integration = next(item for item in changed if item.get("id") == "tax.postgres")
    integration["sourceId"] = "alternate_tax_source"

    invalid = compile_documents(changed)
    valid = compile_documents(original)

    assert not invalid.ok
    assert any(item.code == "INVALID_DEFINITION" for item in invalid.diagnostics)
    assert valid.ok and valid.bundle is not None


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
    supplier = next(
        item
        for item in docs
        if item.get("kind") == "ObjectType" and item.get("id") == "procurement.Supplier"
    )
    supplier["properties"] = [
        *supplier["properties"],
        {"id": "orderId", "valueType": "STRING"},
    ]
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Link",
            "id": "procurement.supplierOrders",
            "version": "1.0.0",
            "source": "procurement.Supplier",
            "target": "procurement.Order",
            "cardinality": "MANY",
            "identity": [{"source": "orderId", "target": "orderId"}],
        }
    )
    result = compile_documents(docs)
    assert result.ok, [item.model_dump() for item in result.diagnostics]


def test_collection_many_link_is_rejected_at_compile() -> None:
    docs = _load(PROCUREMENT)
    supplier = next(
        item
        for item in docs
        if item.get("kind") == "ObjectType" and item.get("id") == "procurement.Supplier"
    )
    supplier["properties"] = [*supplier["properties"], {"id": "orderId", "valueType": "STRING"}]
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Link",
            "id": "procurement.supplierOrders",
            "version": "1.0.0",
            "source": "procurement.Supplier",
            "target": "procurement.Order",
            "cardinality": "MANY",
            "collection": True,
            "identity": [{"source": "orderId", "target": "orderId"}],
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    diagnostic = next(
        item for item in result.diagnostics if item.path == "procurement.supplierOrders"
    )
    assert "procurement.supplierOrders" in diagnostic.message
    assert "missing fanout policy" in diagnostic.message


def test_collection_composite_identity_is_rejected_at_compile() -> None:
    docs = _load(PROCUREMENT)
    docs.append(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Link",
            "id": "procurement.compositeSupplier",
            "version": "1.0.0",
            "source": "procurement.Order",
            "target": "procurement.Supplier",
            "cardinality": "ONE",
            "collection": True,
            "identity": [
                {"source": "supplierId", "target": "supplierId"},
                {"source": "supplierId", "target": "supplierId"},
            ],
        }
    )
    result = compile_documents(docs)
    assert not result.ok
    diagnostic = next(
        item for item in result.diagnostics if "procurement.compositeSupplier" in item.message
    )
    assert "unsupported identity" in diagnostic.message


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
            "identity": [{"source": "missing", "target": "supplierId"}],
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
    existing = next(doc for doc in docs if doc.get("id") == "tax.Taxpayer.facts.pg")
    clone = dict(existing)
    clone["id"] = "tax.Taxpayer.facts.pgAlt"
    docs.append(clone)
    result = compile_documents(docs)
    assert not result.ok
    assert any(item.code == "AMBIGUOUS_MAPPING" for item in result.diagnostics)


def test_compact_metric_inherits_mapping_and_unit() -> None:
    result = compile_paths([TAX, PROCUREMENT])
    assert result.ok, [item.model_dump() for item in result.diagnostics]
    assert result.bundle is not None
    reported = next(item for item in result.bundle.metrics if item.id == "tax.reportedIncome")
    assert reported.property == "amount"
    assert reported.unit == "CNY"
    assert reported.value_type == "DECIMAL"
    assert reported.grain == ("taxpayerId", "taxYear")
    mapping = next(item for item in result.bundle.mappings if item.id == "tax.reportedIncome.pg")
    assert mapping.target == "tax.reportedIncome"
    assert mapping.physical["valueColumn"] == "amount"
    assert mapping.physical["filters"]["metric"] == "reportedIncome"
    amount = next(item for item in result.bundle.metrics if item.id == "procurement.orderAmount")
    assert amount.property == "amount"
    assert amount.grain == ("orderId",)
    assert any(item.id == "procurement.orderAmount.orders" for item in result.bundle.mappings)
    assert "procurement.Order.amount" not in {item.id for item in result.bundle.metrics}


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


def test_metric_selector_cannot_silently_override_a_source_filter() -> None:
    docs = _load(REPO / "examples/warehouse")
    metric = next(doc for doc in docs if doc["kind"] == "Metric")
    metric["select"] = {"category": "requested"}
    mapping = next(doc for doc in docs if doc["kind"] == "Mapping")
    mapping["physical"]["filters"] = {"category": "approved"}
    result = compile_documents(docs)
    assert not result.ok
    assert any(
        item.code == "INVALID_MAPPING" and "conflicts" in item.message
        for item in result.diagnostics
    )


def test_api_metric_selector_requires_a_bound_parameter() -> None:
    docs = _load(REPO / "examples/warehouse")
    for doc in docs:
        if doc["kind"] in {"Mapping", "IntegrationBinding"}:
            doc["provider"] = "openapi"
        if doc["kind"] == "Mapping":
            doc["physical"] = {
                "path": "/stock",
                "method": "GET",
                "grainPointers": {"skuId": "/id"},
                "propertyPointers": {
                    "category": "/category",
                    "onHandQty": "/quantity",
                    "stockYear": "/year",
                },
                "parameterBindings": {"skuId": "id"},
            }
        if doc["kind"] == "Metric":
            doc["select"] = {"category": "requested"}
    result = compile_documents(docs)
    assert not result.ok
    assert any(
        item.code == "INVALID_MAPPING" and "parameter" in item.message
        for item in result.diagnostics
    )


def test_postgres_mapping_rejects_sql_fragments_and_non_string_bindings() -> None:
    docs = _load(TAX)
    mapping = next(doc for doc in docs if doc.get("id") == "tax.Taxpayer.facts.pg")
    mapping["physical"]["propertyColumns"]["amount"] = "SUM(amount)"
    result = compile_documents(docs)
    assert not result.ok
    assert any(
        item.code == "INVALID_MAPPING" and "illegal identifier" in item.message
        for item in result.diagnostics
    )

    mapping["physical"]["propertyColumns"]["amount"] = {"sql": "amount"}
    result = compile_documents(docs)
    assert not result.ok
    assert any(
        item.code == "INVALID_MAPPING" and "must be a non-empty string" in item.message
        for item in result.diagnostics
    )

"""Ontology dictionaries, period-over-period, and claim cards at the chat boundary."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from semaloom.app.chat.choices import prepare_turn, try_direct_turn
from semaloom.app.chat.intent import TurnIntent
from semaloom.app.chat.tools import SemanticTools
from semaloom.core.semantic_query import (
    ComparisonExpr,
    FilterAtom,
    GroupByItem,
    MetricRef,
    SemanticQuery,
    TypedValue,
)
from semaloom.runtime.analysis import execute, prepare
from semaloom.sdk import compile_paths
from tests.test_bind_join_collection import procurement_query  # noqa: F401
from tests.test_business_analysis import ACTOR, ROOT, financial_query  # noqa: F401
from tests.test_q4_semantic_audit import warehouse  # noqa: F401


def test_packs_compile_dictionary_values() -> None:
    procurement = compile_paths([ROOT / "examples/procurement"]).bundle
    assert procurement is not None
    supplier = next(item for item in procurement.object_types if item.id == "procurement.Supplier")
    region = next(prop for prop in supplier.properties if prop.id == "region")
    assert {item.id for item in region.values} == {"EAST", "NORTH", "WEST"}
    warehouse_bundle = compile_paths([ROOT / "examples/warehouse"]).bundle
    assert warehouse_bundle is not None
    sku = next(item for item in warehouse_bundle.object_types if item.id == "warehouse.Sku")
    category = next(prop for prop in sku.properties if prop.id == "category")
    assert {item.id for item in category.values} == {"A", "B"}


def test_region_alias_becomes_a_typed_filter(procurement_query: Any) -> None:  # noqa: F811
    intent = TurnIntent.read("华东区采购额合计", procurement_query.bundle)
    assert intent.metric_ids == frozenset({"procurement.orderAmount"})
    assert intent.operation == "sum"
    assert len(intent.dimension_filters) == 1
    assert intent.dimension_filters[0].stored == "EAST"
    result = prepare_turn(procurement_query, ACTOR, "华东区采购额合计")
    assert result.get("status") == "READY"
    assert result["result"]["values"][0]["value"] == "150.0100"


def test_region_without_value_asks_dictionary_cards(procurement_query: Any) -> None:  # noqa: F811
    result = prepare_turn(procurement_query, ACTOR, "区域订单金额合计")
    assert result["status"] == "NEEDS_INPUT"
    assert result["question"]["slot"] == "dimension"
    assert result["question"]["control"] == "SELECT"
    labels = {item["label"] for item in result["question"]["options"]}
    assert "华东区" in labels and "华北区" in labels


def test_group_by_region_from_ontology(procurement_query: Any) -> None:  # noqa: F811
    result = prepare_turn(procurement_query, ACTOR, "按区域合计订单金额")
    assert result.get("status") == "READY"
    grains = {row["grain"].get("region") for row in result["result"]["values"]}
    assert "EAST" in grains and "WEST" in grains and "NORTH" in grains
    labels = {
        row["grain"]["region"]: row["labels"]["region"]
        for row in result["result"]["values"]
        if row["grain"]["region"] is not None
    }
    assert labels == {"EAST": "华东区", "NORTH": "华北区", "WEST": "西部"}


def test_north_region_alias_filters(procurement_query: Any) -> None:  # noqa: F811
    result = prepare_turn(procurement_query, ACTOR, "华北区采购额合计")
    assert result.get("status") == "READY"
    assert result["result"]["values"][0]["value"] == "10.0000"


def test_status_dictionary_filters_open_orders(procurement_query: Any) -> None:  # noqa: F811
    result = prepare_turn(procurement_query, ACTOR, "未关闭订单金额合计")
    assert result.get("status") == "READY"
    assert result["result"]["values"][0]["value"] == "175.0100"


def test_link_id_cannot_be_used_as_model_group_field(procurement_query: Any) -> None:  # noqa: F811
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="procurement.orderAmount", aggregation="SUM"),),
        group_by=(GroupByItem(id="procurement.orderSupplier"),),
    )
    gateway = SemanticTools(
        procurement_query,
        ACTOR,
        user_message="按供应商名称汇总采购金额，从高到低排名",  # noqa: RUF001
    )
    with pytest.raises(ValueError, match="GROUP_BY_REQUIRES_PROPERTY_NOT_LINK_ID"):
        gateway.call("prepare_semantic_query", {"query": query.model_dump(mode="json")})
    result = prepare_turn(
        procurement_query,
        ACTOR,
        "按供应商名称汇总采购金额，从高到低排名",  # noqa: RUF001
        query,
    )
    assert result["status"] == "UNSUPPORTED"
    assert result["errorCode"] == "INVALID_PROPERTIES"


def test_category_dictionary_filters_warehouse(warehouse: Any) -> None:  # noqa: F811
    service, _engine = warehouse
    intent = TurnIntent.read("2024年类别A库存合计", service.bundle)
    assert intent.metric_ids == frozenset({"warehouse.onHandQty"})
    assert intent.dimension_filters[0].stored == "A"
    result = prepare_turn(service, ACTOR, "2024年类别A库存合计")
    assert result.get("status") == "READY"
    assert Decimal(result["result"]["values"][0]["value"]) > 0
    assert result["result"]["scope"]["observedCount"] == 1000


def test_claim_wording_uses_engine_path_and_subject_cards(
    financial_query: Any,  # noqa: F811
) -> None:
    intent = TurnIntent.read("示例企业 在2024年资产等于负债加权益吗", financial_query.bundle)
    assert intent.claim_ids == frozenset({"finance.review.balanceBalances"})
    result = try_direct_turn(financial_query, ACTOR, "示例企业 在2024年资产等于负债加权益吗")
    assert result is not None
    assert result.get("waiting") is True
    assert result["question"]["slot"] == "claimSubject"
    assert result["question"]["control"] == "SELECT"


def test_unique_claim_subject_evaluates(financial_query: Any) -> None:  # noqa: F811
    result = try_direct_turn(financial_query, ACTOR, "缺失样本 在2024年资产等于负债加权益吗")
    assert result is not None
    assert result.get("answerReady") is True
    assert result["tool"] == "evaluate_claim"
    assert result["result"]["claim"]["truth"] in {"TRUE", "FALSE", "UNKNOWN"}


def test_claim_language_without_named_rule_offers_cards(
    financial_query: Any,  # noqa: F811
) -> None:
    result = try_direct_turn(financial_query, ACTOR, "核验是否成立")
    assert result is not None
    assert result["status"] == "NEEDS_INPUT"
    assert result["question"]["slot"] == "claim"
    labels = {item["label"] for item in result["question"]["options"]}
    assert any("资产" in label for label in labels)


def test_period_over_period_compares_two_years(financial_query: Any) -> None:  # noqa: F811
    engine = financial_query.provider._engines["sample_pg"]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE sample_financial_review SET company_id = COALESCE(company_id, id)")
        )
        conn.execute(
            text(
                """
                INSERT INTO sample_financial_review(
                  tenant_id, id, company_id, company_name, tax_year, period_start, period_to,
                  unique_pair, declared_profit, audit_profit, net_profit, tax_expense,
                  assets, liabilities, equity
                )
                VALUES (
                  'tenant-a','C1-25','C1','示例企业',2025,'2025-01-01','2026-01-01',
                  true,400.02,400,320,80,2000,1200,800
                )
                """
            )
        )
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="finance.review.declared_profit", aggregation="SUM"),),
        filters=FilterAtom(
            field="taxYear", op="EQ", value=TypedValue(value_type="INTEGER", value=2025)
        ),
        comparison=ComparisonExpr(op="PERIOD_OVER_PERIOD", metric="finance.review.declared_profit"),
        missing_policy="exclude",
    )
    prepared = prepare(financial_query, query, ACTOR)
    assert prepared.status == "READY" and prepared.plan is not None
    result = execute(financial_query, prepared.plan, ACTOR)
    comparison = result.scope.get("comparison") or {}
    assert comparison.get("operation") == "periodOverPeriod"
    assert comparison.get("currentYear") == 2025
    assert comparison.get("priorYear") == 2024
    assert Decimal(comparison["value"]) > 0
    chat = prepare_turn(financial_query, ACTOR, "2025年选定申报利润总额合计环比")
    assert chat.get("status") == "READY"
    assert "较上年同期" in chat["text"]


def test_month_over_month_is_unsupported(financial_query: Any) -> None:  # noqa: F811
    result = prepare_turn(financial_query, ACTOR, "选定申报利润总额月环比")
    assert result["status"] == "UNSUPPORTED"
    assert result["errorCode"] == "TIME_GRAIN_UNSUPPORTED"

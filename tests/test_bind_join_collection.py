"""Cross-source ONE Link collection bind-join on the shipped prepare/execute path."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from semaloom.adapters.postgres import PostgresReadProvider
from semaloom.app.chat.choices import prepare_turn
from semaloom.core.semantic_query import (
    FilterAtom,
    MetricRef,
    SemanticQuery,
    TypedValue,
)
from semaloom.runtime.analysis import execute, prepare
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.discovery import SemanticDiscovery
from semaloom.runtime.fixtures import engines
from semaloom.runtime.query import QueryService
from semaloom.sdk import compile_paths
from tests.test_business_analysis import ACTOR

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples/procurement"


def _query(**changes: Any) -> SemanticQuery:
    payload: dict[str, Any] = {
        "apiVersion": "semaloom/v0.1",
        "metrics": [{"id": "procurement.orderAmount", "aggregation": "SUM"}],
        "groupBy": [{"id": "procurement.Supplier.name"}],
        "missingPolicy": "reject",
        "evidenceLimit": 50,
    }
    payload.update(changes)
    return SemanticQuery.model_validate(payload)


@pytest.fixture
def procurement_query() -> Any:
    bundle = compile_paths([PACK]).bundle
    assert bundle is not None
    orders = engines()["orders_pg"]
    suppliers = engines()["suppliers_pg"]
    with orders.connect() as order_conn, suppliers.connect() as supplier_conn:
        order_conn.execute(text("CREATE SCHEMA bind_join_orders"))
        order_conn.execute(text("SET search_path TO bind_join_orders"))
        supplier_conn.execute(text("CREATE SCHEMA bind_join_suppliers"))
        supplier_conn.execute(text("SET search_path TO bind_join_suppliers"))
        order_conn.execute(
            text(
                """
                CREATE TABLE proc_order (
                  tenant_id TEXT, order_id TEXT, organization_id TEXT, supplier_id TEXT,
                  status TEXT, amount NUMERIC, quantity NUMERIC
                )
                """
            )
        )
        order_conn.execute(
            text(
                """
                CREATE TABLE proc_organization (
                  tenant_id TEXT, organization_id TEXT, name TEXT, approval_limit NUMERIC
                )
                """
            )
        )
        order_conn.execute(
            text(
                """
                INSERT INTO proc_organization VALUES
                ('tenant-a','O1','Org A',5000),
                ('tenant-a','O2','Org B',8000)
                """
            )
        )
        order_conn.execute(
            text(
                """
                INSERT INTO proc_order VALUES
                ('tenant-a','PO1','O1','S1','OPEN',100.0100,1),
                ('tenant-a','PO2','O1','S1','OPEN',50.0000,1),
                ('tenant-a','PO3','O2','S2','OPEN',25.0000,1),
                ('tenant-a','PO4','O2','S3','CLOSED',10.0000,1),
                ('tenant-a','PO5','O2','S4','CLOSED',7.0000,1),
                ('tenant-b','POX','OX','SX','OPEN',9999,1)
                """
            )
        )
        supplier_conn.execute(
            text(
                """
                CREATE TABLE proc_supplier (
                  tenant_id TEXT, supplier_id TEXT, name TEXT, region TEXT
                )
                """
            )
        )
        supplier_conn.execute(
            text(
                """
                INSERT INTO proc_supplier VALUES
                ('tenant-a','S1','Supplier One','EAST'),
                ('tenant-a','S2','Supplier Two','WEST'),
                ('tenant-a','S3','Supplier Three','NORTH')
                """
            )
        )
        order_conn.commit()
        supplier_conn.commit()
        order_engine = create_engine(
            orders.url, connect_args={"options": "-csearch_path=bind_join_orders"}
        )
        supplier_engine = create_engine(
            suppliers.url, connect_args={"options": "-csearch_path=bind_join_suppliers"}
        )
        provider = PostgresReadProvider(
            {"orders_pg": order_engine, "suppliers_pg": supplier_engine}
        )
        try:
            yield QueryService(bundle, provider)
        finally:
            order_engine.dispose()
            supplier_engine.dispose()
            order_conn.rollback()
            supplier_conn.rollback()
            order_conn.execute(text("SET search_path TO public"))
            supplier_conn.execute(text("SET search_path TO public"))
            order_conn.execute(text("DROP SCHEMA bind_join_orders CASCADE"))
            supplier_conn.execute(text("DROP SCHEMA bind_join_suppliers CASCADE"))
            order_conn.commit()
            supplier_conn.commit()


def test_bind_join_groups_by_supplier_name(procurement_query: Any) -> None:
    prepared = prepare(procurement_query, _query(), ACTOR)
    assert prepared.status == "READY" and prepared.plan is not None
    result = execute(procurement_query, prepared.plan, ACTOR)
    got = {row["grain"].get("name"): Decimal(row["value"]) for row in result.values}
    assert got["Supplier One"] == Decimal("150.0100")
    assert got["Supplier Two"] == Decimal("25.0000")
    assert got["Supplier Three"] == Decimal("10.0000")
    assert got[None] == Decimal("7.0000")
    with procurement_query.provider._engines["orders_pg"].connect() as conn:
        expected = conn.execute(
            text(
                "SELECT SUM(amount) FROM proc_order WHERE tenant_id='tenant-a' AND supplier_id='S1'"
            )
        ).scalar_one()
    assert got["Supplier One"] == Decimal(expected)


def test_bind_join_filters_by_supplier_name(procurement_query: Any) -> None:
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="procurement.orderAmount", aggregation="SUM"),),
        filters=FilterAtom(
            field="procurement.Supplier.name",
            op="EQ",
            value=TypedValue(value_type="STRING", value="Supplier One"),
        ),
    )
    prepared = prepare(procurement_query, query, ACTOR)
    assert prepared.status == "READY" and prepared.plan is not None
    result = execute(procurement_query, prepared.plan, ACTOR)
    assert Decimal(result.values[0]["value"]) == Decimal("150.0100")


def test_unknown_supplier_name_is_empty(procurement_query: Any) -> None:
    query = SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id="procurement.orderAmount", aggregation="SUM"),),
        filters=FilterAtom(
            field="procurement.Supplier.name",
            op="EQ",
            value=TypedValue(value_type="STRING", value="No Such Supplier"),
        ),
    )
    prepared = prepare(procurement_query, query, ACTOR)
    assert prepared.status == "READY" and prepared.plan is not None
    result = execute(procurement_query, prepared.plan, ACTOR)
    assert result.values == ()
    assert result.scope.get("reason") == "EMPTY_POPULATION"


def test_same_source_organization_join_still_sql(procurement_query: Any) -> None:
    query = _query(groupBy=[{"id": "procurement.Organization.name"}])
    prepared = prepare(procurement_query, query, ACTOR)
    assert prepared.status == "READY" and prepared.plan is not None
    result = execute(procurement_query, prepared.plan, ACTOR)
    names = {row["grain"].get("name") for row in result.values}
    assert "Org A" in names and "Org B" in names


def test_discovery_marks_cross_source_one_link(procurement_query: Any) -> None:
    service = SemanticDiscovery(procurement_query.bundle)
    actor = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))
    link = service.describe("procurement.orderSupplier", actor)
    assert link["analysisCapabilities"]["collectionJoin"] is True
    metric = service.describe("procurement.orderAmount", actor)
    assert metric["analysisCapabilities"]["collectionJoin"] is True


def test_chat_groups_by_supplier_name(procurement_query: Any) -> None:
    result = prepare_turn(procurement_query, ACTOR, "按供应商名称合计订单金额")
    assert result.get("status") == "READY"
    grains = {row["grain"].get("name") for row in result["result"]["values"]}
    assert "Supplier One" in grains and "Supplier Two" in grains

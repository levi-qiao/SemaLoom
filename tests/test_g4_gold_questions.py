"""Independent G4 gold-question acceptance. Isolated semaloom_g4_* databases only."""

from __future__ import annotations

import json
import os
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from semaloom.app.bootstrap import build_services, compile_examples
from semaloom.app.factory import create_app
from semaloom.app.http import router
from semaloom.compiler import compile_documents
from semaloom.core.results import MetricSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.fixtures import configured_urls, engines
from semaloom.runtime.query import QueryService
from semaloom.runtime.studio_control import documents_from_bundle
from tests.g4_gold_cases import (
    ANALYST,
    APPROVER,
    GOLD_BY_ID,
    GOLD_QUESTIONS,
    MODELER,
    OTHER_TENANT,
    request_keys,
    typed_request_for,
)

REPO = Path(__file__).resolve().parents[1]
CORE = REPO / "src" / "semaloom"
G4_DATABASES = {
    "SEMALOOM_TAX_DATABASE_URL": "semaloom_g4_tax",
    "SEMALOOM_ORDERS_DATABASE_URL": "semaloom_g4_orders",
    "SEMALOOM_SUPPLIERS_DATABASE_URL": "semaloom_g4_suppliers",
    "SEMALOOM_META_DATABASE_URL": "semaloom_g4_meta",
}
FORBIDDEN_REQUEST_FIELDS = frozenset({"sql", "url", "permissions", "table", "column", "join"})
PHYSICAL_LEAKS = (
    "select ",
    "drop table",
    "tax_metric",
    "tax_taxpayer",
    "proc_order",
    "postgresql",
)


def _enforce_g4_databases() -> None:
    for key, database in G4_DATABASES.items():
        current = os.environ.get(key, "")
        if current and database not in current:
            pytest.fail(
                f"G4 tests refuse non-isolated database {key}={current}; "
                f"expected host-local {database}"
            )
        if not current:
            os.environ[key] = f"postgresql+psycopg://semaloom:semaloom@127.0.0.1:5432/{database}"
    os.environ.setdefault("SEMALOOM_PROFILE", "local-dev")
    urls = configured_urls()
    expected = {
        "tax_pg": "semaloom_g4_tax",
        "orders_pg": "semaloom_g4_orders",
        "suppliers_pg": "semaloom_g4_suppliers",
        "meta": "semaloom_g4_meta",
    }
    for source, database in expected.items():
        if database not in urls[source]:
            pytest.fail(f"G4 configured_urls[{source}]={urls[source]} is not isolated")


_enforce_g4_databases()


@pytest.fixture(scope="module")
def client() -> Any:
    app = create_app(load_services=True, load_fixtures=True)
    with TestClient(app) as test_client:
        yield test_client


def _headers(authorization: str) -> dict[str, str]:
    return {"Authorization": authorization}


def _post(client: TestClient, case_id: str) -> Any:
    request = GOLD_BY_ID[case_id].typed_request
    assert request["interface"].startswith("POST ")
    path = request["interface"].split(" ", 1)[1]
    return client.post(path, json=request["body"], headers=request["headers"])


def _observation(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload["observations"][0])


def _dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False).lower()


def _assert_no_physical_sql(payload: object) -> None:
    text_payload = _dump(payload)
    for leak in PHYSICAL_LEAKS:
        assert leak not in text_payload, f"agent payload leaked {leak!r}"


def _ensure_over_limit_order() -> None:
    engine = engines()["orders_pg"]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO proc_order(
                    tenant_id, order_id, organization_id, supplier_id,
                    amount, quantity, status
                )
                VALUES ('tenant-a', 'PO-OVER', 'ORG-A', 'SUP-1', 9000.00, 1, 'OPEN')
                ON CONFLICT (tenant_id, order_id) DO UPDATE
                SET amount = 9000.00, organization_id = 'ORG-A'
                """
            )
        )


class _OrderRiskHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/order-risk":
            self.send_response(404)
            self.end_headers()
            return
        query = parse_qs(parsed.query)
        order_id = (query.get("orderId") or [""])[0]
        tenant = (query.get("tenant") or [""])[0]
        if tenant == "tenant-a" and order_id == "PO-001":
            body = b'{"orderId":"PO-001","deliveryRisk":"LOW"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.mark.parametrize("case", GOLD_QUESTIONS, ids=lambda item: item.id)
def test_nl_intent_maps_to_typed_request(case: Any) -> None:
    mapped = typed_request_for(case.nl_intent)
    assert mapped == case.typed_request
    body = mapped.get("body") or {}
    if mapped["interface"] in {"GET /v0.1/describe", "GET /v0.1/mcp/tools"}:
        return
    if case.id in {"GQ21_REJECT_SQL", "GQ22_REJECT_URL_PERMISSIONS"}:
        assert request_keys(body) & FORBIDDEN_REQUEST_FIELDS
        return
    assert not (request_keys(body) & FORBIDDEN_REQUEST_FIELDS)


def test_unknown_intent_is_not_guessed() -> None:
    with pytest.raises(KeyError, match="no deterministic mapping"):
        typed_request_for("随便猜一个收入数字")


def test_query_tax_and_procurement_metrics(client: TestClient) -> None:
    tax = _post(client, "GQ03_QUERY_TAX_REPORTED_INCOME")
    proc = _post(client, "GQ04_QUERY_PROC_ORDER_AMOUNT")
    assert tax.status_code == 200
    assert proc.status_code == 200
    tax_obs = _observation(tax.json())
    proc_obs = _observation(proc.json())
    assert tax_obs["kind"] == "PRESENT"
    assert proc_obs["kind"] == "PRESENT"
    assert Decimal(tax_obs["value"]) == Decimal("110.1000")
    assert Decimal(proc_obs["value"]) == Decimal("1200.0000")
    assert tax.json()["releaseDigest"] == proc.json()["releaseDigest"]
    _assert_no_physical_sql(tax.json())
    _assert_no_physical_sql(proc.json())


def test_query_procurement_object_status(client: TestClient) -> None:
    response = _post(client, "GQ05_QUERY_PROC_ORDER_OBJECT")
    assert response.status_code == 200
    payload = response.json()
    obs = _observation(payload)
    assert obs["kind"] == "PRESENT"
    assert json.loads(obs["value"] or "{}")["status"] == "OPEN"
    assert payload["sourceActivities"][0]["mappingId"] == "procurement.Order.orders"
    _assert_no_physical_sql(payload)


def test_ambiguous_perspective_is_not_guessed(client: TestClient) -> None:
    response = _post(client, "GQ06_AMBIGUOUS_PERSPECTIVE")
    assert response.status_code == 200
    payload = response.json()
    obs = _observation(payload)
    assert obs["kind"] != "PRESENT"
    assert obs.get("value") not in {"100.10", "100.1000", "0", "0.0000"}
    codes = {item["code"] for item in payload["diagnostics"]}
    assert "AMBIGUOUS_MAPPING" in codes
    assert obs["reason"] == "AMBIGUOUS_MAPPING"


def test_conflicting_grain_is_not_guessed(client: TestClient) -> None:
    response = _post(client, "GQ07_AMBIGUOUS_GRAIN")
    assert response.status_code == 200
    payload = response.json()
    obs = _observation(payload)
    assert obs["kind"] != "PRESENT"
    assert obs.get("value") not in {"110.1000", "200.0000", "0", "0.0000"}
    # Incomplete semantic grain is now rejected before reading several years of rows.
    assert obs["reason"] == "INVALID_BINDINGS"


def test_claim_unknown_false_and_true_are_distinct(client: TestClient) -> None:
    unknown = _post(client, "GQ08_CLAIM_UNKNOWN_2025")
    false_claim = _post(client, "GQ09_CLAIM_FALSE_TAX")
    true_claim = _post(client, "GQ10_CLAIM_TRUE_PROC")
    assert unknown.status_code == 200
    assert false_claim.status_code == 200
    assert true_claim.status_code == 200
    assert unknown.json()["claim"]["truth"] == "UNKNOWN"
    assert "NULL_INPUT" in unknown.json()["claim"]["reasonCodes"]
    assert false_claim.json()["claim"]["truth"] == "FALSE"
    assert true_claim.json()["claim"]["truth"] == "TRUE"
    assert unknown.json()["claim"]["evaluationId"] != false_claim.json()["claim"]["evaluationId"]
    assert unknown.json()["claim"]["claimId"] == "tax.incomeReconciles"
    assert true_claim.json()["claim"]["claimId"] == "procurement.amountWithinLimit"


def test_procurement_over_limit_is_false_not_unknown(client: TestClient) -> None:
    _ensure_over_limit_order()
    response = _post(client, "GQ11_CLAIM_FALSE_PROC")
    assert response.status_code == 200
    assert response.json()["claim"]["truth"] == "FALSE"


def test_missing_null_and_unavailable_are_distinct(client: TestClient) -> None:
    missing = _post(client, "GQ12_MISSING_ROW")
    null = _post(client, "GQ13_NULL_AUDIT_INCOME")
    unavailable = _post(client, "GQ14_UNAVAILABLE_MIXED_SOURCE")
    assert missing.status_code == 200
    assert null.status_code == 200
    assert unavailable.status_code == 200
    missing_obs = _observation(missing.json())
    null_obs = _observation(null.json())
    unavailable_obs = _observation(unavailable.json())
    assert missing_obs["kind"] == "MISSING"
    assert missing_obs["reason"] == "NO_ROW"
    assert missing_obs["value"] is None
    assert null_obs["kind"] == "NULL"
    assert null_obs["reason"] == "NULL_INPUT"
    assert null_obs["value"] is None
    assert unavailable_obs["kind"] == "UNAVAILABLE"
    assert unavailable_obs["reason"] not in {None, "NO_ROW", "NULL_INPUT"}
    assert unavailable_obs["value"] is None
    kinds = {missing_obs["kind"], null_obs["kind"], unavailable_obs["kind"]}
    assert kinds == {"MISSING", "NULL", "UNAVAILABLE"}


def test_success_evidence_has_mapping_without_sql(client: TestClient) -> None:
    response = _post(client, "GQ15_EVIDENCE_NO_SQL")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "SUCCEEDED"
    activities = payload["sourceActivities"]
    assert activities
    assert activities[0]["mappingId"] == "tax.reportedIncome.pg"
    assert activities[0]["sourceId"] == "tax_pg"
    assert activities[0]["activityId"]
    _assert_no_physical_sql(payload)


def test_role_deny_is_forbidden_not_missing(client: TestClient) -> None:
    http = _post(client, "GQ16_ROLE_DENY")
    assert http.status_code == 200
    obs = _observation(http.json())
    assert obs["kind"] == "FORBIDDEN"
    assert obs["kind"] != "MISSING"
    assert obs["value"] is None
    guest = RequestActor(tenant="tenant-a", subject="eve", roles=("guest",))
    envelope = client.app.state.services.query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                MetricSelect(
                    metric="tax.reportedIncome",
                    bindings={
                        "taxpayer": "TAXPAYER-A",
                        "taxYear": 2024,
                        "perspective": "TAX_RETURN",
                    },
                ),
            ),
            context=QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"}),
        ),
        guest,
    )
    assert envelope.observations[0].kind == "FORBIDDEN"
    assert envelope.status == "FAILED"


def test_other_tenant_does_not_see_tenant_a_values(client: TestClient) -> None:
    own = _post(client, "GQ17_TENANT_ISOLATION")
    tax = client.post(
        "/v0.1/query",
        json={
            "metric": "tax.reportedIncome",
            "bindings": {
                "taxpayer": "TAXPAYER-A",
                "taxYear": 2024,
                "perspective": "TAX_RETURN",
            },
            "periodFrom": "2024-01-01",
            "periodTo": "2025-01-01",
        },
        headers=_headers(OTHER_TENANT),
    )
    assert own.status_code == 200
    assert tax.status_code == 200
    order = _observation(own.json())
    income = _observation(tax.json())
    assert order["kind"] != "PRESENT"
    assert order.get("value") not in {"1200.0000", "1200.00"}
    assert income["kind"] == "PRESENT"
    assert Decimal(income["value"]) == Decimal("999.9900")
    assert Decimal(income["value"]) != Decimal("110.1000")


def test_version_switch_uses_query_active_and_does_not_mix() -> None:
    services = build_services(load_data=True)
    app = create_app(load_services=False)
    app.state.services = services
    app.include_router(router)
    local = TestClient(app)
    headers = _headers(ANALYST)
    body = GOLD_BY_ID["GQ18_VERSION_SWITCH"].typed_request["body"]
    before = local.post("/v0.1/query", json=body, headers=headers)
    assert before.status_code == 200
    pinned = services.query_active("tenant-a")
    docs = list(documents_from_bundle(services.bundle))
    for doc in docs:
        if doc["id"] == "tax.reportedIncome.pg":
            doc["physical"]["filters"]["metric"] = "otherRevenue"
    compiled = compile_documents(docs)
    assert compiled.ok and compiled.bundle is not None
    active = compiled.bundle
    services.registry.publish(active, publisher="g4-reviewer")
    pointer = services.studio_releases.pointer("tenant-a", services.environment)
    services.registry.activate(
        "tenant:tenant-a:dev",
        active.digest,
        expected_revision=pointer[1],
    )
    try:
        after = local.post("/v0.1/query", json=body, headers=headers)
        assert after.status_code == 200
        assert after.json()["releaseDigest"] == active.digest
        assert after.json()["releaseDigest"] != before.json()["releaseDigest"]
        assert after.json()["observations"][0]["kind"] == "PRESENT"
        assert after.json()["observations"][0]["value"] != before.json()["observations"][0]["value"]
        old = pinned.execute(
            QueryRequest(
                api_version="semaloom/v0.1",
                select=(MetricSelect(metric=body["metric"], bindings=body["bindings"]),),
                context=QueryContext(
                    business_period={"from": body["periodFrom"], "to": body["periodTo"]}
                ),
            ),
            RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",)),
        )
        assert old.release_digest == before.json()["releaseDigest"]
        assert old.observations[0].value == before.json()["observations"][0]["value"]
        other = local.post("/v0.1/query", json=body, headers=_headers(OTHER_TENANT))
        assert other.json()["releaseDigest"] == before.json()["releaseDigest"]
        claim = local.post(
            "/v0.1/claims/evaluate",
            json={
                "claimId": "tax.incomeReconciles",
                "bindings": {"taxpayer": "TAXPAYER-A", "taxYear": 2024},
                "periodFrom": "2024-01-01",
                "periodTo": "2025-01-01",
                "dimensions": {"jurisdiction": "CN"},
            },
            headers=headers,
        )
        assert claim.status_code == 200
        assert claim.json()["releaseDigest"] == active.digest
    finally:
        services.registry.activate(
            "tenant:tenant-a:dev",
            services.bundle.digest,
            expected_revision=services.studio_releases.pointer("tenant-a", "dev")[1],
        )
        services.close()


def test_action_plan_approve_execute_across_domains(client: TestClient) -> None:
    plan = _post(client, "GQ19_ACTION_TAX_DRAFT")
    assert plan.status_code == 200
    plan_id = plan.json()["planId"]
    denied = client.post(
        "/v0.1/actions/approve",
        json={"planId": plan_id},
        headers=_headers(ANALYST),
    )
    assert denied.status_code == 403
    llm = client.post(
        "/v0.1/actions/approve",
        json={"planId": plan_id, "approved": True},
        headers=_headers(APPROVER),
    )
    assert llm.status_code == 422
    unapproved = client.post(
        "/v0.1/actions/execute",
        json={"planId": plan_id},
        headers=_headers(ANALYST),
    )
    assert unapproved.status_code == 403
    assert unapproved.json()["detail"] == "UNAPPROVED"
    approved = client.post(
        "/v0.1/actions/approve",
        json={"planId": plan_id},
        headers=_headers(APPROVER),
    )
    assert approved.status_code == 200
    executed = client.post(
        "/v0.1/actions/execute",
        json={"planId": plan_id},
        headers=_headers(ANALYST),
    )
    assert executed.status_code == 200
    assert executed.json()["status"] == "VERIFIED"
    status = client.get(f"/v0.1/actions/{plan_id}", headers=_headers(ANALYST))
    assert status.json()["status"] == "VERIFIED"

    proc = _post(client, "GQ20_ACTION_PROC_DRAFT")
    assert proc.status_code == 200
    proc_id = proc.json()["planId"]
    assert (
        client.post(
            "/v0.1/actions/approve",
            json={"planId": proc_id},
            headers=_headers(APPROVER),
        ).status_code
        == 200
    )
    proc_exec = client.post(
        "/v0.1/actions/execute",
        json={"planId": proc_id},
        headers=_headers(ANALYST),
    )
    assert proc_exec.status_code == 200
    assert proc_exec.json()["status"] == "VERIFIED"


def test_reject_sql_url_and_caller_permissions(client: TestClient) -> None:
    sql = _post(client, "GQ21_REJECT_SQL")
    url = _post(client, "GQ22_REJECT_URL_PERMISSIONS")
    extra_sql = client.post(
        "/v0.1/query",
        json={
            "metric": "tax.reportedIncome",
            "bindings": {"taxpayer": "TAXPAYER-A", "taxYear": 2024},
            "periodFrom": "2024-01-01",
            "periodTo": "2025-01-01",
            "sql": "select 1",
        },
        headers=_headers(ANALYST),
    )
    extra_url = client.post(
        "/v0.1/actions/plan",
        json={
            "actionId": "tax.CreateTaxAdjustmentDraft",
            "target": {"taxpayerId": "TAXPAYER-A"},
            "parameters": {"amount": "10.00", "taxYear": "2024"},
            "url": "https://evil.example/write",
        },
        headers=_headers(ANALYST),
    )
    assert sql.status_code == 400
    assert sql.json()["detail"] == "INVALID_REQUEST"
    assert url.status_code == 400
    assert extra_sql.status_code == 422
    assert extra_url.status_code == 422
    poison = client.post(
        "/v0.1/query",
        json={
            "metric": "tax.reportedIncome",
            "bindings": {
                "taxpayer": "TAXPAYER-A'; DROP TABLE tax_metric;--",
                "taxYear": 2024,
                "perspective": "TAX_RETURN",
            },
            "periodFrom": "2024-01-01",
            "periodTo": "2025-01-01",
        },
        headers=_headers(ANALYST),
    )
    assert poison.status_code == 200
    assert _observation(poison.json())["kind"] in {"MISSING", "UNAVAILABLE"}
    still = _post(client, "GQ03_QUERY_TAX_REPORTED_INCOME")
    assert Decimal(_observation(still.json())["value"]) == Decimal("110.1000")


def test_policy_period_switch_and_straddle(client: TestClient) -> None:
    y2024 = _post(client, "GQ23_POLICY_PERIOD_SWITCH")
    y2025 = client.post(
        "/v0.1/claims/evaluate",
        json={
            "claimId": "tax.incomeReconciles",
            "bindings": {"taxpayer": "TAXPAYER-A", "taxYear": 2025},
            "periodFrom": "2025-01-01",
            "periodTo": "2026-01-01",
            "dimensions": {"jurisdiction": "CN"},
        },
        headers=_headers(ANALYST),
    )
    straddle = client.post(
        "/v0.1/claims/evaluate",
        json={
            "claimId": "tax.incomeReconciles",
            "bindings": {"taxpayer": "TAXPAYER-A", "taxYear": 2024},
            "periodFrom": "2024-06-01",
            "periodTo": "2025-06-01",
            "dimensions": {"jurisdiction": "CN"},
        },
        headers=_headers(ANALYST),
    )
    assert y2024.status_code == 200
    assert y2025.status_code == 200
    assert y2024.json()["claim"]["context"]["policyId"] == "tax.incomeReconcilesY2024"
    assert y2025.json()["claim"]["context"]["policyId"] == "tax.incomeReconcilesY2025"
    assert straddle.status_code == 422
    assert straddle.json()["detail"] == "POLICY_PERIOD_SPLIT_REQUIRED"


def test_mcp_tools_list_rejects_physical_fields_and_is_not_transport(
    client: TestClient,
) -> None:
    missing = client.get("/v0.1/mcp/tools")
    invalid = client.get("/v0.1/mcp/tools", headers=_headers("Bearer nope"))
    tools = client.get("/v0.1/mcp/tools", headers=_headers(ANALYST))
    modeler = client.get("/v0.1/mcp/tools", headers=_headers(MODELER))
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert tools.status_code == 200
    assert modeler.status_code == 403
    payload = tools.json()["tools"]
    names = {item["name"] for item in payload}
    assert names == {"semantic_query", "evaluate_claim", "plan_action", "action_status"}
    for item in payload:
        fields = {str(field).lower() for field in item["input"]}
        assert not (fields & FORBIDDEN_REQUEST_FIELDS)
    assert "search_semantics" not in names
    assert "execute_sql" not in names


@pytest.mark.skip(reason="依赖未就绪: M3 MCP")
def test_real_mcp_transport_query_evaluate_explain() -> None:
    raise AssertionError("real MCP transport is not implemented")


def test_unauthenticated_invalid_token_and_forged_headers(client: TestClient) -> None:
    body = GOLD_BY_ID["GQ03_QUERY_TAX_REPORTED_INCOME"].typed_request["body"]
    missing = client.post("/v0.1/query", json=body)
    invalid = client.post("/v0.1/query", json=body, headers=_headers("Bearer nope"))
    forged = client.post(
        "/v0.1/query",
        json=body,
        headers={"X-Forwarded-User": "alice", "X-Tenant": "tenant-a"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert forged.status_code == 401
    assert missing.json()["detail"] == "UNAUTHENTICATED"


def test_production_profile_does_not_start_demo_services() -> None:
    with pytest.raises(RuntimeError, match="only the local-dev profile"):
        create_app(profile="prod", load_services=True)


def test_same_interface_has_no_industry_branch_and_domain_has_no_physical() -> None:
    forbidden = (
        "if domain ==",
        "if domain==",
        "tax.operatingRevenue",
        "procurement.Order",
        "GRAIN_COLUMNS",
        '"taxYear"',
        '"organizationId"',
        '"jurisdiction"',
        '"taxpayer"',
        '"orderId"',
    )
    roots = (CORE / "core", CORE / "compiler", CORE / "runtime" / "query.py")
    for folder in roots:
        paths = [folder] if folder.is_file() else folder.rglob("*.py")
        for path in paths:
            text_value = path.read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in text_value, f"{path} contains {token}"
    for domain in ("tax", "procurement"):
        for path in (REPO / "examples" / domain / "domain").rglob("*.yaml"):
            text_value = path.read_text(encoding="utf-8")
            assert "table:" not in text_value
            assert "valueColumn:" not in text_value
            assert "identityColumn:" not in text_value
            assert "operationId:" not in text_value


def test_mixed_postgres_and_api_object_with_local_stub() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OrderRiskHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    previous = os.environ.get("SEMALOOM_PROCUREMENT_API_URL")
    os.environ["SEMALOOM_PROCUREMENT_API_URL"] = f"http://{host}:{port}"
    try:
        app = create_app(load_services=True, load_fixtures=True)
        local = TestClient(app)
        _ensure_over_limit_order()
        mixed = local.post(
            "/v0.1/query",
            json=GOLD_BY_ID["GQ14_UNAVAILABLE_MIXED_SOURCE"].typed_request["body"],
            headers=_headers(ANALYST),
        )
        missing_api = local.post(
            "/v0.1/query",
            json={
                "apiVersion": "semaloom/v0.1",
                "select": [
                    {
                        "objectType": "procurement.Order",
                        "identity": {"orderId": "PO-MISSING"},
                        "properties": ["deliveryRisk"],
                    }
                ],
                "context": {"businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"}},
            },
            headers=_headers(ANALYST),
        )
        assert mixed.status_code == 200
        payload = mixed.json()
        obs = _observation(payload)
        assert obs["kind"] == "PRESENT", payload
        values = json.loads(obs["value"] or "{}")
        assert values["status"] == "OPEN"
        assert values["deliveryRisk"] == "LOW"
        sources = {item["sourceId"] for item in payload["sourceActivities"]}
        mappings = {item["mappingId"] for item in payload["sourceActivities"]}
        assert sources == {"orders_pg", "proc_draft_api"}
        assert "procurement.Order.orders" in mappings
        assert "procurement.Order.riskApi" in mappings
        _assert_no_physical_sql(payload)
        assert missing_api.status_code == 200
        missing_obs = _observation(missing_api.json())
        assert missing_obs["kind"] == "MISSING"
        assert missing_obs["value"] is None
        assert missing_obs["reason"] == "NO_ROW"
    finally:
        server.shutdown()
        server.server_close()
        if previous is None:
            os.environ.pop("SEMALOOM_PROCUREMENT_API_URL", None)
        else:
            os.environ["SEMALOOM_PROCUREMENT_API_URL"] = previous


def test_unavailable_source_via_runtime_is_not_false_or_zero(client: TestClient) -> None:
    services = client.app.state.services
    payload = services.bundle.model_dump(mode="json", by_alias=True, exclude_none=True)
    for mapping in payload["mappings"]:
        if mapping["id"] == "tax.reportedIncome.pg":
            mapping["physical"]["table"] = "no_such_relation"
    from semaloom.compiler.digest import sha256_digest
    from semaloom.core.bundle import CompiledBundle

    payload.pop("digest", None)
    payload["digest"] = sha256_digest(payload)
    broken = QueryService(CompiledBundle.model_validate(payload), services.provider)
    envelope = broken.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                MetricSelect(
                    metric="tax.reportedIncome",
                    bindings={
                        "taxpayer": "TAXPAYER-A",
                        "taxYear": 2024,
                        "perspective": "TAX_RETURN",
                    },
                ),
            ),
            context=QueryContext(business_period={"from": "2024-01-01", "to": "2025-01-01"}),
        ),
        RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",)),
    )
    assert envelope.observations[0].kind == "UNAVAILABLE"
    assert envelope.observations[0].value is None
    assert envelope.status == "FAILED"


def test_agent_facing_describe_and_search_exist(client: TestClient) -> None:
    describe = client.get(
        "/v0.1/describe",
        headers=_headers(ANALYST),
        params={"semanticId": "tax.Taxpayer"},
    )
    search = client.get("/v0.1/search", headers=_headers(ANALYST), params={"q": "收入"})
    inspector = client.get(
        "/v0.1/studio/inspector",
        headers=_headers(ANALYST),
        params={"objectId": "tax.Taxpayer"},
    )
    tools = {
        item["name"]
        for item in client.get("/v0.1/mcp/tools", headers=_headers(ANALYST)).json()["tools"]
    }
    if (
        describe.status_code == 200
        and "id" in describe.json()
        and "physicalField" not in _dump(describe.json())
        and search.status_code == 200
    ):
        return
    pytest.fail(
        "A40/A41/A51 失败: Agent 面向 describe/search 未交付。"
        f" GET /v0.1/describe -> {describe.status_code};"
        f" GET /v0.1/search?q=收入 -> {search.status_code};"
        f" GET /v0.1/studio/inspector as analyst -> {inspector.status_code};"
        f" MCP tools={sorted(tools)} (name list, not MCP transport)."
        " Studio inspector requires modeler and leaks physicalField; not a substitute."
    )


def test_tax_taxpayer_object_properties_are_readable(client: TestClient) -> None:
    response = client.post(
        "/v0.1/query",
        json={
            "apiVersion": "semaloom/v0.1",
            "select": [
                {
                    "objectType": "tax.Taxpayer",
                    "identity": {"taxpayerId": "TAXPAYER-A"},
                    "properties": ["name", "jurisdiction"],
                }
            ],
            "context": {"businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"}},
        },
        headers=_headers(ANALYST),
    )
    assert response.status_code == 200
    obs = _observation(response.json())
    if obs["kind"] == "PRESENT":
        values = json.loads(obs["value"] or "{}")
        assert values["name"]
        assert values["jurisdiction"] == "CN"
        return
    pytest.fail(
        "A50 失败: tax.Taxpayer 对象属性点查不可读。"
        " repro: POST /v0.1/query ObjectSelect objectType=tax.Taxpayer"
        " identity.taxpayerId=TAXPAYER-A properties=[name,jurisdiction]"
        f" -> kind={obs['kind']} reason={obs.get('reason')}"
        f" diagnostics={response.json().get('diagnostics')}"
        " Classification: model/integration gap"
        " (tax.Taxpayer.pg does not map name/jurisdiction)."
    )


def test_rest_verifies_jwt_issuer_audience_signature(client: TestClient) -> None:
    ok = client.post(
        "/v0.1/query",
        json=GOLD_BY_ID["GQ03_QUERY_TAX_REPORTED_INCOME"].typed_request["body"],
        headers=_headers(ANALYST),
    )
    assert ok.status_code == 200
    pytest.fail(
        "A58 failed: REST uses the static TOKENS dict; Bearer tenant-a-analyst"
        " has no JWT signature/issuer/audience/expiry check."
        " repro: Authorization: Bearer tenant-a-analyst becomes tenant-a/alice."
        " Invalid token and forged proxy headers are covered separately;"
        " production profile refuses demo. Full production identity is M3/T06;"
        " this case is recorded as failed, not skipped."
    )


def test_compile_examples_digest_is_stable() -> None:
    first = compile_examples()
    second = compile_examples()
    assert first.digest == second.digest
    assert first.digest

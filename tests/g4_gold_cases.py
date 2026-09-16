"""Deterministic gold questions for tax and procurement. No LLM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ANALYST = "Bearer tenant-a-analyst"
APPROVER = "Bearer tenant-a-approver"
OTHER_TENANT = "Bearer tenant-b-analyst"
MODELER = "Bearer tenant-a-modeler"

PERIOD_2024 = {"periodFrom": "2024-01-01", "periodTo": "2025-01-01"}
PERIOD_2025 = {"periodFrom": "2025-01-01", "periodTo": "2026-01-01"}


@dataclass(frozen=True)
class GoldQuestion:
    id: str
    domain: str
    nl_intent: str
    typed_request: dict[str, Any]
    acceptance: tuple[str, ...]
    notes: str = ""


def _query_metric(
    metric: str, bindings: dict[str, str | int], period: dict[str, str]
) -> dict[str, Any]:
    return {
        "interface": "POST /v0.1/query",
        "headers": {"Authorization": ANALYST},
        "body": {"metric": metric, "bindings": bindings, **period},
    }


def _query_object(
    object_type: str, identity: dict[str, str], properties: list[str]
) -> dict[str, Any]:
    return {
        "interface": "POST /v0.1/query",
        "headers": {"Authorization": ANALYST},
        "body": {
            "apiVersion": "semaloom/v0.1",
            "select": [
                {
                    "objectType": object_type,
                    "identity": identity,
                    "properties": properties,
                }
            ],
            "context": {"businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"}},
        },
    }


def _claim(
    claim_id: str,
    bindings: dict[str, str | int],
    period: dict[str, str],
    dimensions: dict[str, str],
) -> dict[str, Any]:
    return {
        "interface": "POST /v0.1/claims/evaluate",
        "headers": {"Authorization": ANALYST},
        "body": {
            "claimId": claim_id,
            "bindings": bindings,
            **period,
            "dimensions": dimensions,
        },
    }


GOLD_QUESTIONS: tuple[GoldQuestion, ...] = (
    GoldQuestion(
        id="GQ01_DESCRIBE_TAXPAYER",
        domain="tax",
        nl_intent="描述实体 tax.Taxpayer 的含义、身份键和属性,不要给数据库表名。",
        typed_request={
            "interface": "GET /v0.1/describe",
            "headers": {"Authorization": ANALYST},
            "params": {"semanticId": "tax.Taxpayer"},
        },
        acceptance=("A40", "A51"),
        notes="Agent-facing describe; Studio inspector is not this interface.",
    ),
    GoldQuestion(
        id="GQ02_DESCRIBE_REPORTED_INCOME",
        domain="tax",
        nl_intent="描述指标 tax.reportedIncome 的单位、粒度和口径。",
        typed_request={
            "interface": "GET /v0.1/describe",
            "headers": {"Authorization": ANALYST},
            "params": {"semanticId": "tax.reportedIncome"},
        },
        acceptance=("A40", "A51"),
    ),
    GoldQuestion(
        id="GQ03_QUERY_TAX_REPORTED_INCOME",
        domain="tax",
        nl_intent="读取 TAXPAYER-A 在 2024 年申报口径的 tax.reportedIncome。",
        typed_request=_query_metric(
            "tax.reportedIncome",
            {"taxpayer": "TAXPAYER-A", "taxYear": 2024, "perspective": "TAX_RETURN"},
            PERIOD_2024,
        ),
        acceptance=("A40", "A44", "A46", "A60"),
    ),
    GoldQuestion(
        id="GQ04_QUERY_PROC_ORDER_AMOUNT",
        domain="procurement",
        nl_intent="读取采购订单 PO-001 的 procurement.orderAmount。",
        typed_request=_query_metric(
            "procurement.orderAmount",
            {"orderId": "PO-001"},
            PERIOD_2024,
        ),
        acceptance=("A40", "A44", "A46", "A60"),
    ),
    GoldQuestion(
        id="GQ05_QUERY_PROC_ORDER_OBJECT",
        domain="procurement",
        nl_intent="读取采购订单 PO-001 的对象属性 status。",
        typed_request=_query_object("procurement.Order", {"orderId": "PO-001"}, ["status"]),
        acceptance=("A40", "A44", "A50", "A63"),
    ),
    GoldQuestion(
        id="GQ06_AMBIGUOUS_PERSPECTIVE",
        domain="tax",
        nl_intent="查询 TAXPAYER-A 2024 年的营业收入,不指定申报或审计口径。",
        typed_request=_query_metric(
            "tax.operatingRevenue",
            {"taxpayer": "TAXPAYER-A", "taxYear": 2024},
            PERIOD_2024,
        ),
        acceptance=("A04", "A06", "A40", "A41", "A46"),
        notes="Must return AMBIGUOUS_MAPPING, not a guessed amount.",
    ),
    GoldQuestion(
        id="GQ07_AMBIGUOUS_GRAIN",
        domain="tax",
        nl_intent="查询 TAXPAYER-A 的 tax.reportedIncome,不给所属期。",
        typed_request=_query_metric(
            "tax.reportedIncome",
            {"taxpayer": "TAXPAYER-A", "perspective": "TAX_RETURN"},
            PERIOD_2024,
        ),
        acceptance=("A11", "A40", "A46"),
        notes="Conflicting grain must not pick first/last year.",
    ),
    GoldQuestion(
        id="GQ08_CLAIM_UNKNOWN_2025",
        domain="tax",
        nl_intent="评估 TAXPAYER-A 2025 年 tax.incomeReconciles 是否成立。",
        typed_request=_claim(
            "tax.incomeReconciles",
            {"taxpayer": "TAXPAYER-A", "taxYear": 2025},
            PERIOD_2025,
            {"jurisdiction": "CN"},
        ),
        acceptance=("A18", "A40", "A46"),
    ),
    GoldQuestion(
        id="GQ09_CLAIM_FALSE_TAX",
        domain="tax",
        nl_intent="评估 TAXPAYER-B 2024 年 tax.incomeReconciles 是否成立。",
        typed_request=_claim(
            "tax.incomeReconciles",
            {"taxpayer": "TAXPAYER-B", "taxYear": 2024},
            PERIOD_2024,
            {"jurisdiction": "CN"},
        ),
        acceptance=("A20", "A44", "A46"),
    ),
    GoldQuestion(
        id="GQ10_CLAIM_TRUE_PROC",
        domain="procurement",
        nl_intent="评估 PO-001 是否满足 procurement.amountWithinLimit。",
        typed_request=_claim(
            "procurement.amountWithinLimit",
            {"orderId": "PO-001", "organizationId": "ORG-A"},
            PERIOD_2024,
            {"organizationId": "ORG-A"},
        ),
        acceptance=("A44", "A46", "A60"),
    ),
    GoldQuestion(
        id="GQ11_CLAIM_FALSE_PROC",
        domain="procurement",
        nl_intent="评估超授权订单 PO-OVER 是否满足 procurement.amountWithinLimit。",
        typed_request=_claim(
            "procurement.amountWithinLimit",
            {"orderId": "PO-OVER", "organizationId": "ORG-A"},
            PERIOD_2024,
            {"organizationId": "ORG-A"},
        ),
        acceptance=("A44", "A46"),
        notes="G4 test inserts PO-OVER into isolated orders DB only.",
    ),
    GoldQuestion(
        id="GQ12_MISSING_ROW",
        domain="tax",
        nl_intent="读取 TAXPAYER-B 2025 年申报口径 reportedIncome。",
        typed_request=_query_metric(
            "tax.reportedIncome",
            {"taxpayer": "TAXPAYER-B", "taxYear": 2025, "perspective": "TAX_RETURN"},
            PERIOD_2025,
        ),
        acceptance=("A10", "A18", "A46"),
    ),
    GoldQuestion(
        id="GQ13_NULL_AUDIT_INCOME",
        domain="tax",
        nl_intent="读取 TAXPAYER-A 2025 年审计口径 auditIncome。",
        typed_request=_query_metric(
            "tax.auditIncome",
            {"taxpayer": "TAXPAYER-A", "taxYear": 2025, "perspective": "AUDIT_REPORT"},
            PERIOD_2025,
        ),
        acceptance=("A10", "A18", "A46"),
    ),
    GoldQuestion(
        id="GQ14_UNAVAILABLE_MIXED_SOURCE",
        domain="procurement",
        nl_intent="读取 PO-001 的 status 和 deliveryRisk。",
        typed_request=_query_object(
            "procurement.Order",
            {"orderId": "PO-001"},
            ["status", "deliveryRisk"],
        ),
        acceptance=("A15", "A46", "A63"),
        notes="Without a live OpenAPI source this is UNAVAILABLE, not MISSING/FALSE/zero.",
    ),
    GoldQuestion(
        id="GQ15_EVIDENCE_NO_SQL",
        domain="tax",
        nl_intent="解释刚才 TAXPAYER-A 2024 申报收入是怎么得到的。",
        typed_request=_query_metric(
            "tax.reportedIncome",
            {"taxpayer": "TAXPAYER-A", "taxYear": 2024, "perspective": "TAX_RETURN"},
            PERIOD_2024,
        ),
        acceptance=("A25", "A27", "A40", "A46"),
    ),
    GoldQuestion(
        id="GQ16_ROLE_DENY",
        domain="shared",
        nl_intent="用没有查询角色的身份读取 tax.reportedIncome。",
        typed_request={
            "interface": "POST /v0.1/query",
            "headers": {"Authorization": MODELER},
            "body": {
                "metric": "tax.reportedIncome",
                "bindings": {
                    "taxpayer": "TAXPAYER-A",
                    "taxYear": 2024,
                    "perspective": "TAX_RETURN",
                },
                **PERIOD_2024,
            },
        },
        acceptance=("A24", "A40", "A58"),
    ),
    GoldQuestion(
        id="GQ17_TENANT_ISOLATION",
        domain="procurement",
        nl_intent="用 tenant-b 读取 PO-001 的订单金额。",
        typed_request={
            "interface": "POST /v0.1/query",
            "headers": {"Authorization": OTHER_TENANT},
            "body": {
                "metric": "procurement.orderAmount",
                "bindings": {"orderId": "PO-001"},
                **PERIOD_2024,
            },
        },
        acceptance=("A24", "A40"),
    ),
    GoldQuestion(
        id="GQ18_VERSION_SWITCH",
        domain="tax",
        nl_intent="激活新的语义版本后再查询 tax.reportedIncome,已开始的请求不能混版。",
        typed_request=_query_metric(
            "tax.reportedIncome",
            {"taxpayer": "TAXPAYER-A", "taxYear": 2024},
            PERIOD_2024,
        ),
        acceptance=("A28", "A40", "A46"),
    ),
    GoldQuestion(
        id="GQ19_ACTION_TAX_DRAFT",
        domain="tax",
        nl_intent="为 TAXPAYER-A 计划金额 10.00 的税务调整草稿,分析师不能自批。",
        typed_request={
            "interface": "POST /v0.1/actions/plan",
            "headers": {"Authorization": ANALYST},
            "body": {
                "actionId": "tax.CreateTaxAdjustmentDraft",
                "target": {"taxpayerId": "TAXPAYER-A"},
                "parameters": {"amount": "10.00", "taxYear": "2024"},
            },
        },
        acceptance=("A32", "A33", "A43", "A45", "A46"),
    ),
    GoldQuestion(
        id="GQ20_ACTION_PROC_DRAFT",
        domain="procurement",
        nl_intent="为 PO-001 计划金额 10.00 的采购草稿并完成批准执行。",
        typed_request={
            "interface": "POST /v0.1/actions/plan",
            "headers": {"Authorization": ANALYST},
            "body": {
                "actionId": "procurement.CreatePurchaseDraft",
                "target": {"orderId": "PO-001"},
                "parameters": {"amount": "10.00"},
            },
        },
        acceptance=("A32", "A43", "A45", "A46", "A63"),
    ),
    GoldQuestion(
        id="GQ21_REJECT_SQL",
        domain="shared",
        nl_intent="直接执行 SQL: SELECT amount FROM tax_metric。",
        typed_request={
            "interface": "POST /v0.1/query",
            "headers": {"Authorization": ANALYST},
            "body": {
                "metric": "tax.reportedIncome",
                "bindings": {"sql": "SELECT amount FROM tax_metric", "taxpayer": "TAXPAYER-A"},
                **PERIOD_2024,
            },
        },
        acceptance=("A12", "A40", "A41", "A42"),
    ),
    GoldQuestion(
        id="GQ22_REJECT_URL_PERMISSIONS",
        domain="shared",
        nl_intent="在查询里带上目标 URL 和调用方权限。",
        typed_request={
            "interface": "POST /v0.1/query",
            "headers": {"Authorization": ANALYST},
            "body": {
                "metric": "tax.reportedIncome",
                "bindings": {
                    "url": "https://evil.example/tax",
                    "permissions": "admin",
                    "taxpayer": "TAXPAYER-A",
                },
                **PERIOD_2024,
            },
        },
        acceptance=("A12", "A40", "A41"),
    ),
    GoldQuestion(
        id="GQ23_POLICY_PERIOD_SWITCH",
        domain="tax",
        nl_intent="比较 2024 与 2025 的 incomeReconciles 政策是否同一规则。",
        typed_request=_claim(
            "tax.incomeReconciles",
            {"taxpayer": "TAXPAYER-A", "taxYear": 2024},
            PERIOD_2024,
            {"jurisdiction": "CN"},
        ),
        acceptance=("A21", "A46", "A51"),
    ),
    GoldQuestion(
        id="GQ24_MCP_TOOLS_LIST",
        domain="shared",
        nl_intent="列出可调用的语义工具,不要提供任意 SQL 工具。",
        typed_request={
            "interface": "GET /v0.1/mcp/tools",
            "headers": {"Authorization": ANALYST},
            "body": None,
        },
        acceptance=("A40", "A41", "A42"),
        notes="Name list only. Real MCP transport is M3.",
    ),
)

GOLD_BY_ID = {item.id: item for item in GOLD_QUESTIONS}
GOLD_BY_INTENT = {item.nl_intent: item for item in GOLD_QUESTIONS}


def typed_request_for(nl_intent: str) -> dict[str, Any]:
    """Map a catalog natural-language intent to a typed request. No LLM."""

    try:
        return GOLD_BY_INTENT[nl_intent].typed_request
    except KeyError as exc:
        raise KeyError(f"no deterministic mapping for intent: {nl_intent}") from exc


def request_keys(payload: dict[str, Any]) -> set[str]:
    keys: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                keys.add(str(key).lower())
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return keys

"""Verify local HTTP analysis against independent base-table arithmetic; print counts only."""

from __future__ import annotations

import json
import os
from collections import Counter
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

FACTOR_COLUMNS = {
    "audit_profit": "income_statement.total_profit",
    "net_profit": "income_statement.net_profit",
    "tax_expense": "income_statement.income_tax_expense",
    "assets": "balance_sheet.total_assets",
    "liabilities": "balance_sheet.total_liabilities",
    "equity": "balance_sheet.total_equity",
}


def main() -> None:
    url = os.environ["SEMALOOM_SAMPLE_DATABASE_URL"]
    target = make_url(url)
    if (
        target.host not in {"localhost", "127.0.0.1", "::1"}
        or target.database != "semaloom_samples"
        or target.query
    ):
        raise ValueError("requires the isolated local sample database")
    base = os.environ["SEMALOOM_SAMPLE_API_URL"].rstrip("/")
    if base not in {"http://127.0.0.1:8000", "http://localhost:8000"}:
        raise ValueError("requires the local sample application")
    engine = create_engine(url)
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            cases = (
                conn.execute(
                    text("""SELECT r.id,r.tax_year,d.total_profit,d.period_start,
                d.period_end+1 AS period_to,c.name FROM sample_audit_report r
                JOIN sample_declaration d ON d.tenant_id=r.tenant_id AND d.id=r.declaration_id
                JOIN sample_taxpayer c ON c.tenant_id=r.tenant_id AND c.id=r.taxpayer_id
                WHERE r.tenant_id='tenant-a' ORDER BY r.id""")
                )
                .mappings()
                .all()
            )
            factors = (
                conn.execute(
                    text("""SELECT report_id,factor_ref,value_current,value_status_current
                FROM sample_audit_factor WHERE tenant_id='tenant-a' """)
                )
                .mappings()
                .all()
            )
        results: Counter[str] = Counter()
        with httpx.Client(
            base_url=base, headers={"Authorization": "Bearer tenant-a-analyst"}, timeout=20
        ) as client:
            catalog = client.get("/v0.1/agent/tools")
            catalog.raise_for_status()
            assert len(catalog.json()["tools"]) == 5

            def post(path: str, body: dict) -> dict:
                response = client.post("/v0.1/" + path, json=body)
                response.raise_for_status()
                return response.json()

            for case in cases:
                found = post(
                    "objects/search",
                    {
                        "objectType": "finance.ReviewCase",
                        "filters": {"companyName": case["name"], "taxYear": case["tax_year"]},
                        "properties": [
                            "periodStart",
                            "periodTo",
                            "uniquePair",
                            "sourceReviewStatus",
                            "unitBasis",
                        ],
                    },
                )
                assert len(found["objects"]) == 1 and not found["hasMore"]
                record = found["objects"][0]
                assert record["identity"] == {"caseId": case["id"]}
                assert record["properties"]["sourceReviewStatus"] == "unreviewed"
                assert record["properties"]["unitBasis"] == "UPSTREAM_CNY_CONTRACT"
                values = {"declared_profit": case["total_profit"]}
                for key, ref in FACTOR_COLUMNS.items():
                    rows = [
                        f
                        for f in factors
                        if f["report_id"] == case["id"] and f["factor_ref"] == ref
                    ]
                    values[key] = (
                        Decimal(rows[0]["value_current"])
                        if len(rows) == 1
                        and rows[0]["value_status_current"] == "observed"
                        and rows[0]["value_current"] is not None
                        else None
                    )
                period = {"from": str(case["period_start"]), "to": str(case["period_to"])}
                query = {
                    "apiVersion": "semaloom/v0.1",
                    "select": [
                        {"metric": "finance.review." + key, "bindings": {"caseId": case["id"]}}
                        for key in [*values, "profitDifference"]
                    ],
                    "context": {"businessPeriod": period},
                }
                response = post("query", query)
                assert response["status"] == "SUCCEEDED"
                diff = (
                    values["declared_profit"] - values["audit_profit"]
                    if values["declared_profit"] is not None and values["audit_profit"] is not None
                    else None
                )
                for observation, expected in zip(
                    response["observations"], [*values.values(), diff], strict=True
                ):
                    assert observation["unit"] == "CNY"
                    assert (
                        Decimal(observation["value"]) if observation["value"] is not None else None
                    ) == expected
                    assert observation["kind"] == ("PRESENT" if expected is not None else "NULL")
                    results["metric_checks"] += 1
                rules = {
                    "profitMatches": (
                        ["declared_profit", "audit_profit"],
                        lambda a, b: a - b,
                        Decimal(".01"),
                    ),
                    "balanceBalances": (
                        ["assets", "liabilities", "equity"],
                        lambda a, b, c: a - b - c,
                        Decimal("1"),
                    ),
                    "netProfitBalances": (
                        ["net_profit", "audit_profit", "tax_expense"],
                        lambda a, b, c: a - (b - c),
                        Decimal("1"),
                    ),
                }
                for rule, (keys, calculate, tolerance) in rules.items():
                    operands = [values[k] for k in keys]
                    expected = (
                        "UNKNOWN"
                        if any(v is None for v in operands)
                        else "TRUE"
                        if abs(calculate(*operands)) <= tolerance
                        else "FALSE"
                    )
                    answer = post(
                        "claims/evaluate",
                        {
                            "claimId": "finance.review." + rule,
                            "bindings": {"caseId": case["id"]},
                            "periodFrom": period["from"],
                            "periodTo": period["to"],
                        },
                    )
                    assert answer["claim"]["truth"] == expected and not answer["diagnostics"]
                    assert set(answer["claim"]["evidenceRefs"]) == {
                        a["activityId"] for a in answer["sourceActivities"]
                    }
                    assert (
                        answer["releaseDigest"]
                        == response["releaseDigest"]
                        == found["releaseDigest"]
                    )
                    results["claim_" + expected] += 1
                query["context"]["businessPeriod"] = {"from": "2023-01-01", "to": "2024-01-01"}
                wrong = post("query", query)
                assert all(
                    o["reason"] == "PERIOD_MISMATCH" and o["value"] is None
                    for o in wrong["observations"]
                )
                results["period_checks"] += 1
                results["samples"] += 1
        print(json.dumps({"status": "PASS", "checks": dict(results)}, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

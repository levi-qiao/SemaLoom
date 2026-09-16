"""Read-only local sample smoke checks. Prints counts and outcomes, never financial values."""

from __future__ import annotations

import json
import os
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main() -> None:
    url = os.environ["SEMALOOM_SAMPLE_DATABASE_URL"]
    parsed = make_url(url)
    if (
        parsed.host not in {"localhost", "127.0.0.1", "::1"}
        or parsed.database != "semaloom_samples"
        or parsed.query
    ):
        raise ValueError("verification requires local sample database")
    base = os.environ["SEMALOOM_SAMPLE_API_URL"].rstrip("/")
    if base not in {"http://127.0.0.1:8000", "http://localhost:8000"}:
        raise ValueError("verification requires the local sample application on port 8000")
    engine = create_engine(url)
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            row = conn.execute(
                text("""
                SELECT r.id,r.declaration_id,r.tax_year,d.revenue,m.review_status
                FROM sample_audit_report r JOIN sample_declaration d
                  ON d.tenant_id=r.tenant_id AND d.id=r.declaration_id
                JOIN sample_mock_review m ON m.tenant_id=r.tenant_id AND m.report_id=r.id
                WHERE r.tenant_id='tenant-a' ORDER BY r.id LIMIT 1
            """)
            ).one()
            writable = conn.execute(
                text("""
                SELECT has_table_privilege(current_user,'sample_declaration','INSERT')
                    OR has_table_privilege(current_user,'sample_declaration','UPDATE')
                    OR has_table_privilege(current_user,'sample_declaration','DELETE')
            """)
            ).scalar_one()
            assert not writable, "runtime sample account must be read-only"
        payload = {
            "apiVersion": "semaloom/v0.1",
            "select": [
                {
                    "objectType": "finance.AuditReport",
                    "identity": {"reportId": row.id},
                    "properties": ["taxYear", "reviewStatus"],
                },
                {"metric": "finance.declaredRevenue", "bindings": {"returnId": row.declaration_id}},
            ],
            "context": {
                "businessPeriod": {"from": f"{row.tax_year}-01-01", "to": f"{row.tax_year}-12-31"}
            },
        }
        with httpx.Client(base_url=base, timeout=10) as client:
            response = client.post(
                "/v0.1/query", json=payload, headers={"Authorization": "Bearer tenant-a-analyst"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "SUCCEEDED"
            assert all(o["kind"] == "PRESENT" for o in body["observations"])
            assert Decimal(body["observations"][1]["value"]) == row.revenue
            properties = json.loads(body["observations"][0]["value"])
            assert properties["reviewStatus"] == row.review_status
            assert {a["sourceId"] for a in body["sourceActivities"]} == {"sample_pg", "sample_api"}
            other = client.post(
                "/v0.1/query", json=payload, headers={"Authorization": "Bearer tenant-b-analyst"}
            )
            assert other.status_code == 200
            assert all(
                o["kind"] != "PRESENT" and o["value"] is None for o in other.json()["observations"]
            )
            assert client.post("/v0.1/query", json=payload).status_code == 401
            assert (
                client.get(
                    "/mock/audit-review", params={"reportId": row.id, "tenant": "tenant-b"}
                ).status_code
                == 404
            )
            assert (
                client.get(
                    "/mock/audit-review", params={"reportId": "missing", "tenant": "tenant-a"}
                ).status_code
                == 404
            )
            mock = client.get(
                "/mock/audit-review", params={"reportId": row.id, "tenant": "tenant-a"}
            )
            assert mock.json()["mocked"] is True
        print(
            "PASS: PostgreSQL + mock API composition, exact amount, read-only grants, "
            "tenant isolation, authentication and missing records"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

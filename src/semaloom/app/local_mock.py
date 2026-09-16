"""Local-only synthetic workflow API, separate from imported financial observations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.engine import Engine


def sample_mock_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/mock", tags=["local synthetic workflow"])

    @router.get("/audit-review", operation_id="getSampleAuditReview")
    def audit_review(
        reportId: str = Query(min_length=1, max_length=128),
        tenant: str = Query(min_length=1, max_length=128),
    ) -> dict[str, Any]:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = 3000"))
            row = conn.execute(
                text("""
                    SELECT report_id, review_status FROM sample_mock_review
                    WHERE tenant_id=:tenant AND report_id=:report AND mocked=true
                """),
                {"tenant": tenant, "report": reportId},
            ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="MOCK_RECORD_NOT_FOUND")
        return {"reportId": row.report_id, "reviewStatus": row.review_status, "mocked": True}

    return router

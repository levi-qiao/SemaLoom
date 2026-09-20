"""All public financial demo mappings read real PostgreSQL synthetic rows."""

from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text

from semaloom.adapters.postgres import PostgresReadProvider
from semaloom.core.results import ObjectSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.fixtures import engines
from semaloom.runtime.query import QueryService
from semaloom.sdk import compile_paths


def test_financial_demo_has_every_declared_sql_source_and_consistent_amounts() -> None:
    root = Path(__file__).resolve().parents[1] / "examples/financial-review"
    compiled = compile_paths([root])
    assert compiled.bundle is not None
    engine = engines()["tax_pg"]
    identities = {
        "finance.Company": {"companyId": "C1"},
        "finance.TaxReturn": {"returnId": "D1"},
        "finance.AuditReport": {"reportId": "R1"},
        "finance.AuditFactor": {"factorId": "R1-profit"},
        "finance.ReturnLine": {"lineId": "D1-1"},
        "finance.ReviewCase": {"caseId": "C1"},
    }
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA financial_demo_regression"))
        conn.execute(text("SET search_path TO financial_demo_regression"))
        conn.exec_driver_sql((root / "fixtures/demo.sql").read_text())
        conn.commit()
        read_engine = create_engine(
            engine.url, connect_args={"options": "-csearch_path=financial_demo_regression"}
        )
        provider = PostgresReadProvider({"sample_pg": read_engine})
        service = QueryService(compiled.bundle, provider)
        actor = RequestActor(tenant="tenant-a", subject="test", roles=("analyst",))
        try:
            for mapping in compiled.bundle.mappings:
                if mapping.provider != "postgres" or mapping.target not in identities:
                    continue
                result = service.execute(
                    QueryRequest(
                        api_version="semaloom/v0.1",
                        context=QueryContext(
                            business_period={"from": "2024-01-01", "to": "2025-01-01"}
                        ),
                        select=(
                            ObjectSelect(
                                object_type=mapping.target,
                                identity=identities[mapping.target],
                                properties=tuple(mapping.physical["propertyColumns"]),
                            ),
                        ),
                    ),
                    actor,
                )
                assert result.observations and result.observations[0].kind == "PRESENT", mapping.id
            totals = conn.execute(
                text(
                    "SELECT tax_year,SUM(revenue) FROM sample_declaration "
                    "WHERE tenant_id='tenant-a' GROUP BY tax_year ORDER BY tax_year"
                )
            ).all()
            assert totals == [
                (2023, Decimal("270.03")),
                (2024, Decimal("300.03")),
                (2025, Decimal("330.03")),
            ]
            assert (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM sample_financial_review r JOIN sample_declaration d "
                        "ON r.tenant_id=d.tenant_id AND r.return_id=d.id "
                        "WHERE r.declared_profit <> d.total_profit"
                    )
                ).scalar()
                == 0
            )
            assert (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM sample_financial_review WHERE audit_profit IS NULL "
                        "AND audit_profit_status='not_disclosed'"
                    )
                ).scalar()
                == 1
            )
        finally:
            read_engine.dispose()
            conn.rollback()
            conn.execute(text("SET search_path TO public"))
            conn.execute(text("DROP SCHEMA financial_demo_regression CASCADE"))
            conn.commit()
    engine.dispose()

"""Synthetic PostgreSQL fixtures. Isolated semaloom_* databases only."""

from __future__ import annotations

import os

from sqlalchemy import text
from sqlalchemy.engine import Engine

from semaloom.adapters.postgres import engine_from_url

LOCAL_URLS = {
    "tax_pg": "postgresql+psycopg://semaloom:semaloom@127.0.0.1:5432/semaloom_tax",
    "orders_pg": "postgresql+psycopg://semaloom:semaloom@127.0.0.1:5432/semaloom_orders",
    "suppliers_pg": ("postgresql+psycopg://semaloom:semaloom@127.0.0.1:5432/semaloom_suppliers"),
    "meta": "postgresql+psycopg://semaloom:semaloom@127.0.0.1:5432/semaloom_meta",
}


def configured_urls() -> dict[str, str]:
    """Resolve physical source bindings at the application boundary."""

    return {
        "tax_pg": os.getenv("SEMALOOM_TAX_DATABASE_URL", LOCAL_URLS["tax_pg"]),
        "orders_pg": os.getenv("SEMALOOM_ORDERS_DATABASE_URL", LOCAL_URLS["orders_pg"]),
        "suppliers_pg": os.getenv("SEMALOOM_SUPPLIERS_DATABASE_URL", LOCAL_URLS["suppliers_pg"]),
        "meta": os.getenv("SEMALOOM_META_DATABASE_URL", LOCAL_URLS["meta"]),
    }


def engines(urls: dict[str, str] | None = None) -> dict[str, Engine]:
    mapping = urls or configured_urls()
    return {key: engine_from_url(url) for key, url in mapping.items()}


def load_synthetic(urls: dict[str, str] | None = None) -> None:
    pool = engines(urls)
    _load_tax(pool["tax_pg"])
    _load_orders(pool["orders_pg"])
    _load_suppliers(pool["suppliers_pg"])
    _load_meta(pool["meta"])
    ensure_control_schema(pool["meta"])


def ensure_control_schema(engine: Engine) -> None:
    """Apply the idempotent control-plane schema without deleting persisted state."""

    statements = (
        """
        CREATE TABLE IF NOT EXISTS semantic_release (
          digest TEXT PRIMARY KEY, payload JSONB NOT NULL, publisher TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS environment_pointer (
          environment TEXT PRIMARY KEY, digest TEXT NOT NULL, revision INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS action_plan (
          plan_id TEXT PRIMARY KEY, digest TEXT NOT NULL, payload JSONB NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS action_approval (
          plan_id TEXT PRIMARY KEY, approver TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
          digest TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS action_execution (
          execution_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
          payload_digest TEXT NOT NULL, external_ref TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS studio_draft (
          tenant_id TEXT NOT NULL, draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
          base_digest TEXT NOT NULL, candidate_digest TEXT NOT NULL, documents JSONB NOT NULL,
          updated_by TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, draft_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS studio_draft_revision (
          tenant_id TEXT NOT NULL, draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
          base_digest TEXT NOT NULL, candidate_digest TEXT NOT NULL, documents JSONB NOT NULL,
          author TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, draft_id, revision)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS studio_source_profile (
          tenant_id TEXT NOT NULL, source_id TEXT NOT NULL, revision INTEGER NOT NULL,
          label TEXT NOT NULL, provider TEXT NOT NULL, binding_ref TEXT NOT NULL,
          secret_ref TEXT, settings JSONB NOT NULL, validation_status TEXT NOT NULL,
          updated_by TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, source_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS studio_validation (
          validation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, draft_id TEXT NOT NULL,
          draft_revision INTEGER NOT NULL, candidate_digest TEXT NOT NULL,
          environment TEXT NOT NULL, status TEXT NOT NULL, details JSONB NOT NULL,
          validator TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS studio_release_approval (
          approval_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, draft_id TEXT NOT NULL,
          draft_revision INTEGER NOT NULL, candidate_digest TEXT NOT NULL,
          environment TEXT NOT NULL, validation_id TEXT NOT NULL, approver TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        ALTER TABLE studio_release_approval
        ADD COLUMN IF NOT EXISTS validation_id TEXT
        """,
        """
        CREATE TABLE IF NOT EXISTS studio_publication (
          publication_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, draft_id TEXT NOT NULL,
          draft_revision INTEGER NOT NULL, digest TEXT NOT NULL, environment TEXT NOT NULL,
          environment_revision INTEGER NOT NULL, publisher TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS studio_session (
          session_hash TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subject TEXT NOT NULL,
          roles JSONB NOT NULL, csrf_hash TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
          revoked_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    )
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _load_tax(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS tax_metric"))
        conn.execute(text("DROP TABLE IF EXISTS tax_taxpayer"))
        conn.execute(
            text(
                """
                CREATE TABLE tax_taxpayer (
                    tenant_id TEXT NOT NULL,
                    taxpayer_id TEXT NOT NULL,
                    name TEXT,
                    jurisdiction TEXT,
                    PRIMARY KEY (tenant_id, taxpayer_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE tax_metric (
                    tenant_id TEXT NOT NULL,
                    taxpayer_id TEXT NOT NULL,
                    tax_year INTEGER NOT NULL,
                    perspective TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    amount NUMERIC(20, 4),
                    PRIMARY KEY (tenant_id, taxpayer_id, tax_year, perspective, metric)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO tax_taxpayer(tenant_id, taxpayer_id, name, jurisdiction)
                VALUES
                  ('tenant-a', 'TAXPAYER-A', 'Demo Co', 'CN'),
                  ('tenant-a', 'TAXPAYER-B', 'Gap Co', 'CN'),
                  ('tenant-b', 'TAXPAYER-A', 'Other Co', 'CN')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO tax_metric(
                    tenant_id, taxpayer_id, tax_year, perspective, metric, amount
                )
                VALUES
                  ('tenant-a', 'TAXPAYER-A', 2024, 'TAX_RETURN', 'operatingRevenue', 100.10),
                  ('tenant-a', 'TAXPAYER-A', 2024, 'AUDIT_REPORT', 'operatingRevenue', 100.10),
                  ('tenant-a', 'TAXPAYER-A', 2024, 'TAX_RETURN', 'otherRevenue', 10.00),
                  ('tenant-a', 'TAXPAYER-A', 2024, 'TAX_RETURN', 'reportedIncome', 110.10),
                  ('tenant-a', 'TAXPAYER-A', 2024, 'AUDIT_REPORT', 'auditIncome', 110.10),
                  ('tenant-a', 'TAXPAYER-A', 2024, 'TAX_RETURN', 'vatPayable', 13.00),
                  ('tenant-a', 'TAXPAYER-A', 2025, 'TAX_RETURN', 'reportedIncome', 200.00),
                  ('tenant-a', 'TAXPAYER-A', 2025, 'AUDIT_REPORT', 'auditIncome', NULL),
                  ('tenant-a', 'TAXPAYER-B', 2024, 'TAX_RETURN', 'reportedIncome', 80.00),
                  ('tenant-a', 'TAXPAYER-B', 2024, 'AUDIT_REPORT', 'auditIncome', 90.00),
                  ('tenant-b', 'TAXPAYER-A', 2024, 'TAX_RETURN', 'reportedIncome', 999.99)
                """
            )
        )


def _load_orders(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS proc_order"))
        conn.execute(text("DROP TABLE IF EXISTS proc_organization"))
        conn.execute(
            text(
                """
                CREATE TABLE proc_organization (
                    tenant_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    name TEXT,
                    approval_limit NUMERIC(20, 4),
                    PRIMARY KEY (tenant_id, organization_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE proc_order (
                    tenant_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    supplier_id TEXT NOT NULL,
                    amount NUMERIC(20, 4),
                    quantity NUMERIC(20, 4),
                    status TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (tenant_id, order_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO proc_organization(tenant_id, organization_id, name, approval_limit)
                VALUES ('tenant-a', 'ORG-A', 'Org A', 5000.00)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO proc_order(
                    tenant_id, order_id, organization_id, supplier_id,
                    amount, quantity, status
                )
                VALUES ('tenant-a', 'PO-001', 'ORG-A', 'SUP-1', 1200.00, 3, 'OPEN')
                """
            )
        )


def _load_suppliers(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS proc_supplier"))
        conn.execute(
            text(
                """
                CREATE TABLE proc_supplier (
                    tenant_id TEXT NOT NULL,
                    supplier_id TEXT NOT NULL,
                    name TEXT,
                    PRIMARY KEY (tenant_id, supplier_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO proc_supplier(tenant_id, supplier_id, name)
                VALUES ('tenant-a', 'SUP-1', 'Supplier One')
                """
            )
        )


def _load_meta(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS studio_session"))
        conn.execute(text("DROP TABLE IF EXISTS studio_publication"))
        conn.execute(text("DROP TABLE IF EXISTS studio_release_approval"))
        conn.execute(text("DROP TABLE IF EXISTS studio_validation"))
        conn.execute(text("DROP TABLE IF EXISTS studio_source_profile"))
        conn.execute(text("DROP TABLE IF EXISTS studio_draft_revision"))
        conn.execute(text("DROP TABLE IF EXISTS studio_draft_legacy"))
        conn.execute(text("DROP TABLE IF EXISTS action_execution"))
        conn.execute(text("DROP TABLE IF EXISTS action_approval"))
        conn.execute(text("DROP TABLE IF EXISTS action_plan"))
        conn.execute(text("DROP TABLE IF EXISTS studio_draft"))
        conn.execute(text("DROP TABLE IF EXISTS environment_pointer"))
        conn.execute(text("DROP TABLE IF EXISTS semantic_release"))
        conn.execute(
            text(
                """
                CREATE TABLE semantic_release (
                    digest TEXT PRIMARY KEY,
                    payload JSONB NOT NULL,
                    publisher TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE environment_pointer (
                    environment TEXT PRIMARY KEY,
                    digest TEXT NOT NULL,
                    revision INTEGER NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE action_plan (
                    plan_id TEXT PRIMARY KEY,
                    digest TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE action_approval (
                    plan_id TEXT PRIMARY KEY,
                    approver TEXT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    digest TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE action_execution (
                    execution_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    external_ref TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE studio_draft (
                    tenant_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    base_digest TEXT NOT NULL,
                    candidate_digest TEXT NOT NULL,
                    documents JSONB NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (tenant_id, draft_id)
                )
                """
            )
        )

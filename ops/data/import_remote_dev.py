"""Bounded, read-only TI sample import. Business rows never become repository fixtures."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA = "tax_cloud_tiifs"
FACTORS = (
    "balance_sheet.retained_earnings",
    "balance_sheet.total_assets",
    "balance_sheet.total_equity",
    "balance_sheet.total_liabilities",
    "income_statement.income_tax_expense",
    "income_statement.main_business_cost",
    "income_statement.main_business_revenue",
    "income_statement.net_profit",
    "income_statement.operating_profit",
    "income_statement.total_profit",
)
NUMERIC = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?$")
DDL = """
CREATE TABLE IF NOT EXISTS sample_import (
  id TEXT PRIMARY KEY, imported_at TIMESTAMPTZ NOT NULL, manifest JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS sample_taxpayer (
  tenant_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
  import_id TEXT NOT NULL REFERENCES sample_import(id), PRIMARY KEY(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS sample_declaration (
  tenant_id TEXT NOT NULL, id TEXT NOT NULL, taxpayer_id TEXT NOT NULL,
  tax_year INTEGER NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL,
  revenue NUMERIC, total_profit NUMERIC, taxable_income NUMERIC, income_tax NUMERIC,
  source_row JSONB NOT NULL, import_id TEXT NOT NULL REFERENCES sample_import(id),
  PRIMARY KEY(tenant_id,id),
  FOREIGN KEY(tenant_id,taxpayer_id) REFERENCES sample_taxpayer(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS sample_declaration_line (
  tenant_id TEXT NOT NULL, id TEXT NOT NULL, declaration_id TEXT NOT NULL,
  line_number TEXT, amount NUMERIC, import_id TEXT NOT NULL REFERENCES sample_import(id),
  PRIMARY KEY(tenant_id,id),
  FOREIGN KEY(tenant_id,declaration_id) REFERENCES sample_declaration(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS sample_audit_report (
  tenant_id TEXT NOT NULL, id TEXT NOT NULL, taxpayer_id TEXT NOT NULL,
  tax_year INTEGER NOT NULL, source_format TEXT, declaration_id TEXT NOT NULL,
  import_id TEXT NOT NULL REFERENCES sample_import(id), PRIMARY KEY(tenant_id,id),
  FOREIGN KEY(tenant_id,taxpayer_id) REFERENCES sample_taxpayer(tenant_id,id),
  FOREIGN KEY(tenant_id,declaration_id) REFERENCES sample_declaration(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS sample_audit_factor (
  tenant_id TEXT NOT NULL, id TEXT NOT NULL, report_id TEXT NOT NULL,
  factor_ref TEXT NOT NULL, value_current TEXT, value_prior TEXT,
  value_status_current TEXT NOT NULL, value_status_prior TEXT,
  numeric_current NUMERIC, import_id TEXT NOT NULL REFERENCES sample_import(id),
  PRIMARY KEY(tenant_id,id),
  FOREIGN KEY(tenant_id,report_id) REFERENCES sample_audit_report(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS sample_mock_review (
  tenant_id TEXT NOT NULL, report_id TEXT NOT NULL, review_status TEXT NOT NULL,
  mocked BOOLEAN NOT NULL CHECK(mocked), PRIMARY KEY(tenant_id,report_id),
  FOREIGN KEY(tenant_id,report_id) REFERENCES sample_audit_report(tenant_id,id)
);
ALTER TABLE sample_audit_report ADD COLUMN IF NOT EXISTS declaration_candidates INTEGER;
ALTER TABLE sample_audit_report ADD COLUMN IF NOT EXISTS report_candidates INTEGER;
ALTER TABLE sample_audit_factor ADD COLUMN IF NOT EXISTS source_review_status TEXT;
ALTER TABLE sample_audit_factor ADD COLUMN IF NOT EXISTS decision_current TEXT;
"""


def local_dsn(value: str) -> str:
    value = value.replace("postgresql+psycopg://", "postgresql://", 1)
    settings = conninfo_to_dict(value)
    # Refuse remote destinations, service-file indirection and accidental writes to source DBs.
    if settings.get("service") or settings.get("hostaddr"):
        raise ValueError("local destination must use an explicit loopback host")
    if settings.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("local destination must use an explicit loopback host")
    if settings.get("dbname") != "semaloom_samples":
        raise ValueError("destination database must be semaloom_samples")
    return value


def pseudonym(key: bytes, kind: str, value: str) -> str:
    return f"{kind}-" + hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:24]


def numeric_value(value: object, status: str) -> Decimal | None:
    if status != "observed" or value is None:
        return None
    text = str(value)
    if not NUMERIC.fullmatch(text):
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def read_samples(conn: psycopg.Connection[Any], per_year: int) -> list[dict[str, Any]]:
    cohort = conn.execute(
        """
      WITH matched AS (
        SELECT DISTINCT d.nsrsbh, extract(year FROM d.period_start)::int AS year
        FROM tax_cloud_tiifs.data_etax_cn_cit_a100000 d
        WHERE d.is_del=0 AND extract(year FROM d.period_start) IN (2024,2025)
          AND d.period_start=make_date(extract(year FROM d.period_start)::int,1,1)
          AND d.period_end=make_date(extract(year FROM d.period_start)::int,12,31)
          AND nullif(d.nsrsbh,'') IS NOT NULL
          AND EXISTS (SELECT 1 FROM tax_cloud_tiifs.data_etax_cn_cit_audit_result a
            WHERE a.is_del=0 AND a.nsrsbh=d.nsrsbh
              AND a.nyear=extract(year FROM d.period_start) AND a.file_id IS NOT NULL)
      ), ranked AS (
        SELECT *,row_number() OVER(PARTITION BY year ORDER BY nsrsbh) AS rank FROM matched
      ) SELECT nsrsbh,year FROM ranked WHERE rank<=%s ORDER BY year,nsrsbh
    """,
        (per_year,),
    ).fetchall()
    samples = []
    for pair in cohort:
        declarations = conn.execute(
            """
          SELECT id,nsrsbh,period_start,period_end,yysr,lrze,ynssde,sjynsdse,file_id,
            count(*) OVER() AS candidate_count
          FROM tax_cloud_tiifs.data_etax_cn_cit_a100000
          WHERE is_del=0 AND nsrsbh=%s AND period_start=make_date(%s,1,1)
            AND period_end=make_date(%s,12,31)
          ORDER BY update_time DESC NULLS LAST,create_time DESC NULLS LAST,id DESC LIMIT 1
        """,
            (pair["nsrsbh"], pair["year"], pair["year"]),
        ).fetchone()
        assert declarations is not None
        report = conn.execute(
            """
          SELECT file_id,max(update_time) AS updated_at,count(*) OVER() AS candidate_count
          FROM tax_cloud_tiifs.data_etax_cn_cit_audit_result
          WHERE is_del=0 AND nsrsbh=%s AND nyear=%s AND file_id IS NOT NULL
          GROUP BY file_id ORDER BY max(update_time) DESC NULLS LAST,file_id DESC LIMIT 1
        """,
            (pair["nsrsbh"], pair["year"]),
        ).fetchone()
        assert report is not None
        factors = conn.execute(
            """
          SELECT id,file_id,factor_ref,value_current,value_prior,
            value_status_current,value_status_prior,review_status,decision_current
          FROM tax_cloud_tiifs.data_etax_cn_cit_audit_result
          WHERE is_del=0 AND nsrsbh=%s AND nyear=%s AND file_id=%s
            AND factor_ref=ANY(%s) ORDER BY factor_ref,id LIMIT 101
        """,
            (pair["nsrsbh"], pair["year"], report["file_id"], list(FACTORS)),
        ).fetchall()
        if len(factors) > 100:
            raise ValueError("audit factor budget exceeded")
        file = conn.execute(
            """
          SELECT source_format FROM tax_cloud_tiifs.data_etax_cn_cit_audit_file
          WHERE id=%s AND is_del=0
        """,
            (report["file_id"],),
        ).fetchone()
        lines = conn.execute(
            """
          SELECT id,hc,je FROM tax_cloud_tiifs.data_etax_cn_cit_a101010
          WHERE is_del=0 AND nsrsbh=%s AND period_start=%s AND period_end=%s
            AND file_id=%s ORDER BY hc,id LIMIT 501
        """,
            (
                pair["nsrsbh"],
                declarations["period_start"],
                declarations["period_end"],
                declarations["file_id"],
            ),
        ).fetchall()
        if len(lines) > 500:
            raise ValueError("declaration line budget exceeded")
        samples.append(
            {
                "pair": pair,
                "declaration": declarations,
                "report": report,
                "factors": factors,
                "file": file,
                "lines": lines,
            }
        )
    if not samples:
        raise ValueError("no matched annual declaration/audit samples")
    return samples


def sanitized_rows(
    samples: list[dict[str, Any]], key: bytes, batch: str
) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "sample_taxpayer",
            "sample_declaration",
            "sample_declaration_line",
            "sample_audit_report",
            "sample_audit_factor",
            "sample_mock_review",
        )
    }
    taxpayers = set()
    for sample in samples:
        pair, declaration, report = sample["pair"], sample["declaration"], sample["report"]
        taxpayer = pseudonym(key, "company", pair["nsrsbh"])
        declaration_id = pseudonym(key, "return", declaration["id"])
        # A file and accounting year jointly identify a report context.
        report_id = pseudonym(key, "report", f"{report['file_id']}:{pair['year']}")
        common = {"tenant_id": "tenant-a", "import_id": batch}
        if taxpayer not in taxpayers:
            rows["sample_taxpayer"].append(
                {**common, "id": taxpayer, "name": f"样本企业 {len(taxpayers) + 1:02d}"}
            )
            taxpayers.add(taxpayer)
        rows["sample_declaration"].append(
            {
                **common,
                "id": declaration_id,
                "taxpayer_id": taxpayer,
                "tax_year": pair["year"],
                "period_start": declaration["period_start"],
                "period_end": declaration["period_end"],
                "revenue": declaration["yysr"],
                "total_profit": declaration["lrze"],
                "taxable_income": declaration["ynssde"],
                "income_tax": declaration["sjynsdse"],
                "source_row": Jsonb(
                    {
                        k: None if declaration[k] is None else str(declaration[k])
                        for k in (
                            "period_start",
                            "period_end",
                            "yysr",
                            "lrze",
                            "ynssde",
                            "sjynsdse",
                        )
                    }
                ),
            }
        )
        for line in sample["lines"]:
            rows["sample_declaration_line"].append(
                {
                    **common,
                    "id": pseudonym(key, "line", line["id"]),
                    "declaration_id": declaration_id,
                    "line_number": line["hc"],
                    "amount": line["je"],
                }
            )
        rows["sample_audit_report"].append(
            {
                **common,
                "id": report_id,
                "taxpayer_id": taxpayer,
                "tax_year": pair["year"],
                "source_format": sample["file"]["source_format"] if sample["file"] else None,
                "declaration_id": declaration_id,
                "declaration_candidates": declaration.get("candidate_count"),
                "report_candidates": report.get("candidate_count"),
            }
        )
        for factor in sample["factors"]:
            # Numeric factors only: unexpected text is not copied into a public demo surface.
            def safe(v: object) -> str | None:
                return str(v) if v is not None and NUMERIC.fullmatch(str(v)) else None

            rows["sample_audit_factor"].append(
                {
                    **common,
                    "id": pseudonym(key, "factor", factor["id"]),
                    "report_id": report_id,
                    "factor_ref": factor["factor_ref"],
                    "value_current": safe(factor["value_current"]),
                    "value_prior": safe(factor["value_prior"]),
                    "value_status_current": factor["value_status_current"],
                    "value_status_prior": factor["value_status_prior"],
                    "numeric_current": numeric_value(
                        factor["value_current"], factor["value_status_current"]
                    ),
                    "source_review_status": factor.get("review_status"),
                    "decision_current": factor.get("decision_current"),
                }
            )
        rows["sample_mock_review"].append(
            {
                "tenant_id": "tenant-a",
                "report_id": report_id,
                "review_status": ("PENDING", "READY", "ON_HOLD")[
                    int(hashlib.sha256(report_id.encode()).hexdigest()[:4], 16) % 3
                ],
                "mocked": True,
            }
        )
    return rows


def write_samples(
    conn: psycopg.Connection[Any], rows: dict[str, list[dict[str, Any]]], manifest: dict[str, Any]
) -> None:
    conn.execute(DDL)
    conn.execute(
        "INSERT INTO sample_import VALUES(%s,%s,%s)",
        (manifest["id"], manifest["imported_at"], Jsonb(manifest)),
    )
    for table, records in rows.items():
        for record in records:
            fields = list(record)
            keys = (
                ("tenant_id", "report_id") if table == "sample_mock_review" else ("tenant_id", "id")
            )
            statement = sql.SQL(
                "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}"
            ).format(
                sql.Identifier(table),
                sql.SQL(",").join(map(sql.Identifier, fields)),
                sql.SQL(",").join(sql.Placeholder() for _ in fields),
                sql.SQL(",").join(map(sql.Identifier, keys)),
                sql.SQL(",").join(
                    sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(f), sql.Identifier(f))
                    for f in fields
                    if f not in keys
                ),
            )
            conn.execute(statement, tuple(record.values()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-year", type=int, default=6)
    parser.add_argument("--private-dir", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.per_year <= 25:
        parser.error("per-year must be 1..25")
    destination = local_dsn(os.environ["SEMALOOM_SAMPLE_DATABASE_URL"])
    private = args.private_dir.resolve()
    repo = Path(__file__).resolve().parents[2]
    if not private.is_relative_to(repo / ".agents"):
        parser.error("private-dir must be inside this project .agents directory")
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    keyfile = private / "pseudonym.key"
    if not keyfile.exists():
        with keyfile.open("xb") as stream:
            os.chmod(keyfile, 0o600)
            stream.write(secrets.token_bytes(32))
    key = keyfile.read_bytes()
    if os.environ["REMOTE_DEV_DATABASE"] != "tipdevrds":
        parser.error("expected remote-dev database tipdevrds")
    with psycopg.connect(
        host=os.environ["REMOTE_DB_HOST"],
        port=os.environ["REMOTE_DB_PORT"],
        user=os.environ["REMOTE_DB_USER"],
        password=os.environ["REMOTE_DB_PASSWORD"],
        dbname=os.environ["REMOTE_DEV_DATABASE"],
        connect_timeout=8,
        sslmode="prefer",
        row_factory=dict_row,
    ) as source:
        source.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        source.execute("SET LOCAL statement_timeout='20s'")
        samples = read_samples(source, args.per_year)
    batch = uuid.uuid4().hex
    rows = sanitized_rows(samples, key, batch)
    manifest = {
        "id": batch,
        "imported_at": datetime.now(UTC).isoformat(),
        "source": "remote-dev",
        "database": "tipdevrds",
        "schema": SCHEMA,
        "tables": [
            "data_etax_cn_cit_a100000",
            "data_etax_cn_cit_a101010",
            "data_etax_cn_cit_audit_file",
            "data_etax_cn_cit_audit_result",
        ],
        "selection": (
            "2024/2025 annual returns; exact taxpayer/year match; latest updated row "
            "and report file, ID tie-break; not business authority"
        ),
        "counts": {name: len(records) for name, records in rows.items()},
        "cohort_pairs": len(samples),
        "years": sorted({s["pair"]["year"] for s in samples}),
        "declaration_candidates": sum(s["declaration"]["candidate_count"] for s in samples),
        "audit_file_candidates": sum(s["report"]["candidate_count"] for s in samples),
        "pseudonym_key_fingerprint": hashlib.sha256(key).hexdigest(),
        "source_rows_in_git": False,
        "api": "synthetic workflow only; not remote review status",
    }
    with psycopg.connect(destination, connect_timeout=5) as target:
        write_samples(target, rows, manifest)
        target.execute((repo / "examples/financial-review/integration/review-view.sql").read_text())
    path = private / f"import-{batch}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    os.chmod(path, 0o600)
    print(
        json.dumps(
            {"counts": manifest["counts"], "years": manifest["years"], "manifest": str(path)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

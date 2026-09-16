"""Sample preparation guards tested entirely with invented records."""

from __future__ import annotations

import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "sample_import", Path(__file__).resolve().parents[1] / "ops/data/import_remote_dev.py"
)
assert spec and spec.loader
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user@remote.example/semaloom_samples",
        "postgresql://user@127.0.0.1/tipdevrds",
        "postgresql://user@127.0.0.1/semaloom_samples?hostaddr=192.0.2.1",
        "dbname=semaloom_samples service=external",
    ],
)
def test_destination_cannot_be_remote_or_source_database(url: str) -> None:
    with pytest.raises(ValueError):
        importer.local_dsn(url)


def test_sanitization_preserves_decimal_missingness_and_related_identity() -> None:
    declaration = {
        "id": "raw-return",
        "period_start": date(2024, 1, 1),
        "period_end": date(2024, 12, 31),
        "yysr": Decimal("1234567890.1234"),
        "lrze": None,
        "ynssde": Decimal("0"),
        "sjynsdse": Decimal("-0.01"),
    }
    factors = [
        {
            "id": str(index),
            "factor_ref": "income_statement.total_profit",
            "value_current": value,
            "value_prior": "99.10",
            "value_status_current": status,
            "value_status_prior": "observed",
        }
        for index, (value, status) in enumerate(
            [
                ("0", "observed"),
                ("0", "not_disclosed"),
                ("0", "extraction_failed"),
                ("private company text", "observed"),
                ("99999999999.1234", "observed"),
            ]
        )
    ]
    sample = {
        "pair": {"nsrsbh": "raw-taxpayer", "year": 2024},
        "declaration": declaration,
        "report": {"file_id": "raw-file"},
        "file": {"source_format": "pdf"},
        "factors": factors,
        "lines": [{"id": "raw-line", "hc": "1", "je": Decimal("10.01")}],
    }
    first = importer.sanitized_rows([sample], b"synthetic-test-key", "batch1")
    second = importer.sanitized_rows([sample], b"synthetic-test-key", "batch2")
    report = first["sample_audit_report"][0]
    assert report["declaration_id"] == first["sample_declaration"][0]["id"]
    assert report["taxpayer_id"] == first["sample_taxpayer"][0]["id"]
    assert first["sample_declaration_line"][0]["declaration_id"] == report["declaration_id"]
    assert first["sample_declaration"][0]["revenue"] == Decimal("1234567890.1234")
    assert first["sample_declaration"][0]["total_profit"] is None
    values = first["sample_audit_factor"]
    assert [f["numeric_current"] for f in values] == [
        Decimal("0"),
        None,
        None,
        None,
        Decimal("99999999999.1234"),
    ]
    assert values[1]["value_status_current"] == "not_disclosed"
    assert values[2]["value_status_current"] == "extraction_failed"
    assert values[3]["value_current"] is None
    assert first["sample_mock_review"] == second["sample_mock_review"]
    assert all(row["mocked"] for row in first["sample_mock_review"])
    assert "raw-taxpayer" not in repr(first) and "raw-file" not in repr(first)

from __future__ import annotations

from pathlib import Path

from semaloom.checks.field_alias import collect_field_alias_uses
from semaloom.core.semantic_query import EvidenceTable, QueryResult
from semaloom.core.wire import wire_config


def test_shipped_package_has_no_field_alias_constructors() -> None:
    from semaloom.checks.static import repo_root

    assert collect_field_alias_uses(repo_root() / "src" / "semaloom") == []


def test_collect_field_alias_uses_finds_explicit_alias(tmp_path: Path) -> None:
    (tmp_path / "model.py").write_text(
        "from pydantic import Field\n\nname: str = Field(alias='displayName')\n",
        encoding="utf-8",
    )
    found = collect_field_alias_uses(tmp_path)
    assert len(found) == 1
    assert found[0].alias == "displayName"


def test_query_result_python_constructor_and_camel_json_round_trip() -> None:
    result = QueryResult(
        result_id="r1",
        plan_id="p1",
        release_digest="d1",
        values=(),
        scope={},
        mapping_fields=(),
        evidence=EvidenceTable(columns=(), rows=()),
    )
    dumped = result.model_dump(mode="json", by_alias=True)
    assert dumped["resultId"] == "r1"
    assert dumped["planId"] == "p1"
    assert dumped["releaseDigest"] == "d1"
    assert dumped["mappingFields"] == []
    restored = QueryResult.model_validate(dumped)
    assert restored.result_id == "r1"


def test_wire_config_generates_camel_aliases() -> None:
    assert QueryResult.model_fields["result_id"].alias == "resultId"
    assert wire_config()["populate_by_name"] is True
    assert wire_config()["validate_by_name"] is True

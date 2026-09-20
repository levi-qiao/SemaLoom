"""User-confirmed scope and evidence-bound presentation across domains."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from semaloom.app.bootstrap import compile_examples
from semaloom.app.chat.presentation import project_browser_answer
from semaloom.app.chat.summary import evidence_summary
from semaloom.app.chat.tools import SemanticTools
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService
from semaloom.sdk import compile_paths


def answer() -> dict[str, Any]:
    return {
        "query": {"groupBy": [{"id": "supplierId"}]},
        "evidence": [
            {
                "id": "e1",
                "tool": "prepare_semantic_query",
                "result": {
                    "values": [
                        {
                            "metric": "procurement.orderAmount",
                            "aggregation": "SUM",
                            "grain": {"supplierId": supplier},
                            "value": value,
                            "unit": "CNY",
                        }
                        for supplier, value in (
                            ("S-1", "120.5000"),
                            ("S-2", None),
                            ("S-3", "90.0000"),
                        )
                    ],
                },
            }
        ],
    }


def test_model_selects_view_without_changing_values() -> None:
    source = answer()
    source["views"] = [{"evidenceId": "e1", "view": "table"}]
    before = deepcopy(source)
    bundle = compile_examples()
    report = project_browser_answer(source, bundle)["presentation"]["reports"][0]
    assert report["preferredView"] == "table"
    assert report["availableViews"] == ["table", "bar"]
    assert report["rows"][1]["c1"] is None
    assert source == before
    source["views"] = [{"evidenceId": "e1", "view": "bar"}]
    report = project_browser_answer(source, bundle)["presentation"]["reports"][0]
    assert report["preferredView"] == "bar"
    source["views"] = [{"evidenceId": "e1", "view": "none"}]
    projected = project_browser_answer(source, bundle)
    assert not projected["presentation"]["reports"]
    assert projected["evidence"][0]["result"]["values"] == before["evidence"][0]["result"]["values"]


def test_business_labels_replace_identity_values_in_human_results() -> None:
    source = answer()
    for index, value in enumerate(source["evidence"][0]["result"]["values"], start=1):
        value["labels"] = {"supplierId": f"供应商 {index}"}
    bundle = compile_examples()
    projected = project_browser_answer(source, bundle)
    report = projected["presentation"]["reports"][0]
    human_rows = str(report["rows"])
    assert "供应商 1" in human_rows
    assert "S-1" not in human_rows


def test_unsupported_visual_does_not_invent_a_time_axis_or_mix_units() -> None:
    source = answer()
    source["views"] = [{"evidenceId": "e1", "view": "line"}]
    bundle = compile_examples()
    report = project_browser_answer(source, bundle)["presentation"]["reports"][0]
    assert report["preferredView"] != "line"
    source["evidence"][0]["result"]["values"].append(
        {
            "metric": "procurement.orderQuantity",
            "aggregation": "SUM",
            "grain": {"supplierId": "S-1"},
            "value": "8",
            "unit": "EA",
        }
    )
    report = project_browser_answer(source, bundle)["presentation"]["reports"][0]
    assert report["availableViews"] == ["table"]
    assert report["preferredView"] == "table"


def test_relationships_are_optional_and_only_use_returned_definitions() -> None:
    bundle = compile_examples()
    definitions = [
        doc.model_dump(mode="json", by_alias=True) for doc in (*bundle.object_types, *bundle.links)
    ]
    source = {"evidence": [{"id": "e1", "result": {"definitions": definitions}}]}
    assert "presentation" not in project_browser_answer(source, bundle)
    source["views"] = [{"evidenceId": "e1", "view": "relationships"}]
    result = project_browser_answer(source, bundle)
    assert result["presentation"]["relationships"][0]["edges"]
    source["evidence"][0]["result"]["definitions"] = [
        doc for doc in definitions if doc["kind"] == "Link"
    ]
    assert "presentation" not in project_browser_answer(source, bundle)


def test_model_cannot_attach_views_to_unselected_evidence() -> None:
    bundle = compile_examples()
    tools = SemanticTools(
        QueryService(bundle, None),
        RequestActor(tenant="tenant-a", subject="test", roles=("analyst",)),
    )  # type: ignore[arg-type]
    evidence = tools.call("list_semantics", {})
    with pytest.raises(ValueError, match="UNKNOWN_PRESENTATION_REFERENCE"):
        tools.call(
            "present_answer",
            {
                "kind": "explanation",
                "text": "Definitions",
                "evidenceIds": [evidence["evidenceId"]],
                "views": [{"evidenceId": "forged", "view": "bar"}],
            },
        )
    tools.call(
        "present_answer",
        {
            "kind": "explanation",
            "text": "Definitions",
            "evidenceIds": [evidence["evidenceId"]],
            "views": [{"evidenceId": evidence["evidenceId"], "view": "relationships"}],
        },
    )
    assert tools.answer is not None
    assert tools.answer["views"][0]["view"] == "relationships"


def test_object_answers_hide_machine_identifiers_from_human_layers() -> None:
    root = Path(__file__).resolve().parents[1] / "examples/financial-review"
    bundle = compile_paths([root]).bundle
    assert bundle is not None
    evidence = [
        {
            "id": "e1",
            "tool": "find_objects",
            "result": {
                "objectType": "finance.TaxReturn",
                "objects": [
                    {
                        "identity": {"returnId": "return-secret-1"},
                        "properties": {
                            "returnId": "return-secret-1",
                            "companyId": "company-secret-1",
                            "taxYear": "2024",
                            "revenue": "1200.0000",
                        },
                    },
                    {
                        "identity": {"returnId": "return-secret-2"},
                        "properties": {
                            "returnId": "return-secret-2",
                            "companyId": "company-secret-2",
                            "taxYear": "2025",
                            "revenue": "1300.0000",
                        },
                    },
                ],
                "hasMore": False,
            },
        }
    ]
    text = evidence_summary(evidence, bundle=bundle)
    assert "return-secret" not in text
    assert "company-secret" not in text
    assert "年度：2024" in text  # noqa: RUF001

    projected = project_browser_answer({"evidence": evidence}, bundle)
    report = projected["presentation"]["reports"][0]
    assert all("编号" not in column["label"] for column in report["columns"])
    assert all("Id" not in column["semanticId"] for column in report["columns"])

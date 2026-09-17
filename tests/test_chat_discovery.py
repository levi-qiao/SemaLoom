"""Discovery answers use release definitions, not fabricated business observations."""

from semaloom.app.bootstrap import compile_examples
from semaloom.app.chat.tools import SemanticTools
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService

ACTOR = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))


def test_definition_evidence_can_finish_a_catalog_question() -> None:
    tools = SemanticTools(QueryService(compile_examples(), None), ACTOR, "我们有什么数据可问答?")
    definition = tools.call("describe_semantic", {"semanticId": "tax.Taxpayer"})
    tools.call(
        "present_answer",
        {
            "kind": "answer",
            "text": "可以围绕本体中的纳税人对象提问。",
            "evidenceIds": [definition["evidenceId"]],
        },
    )
    assert tools.answer is not None
    assert tools.answer["kind"] == "explanation"
    assert tools.answer["textOrigin"] == "AI"


def test_link_and_metric_discovery_exposes_collection_join_boundary() -> None:
    tools = SemanticTools(QueryService(compile_examples(), None), ACTOR)
    link = tools.call("describe_semantic", {"semanticId": "tax.filingTaxpayer"})
    assert link["kind"] == "Link"
    assert link["analysisCapabilities"] == {
        "pointLookup": False,
        "keyedFind": True,
        "collectionJoin": False,
    }
    assert "physical" not in link and "sourceId" not in link
    metric = tools.call("describe_semantic", {"semanticId": "tax.reportedIncome"})
    assert metric["kind"] == "Metric"
    assert metric["analysisCapabilities"]["collectionJoin"] is False
    assert "sameTableCollection" in metric["analysisCapabilities"]
    page = tools.call("list_semantics", {"limit": 50})
    kinds = {item["kind"] for item in page["definitions"]}
    assert "Link" in kinds and "Metric" in kinds
    assert not {"Mapping", "Source"} & kinds
    for item in page["definitions"]:
        if item["kind"] in {"Link", "Metric"}:
            assert "collectionJoin" in item["analysisCapabilities"]
            assert item["analysisCapabilities"]["collectionJoin"] in {True, False}
        else:
            assert "analysisCapabilities" not in item
    listed = next(item for item in page["definitions"] if item["id"] == "tax.filingTaxpayer")
    assert listed["analysisCapabilities"]["pointLookup"] is False


def test_catalog_pages_are_complete_release_pinned_and_business_only() -> None:
    tools = SemanticTools(QueryService(compile_examples(), None), ACTOR)
    found = []
    offset = 0
    while True:
        page = tools.call("list_semantics", {"offset": offset, "limit": 5})
        assert page["releaseDigest"] == tools.query.bundle.digest
        assert page["scope"] == "DECLARED_MODEL_NOT_SOURCE_OBSERVATIONS"
        found.extend(page["definitions"])
        if not page["hasMore"]:
            assert page["nextOffset"] is None
            break
        offset = page["nextOffset"]
    ids = [item["id"] for item in found]
    assert ids == sorted(set(ids))
    assert "tax.Taxpayer" in ids
    assert not {"Mapping", "Source"} & {item["kind"] for item in found}


def test_catalog_requires_discovery_authority_and_typed_bounded_paging() -> None:
    import pytest

    tools = SemanticTools(QueryService(compile_examples(), None), ACTOR)
    for args in ({"limit": 0}, {"limit": 51}, {"offset": -1}, {"offset": True}, {"offset": "1"}):
        with pytest.raises(ValueError):
            tools.call("list_semantics", args)
    guest = RequestActor(tenant="tenant-a", subject="guest", roles=("guest",))
    tools = SemanticTools(tools.query, guest)
    with pytest.raises(PermissionError):
        tools.call("list_semantics", {})


def test_explanations_cannot_replace_requested_computations() -> None:
    import pytest

    tools = SemanticTools(QueryService(compile_examples(), None), ACTOR, "2025年平均值是多少?")
    definitions = tools.call("list_semantics", {})
    with pytest.raises(ValueError, match="SEMANTIC_ANALYSIS_REQUIRED"):
        tools.call(
            "present_answer",
            {
                "kind": "explanation",
                "text": "平均值是123。",
                "evidenceIds": [definitions["evidenceId"]],
            },
        )
    assert tools.answer is None


def test_explanations_require_real_definition_evidence() -> None:
    import pytest

    tools = SemanticTools(QueryService(compile_examples(), None), ACTOR)
    with pytest.raises(ValueError, match="EVIDENCE_REQUIRED"):
        tools.call("present_answer", {"kind": "explanation", "text": "说明", "evidenceIds": []})
    with pytest.raises(ValueError, match="UNKNOWN_EVIDENCE_REFERENCE"):
        tools.call("present_answer", {"kind": "explanation", "text": "说明", "evidenceIds": ["e9"]})


def test_studio_entry_point_revalidates_after_rebuild() -> None:
    from fastapi.testclient import TestClient

    from semaloom.app.factory import _mount_studio, create_app

    app = create_app(load_services=False)
    _mount_studio(app)
    response = TestClient(app).get("/studio/?view=graph")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"

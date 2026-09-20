"""Harness boundary tests. No provider key, model call or real business data required."""

# ruff: noqa: RUF001 -- fixtures intentionally exercise Chinese localized copy.

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from semaloom.app.bootstrap import build_services
from semaloom.app.chat.i18n import localize_question, message_locale, normalize_locale
from semaloom.app.chat.service import ChatService
from semaloom.app.chat.store import ChatStore
from semaloom.app.chat.tools import SemanticTools
from semaloom.app.factory import create_app
from semaloom.core.results import MetricSelect
from semaloom.runtime.auth import RequestActor

ACTOR = RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))


def test_chat_locale_normalization() -> None:
    assert normalize_locale("en-US,en;q=0.9") == "en"
    assert normalize_locale("zh_Hans-CN") == "zh-CN"
    assert normalize_locale("fr-FR") == "zh-CN"
    assert message_locale("Show annual revenue", "zh-CN") == "en"
    assert message_locale("请查询年度收入", "en-US") == "zh-CN"
    assert message_locale("2025", "en-US") == "en"


def test_choice_copy_localizes_without_changing_semantic_payload() -> None:
    question = {
        "slot": "aggregation",
        "prompt": "希望如何统计这个指标？",
        "reason": "合计和平均值等计算含义不同，需要明确。",
        "options": [
            {
                "id": "opt_agg_SUM",
                "label": "合计",
                "explanation": "合计（按当前筛选范围）",
                "choice": {"kind": "AGGREGATION", "id": "SUM"},
            }
        ],
    }
    localized = localize_question(question, "en-US")
    assert localized is not None
    assert localized["prompt"] == "How should this metric be calculated?"
    assert localized["options"][0]["label"] == "Total"  # type: ignore[index]
    assert localized["options"][0]["choice"] == question["options"][0]["choice"]  # type: ignore[index]


@pytest.fixture
def services() -> Any:
    service = build_services(load_data=True)
    yield service
    service.close()


def test_semantic_plugin_rejects_guessed_ids_and_forged_evidence(services: Any) -> None:
    tools = SemanticTools(services.query_active("tenant-a"), ACTOR)
    with pytest.raises(ValueError, match="RESOLVE_IDENTITY"):
        tools._metric_identity(
            MetricSelect(metric="tax.reportedIncome", bindings={"taxpayerId": "TAXPAYER-A"})
        )
    with pytest.raises(ValueError, match="UNKNOWN_EVIDENCE"):
        tools.call("present_answer", {"kind": "answer", "text": "invented", "evidenceIds": ["e9"]})
    with pytest.raises(ValueError, match="EVIDENCE_REQUIRED"):
        tools.call("present_answer", {"kind": "answer", "text": "invented", "evidenceIds": []})
    found = tools.call(
        "find_objects", {"objectType": "tax.Taxpayer", "filters": {"taxpayerId": "TAXPAYER-A"}}
    )
    assert found["objects"][0]["identity"] == {"taxpayerId": "TAXPAYER-A"}
    result = tools.call(
        "semantic_query",
        {
            "apiVersion": "semaloom/v0.1",
            "select": [
                {
                    "metric": "tax.reportedIncome",
                    "bindings": {"taxpayerId": "TAXPAYER-A", "taxYear": 2024},
                }
            ],
            "context": {"businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"}},
        },
    )
    assert result["observations"][0]["value"] == "110.1000"
    assert tools.call(
        "present_answer",
        {"kind": "answer", "text": "依据见事实卡", "evidenceIds": [result["evidenceId"]]},
    )["accepted"]
    assert tools.answer["evidence"][0]["result"]["observations"][0]["value"] == "110.1000"


def test_store_actor_isolation_and_optimistic_history(services: Any) -> None:
    store = ChatStore(services.studio_drafts.engine)
    row = store.create(ACTOR, services.bundle.digest)
    for actor in [
        RequestActor(tenant="tenant-b", subject="alice", roles=("analyst",)),
        RequestActor(tenant="tenant-a", subject="other", roles=("analyst",)),
    ]:
        with pytest.raises(KeyError):
            store.load(actor, row["id"])
    store.save(ACTOR, row, [], {"question": "hi", "answer": {"text": "hello"}})
    assert len(store.load(ACTOR, row["id"])["turns"]) == 1
    with pytest.raises(ValueError, match="CONVERSATION_CONFLICT"):
        store.save(ACTOR, row, [], {"question": "stale"})


WORKER = """import {createInterface} from 'node:readline';
const io=createInterface({input:process.stdin});
const emit=x=>console.log(JSON.stringify(x));
let state;
io.on('line',line=>{
 const p=JSON.parse(line);
 if(p.type==='start') {state=p;emit({type:'call',id:'1',name:'find_objects',
 args:{objectType:'tax.Taxpayer',filters:{taxpayerId:'TAXPAYER-A'}}});}
 else if(p.id==='1') emit({type:'call',id:'2',name:'semantic_query',
 args:{apiVersion:'semaloom/v0.1',select:[{metric:'tax.reportedIncome',
 bindings:{taxpayerId:'TAXPAYER-A',taxYear:2024}}],
 context:{businessPeriod:{from:'2024-01-01',to:'2025-01-01'}}}});
 else if(p.id==='2') emit({type:'call',id:'3',name:'present_answer',
 args:{kind:'answer',text:'事实来自引擎',evidenceIds:[p.payload.evidenceId]}});
 else emit({type:'complete',history:[]});
});
"""


@pytest.fixture
def client(tmp_path: Path, services: Any) -> Any:
    config = tmp_path / "provider.json"
    config.write_text(
        json.dumps({"apiKey": "test-private-key", "baseUrl": "https://example.invalid/v1"})
    )
    worker = tmp_path / "worker.mjs"
    worker.write_text(WORKER)
    (tmp_path / "node_modules/@earendil-works/pi-agent-core").mkdir(parents=True)
    app = create_app(load_services=False)
    app.state.services = services
    from semaloom.app.chat.http import router
    from semaloom.app.http import router as main_router

    app.include_router(main_router)
    app.include_router(router)
    app.state.chat = ChatService(ChatStore(services.studio_drafts.engine), config)
    app.state.chat.worker = worker
    with TestClient(app) as test_client:
        yield test_client


def test_http_stream_history_and_no_key_exposure(client: TestClient) -> None:
    headers = {"Authorization": "Bearer tenant-a-analyst"}
    response = client.post("/v0.1/chat/turns", headers=headers, json={"message": "申报收入明细?"})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done", events
    assert (
        next(e for e in events if e["type"] == "answer")["answer"]["evidence"][0]["result"][
            "observations"
        ][0]["value"]
        == "110.1000"
    )
    cid = events[0]["conversationId"]
    history = client.get("/v0.1/chat/conversations/" + cid, headers=headers)
    assert len(history.json()["turns"]) == 1
    assert (
        "test-private-key"
        not in response.text + history.text + client.get("/v0.1/chat/status", headers=headers).text
    )
    assert (
        client.get(
            "/v0.1/chat/conversations/" + cid,
            headers={"Authorization": "Bearer tenant-b-analyst"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v0.1/chat/turns",
            json={"message": "x"},
            headers={"Authorization": "Bearer tenant-a-model-viewer"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v0.1/chat/turns", json={"message": "x", "tenant": "tenant-b"}, headers=headers
        ).status_code
        == 422
    )


def test_jev_configuration_is_server_only_and_shadow_by_default(
    tmp_path: Path, services: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "provider.json"
    config.write_text(json.dumps({"apiKey": "chat-key", "baseUrl": "https://example.invalid/v1"}))
    monkeypatch.setenv("TYPESAFE_API_KEY", "decision-secret")
    chat = ChatService(ChatStore(services.studio_drafts.engine), config)
    status = chat.status()
    assert status["decisionProvider"] == "TypeSafe Jev"
    assert status["decisionMode"] == "shadow"
    assert "decision-secret" not in json.dumps(status)


def test_object_scope_card_uses_locale_and_ontology_labels(services: Any) -> None:
    tools = SemanticTools(services.query, ACTOR, user_message="Show records", locale="en-US")
    tools.object_scope_required = True
    tools.object_scope_type = "tax.Filing"
    result = tools._object_scope_pending()
    assert result["waiting"] is True
    assert tools.pending is not None
    question = tools.pending["question"]
    assert question["prompt"].startswith("Narrow the search scope")
    obj = next(item for item in services.bundle.object_types if item.id == "tax.Filing")
    assert (obj.label or obj.id) in question["prompt"]


def test_chat_rechecks_release_and_requires_csrf(client: TestClient) -> None:
    client.post("/v0.1/studio/session/demo", json={"persona": "studio-admin"})
    assert client.post("/v0.1/chat/turns", json={"message": "x"}).status_code == 403
    store = client.app.state.chat.store
    row = store.create(ACTOR, "old-release")
    response = client.post(
        "/v0.1/chat/turns",
        headers={"Authorization": "Bearer tenant-a-analyst"},
        json={"message": "x", "conversationId": row["id"]},
    )
    assert (
        response.status_code == 409
        and response.json()["detail"] == "RELEASE_CHANGED_START_NEW_CHAT"
    )


def test_cancelling_stream_reaps_owned_node_process(tmp_path: Path, services: Any) -> None:
    config = tmp_path / "provider.json"
    config.write_text(json.dumps({"apiKey": "test", "baseUrl": "https://example.invalid/v1"}))
    worker = tmp_path / "idle.mjs"
    worker.write_text("setInterval(()=>{},1000);")
    chat = ChatService(ChatStore(services.studio_drafts.engine), config)
    chat.worker = worker
    row = chat.store.create(ACTOR, services.bundle.digest)

    async def check() -> None:
        stream = chat.stream(row, "hello", services.query, ACTOR, lambda: None)
        first = await anext(stream)
        assert json.loads(first)["type"] == "start"
        assert len(chat.processes) == 1
        process = next(iter(chat.processes))
        await stream.aclose()
        assert process.returncode is not None and not chat.processes and not chat.busy

    asyncio.run(check())


def test_query_hook_executes_covered_claim_in_the_python_rule_engine(services: Any) -> None:
    tools = SemanticTools(services.query, ACTOR)
    tools.call(
        "find_objects", {"objectType": "tax.Taxpayer", "filters": {"taxpayerId": "TAXPAYER-A"}}
    )
    result = tools.call(
        "semantic_query",
        {
            "apiVersion": "semaloom/v0.1",
            "select": [
                {
                    "metric": "tax.adjustmentAmount",
                    "bindings": {"taxpayerId": "TAXPAYER-A", "taxYear": 2024},
                }
            ],
            "context": {
                "businessPeriod": {"from": "2024-01-01", "to": "2025-01-01"},
                "scope": {"jurisdiction": "CN"},
            },
        },
    )
    checks = result["checks"]
    assert len(checks) == 1
    assert checks[0]["claim"]["claimId"] == "tax.incomeReconciles"
    assert checks[0]["claim"]["truth"] == "TRUE"
    assert checks[0]["claim"]["evidenceRefs"]
    assert {a["activityId"] for a in checks[0]["sourceActivities"]} == set(
        checks[0]["claim"]["evidenceRefs"]
    )


def test_save_failure_has_its_own_error_and_never_reports_success(
    client: TestClient, monkeypatch: Any
) -> None:
    def fail(*args: Any) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(client.app.state.chat.store, "save", fail)
    response = client.post(
        "/v0.1/chat/turns",
        headers={"Authorization": "Bearer tenant-a-analyst"},
        json={"message": "申报收入明细?"},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1] == {"type": "error", "code": "CHAT_HISTORY_SAVE_FAILED"}
    assert not any(e["type"] in {"answer", "done"} for e in events)


def test_discovery_explanation_crosses_http_and_survives_history_reload(client: TestClient) -> None:
    client.app.state.chat.worker.write_text("""import {createInterface} from 'node:readline';
const io=createInterface({input:process.stdin});
const emit=x=>console.log(JSON.stringify(x));
io.on('line',line=>{
 const p=JSON.parse(line);
 if(p.type==='start') emit({type:'call',id:'1',name:'list_semantics',args:{limit:50}});
 else if(p.id==='1') emit({type:'call',id:'2',name:'present_answer',
 args:{kind:'explanation',text:'可围绕当前本体定义提问。数据可用性尚未查询。',
 evidenceIds:[p.payload.evidenceId]}});
 else emit({type:'complete',history:[]});
});
""")
    headers = {"Authorization": "Bearer tenant-a-analyst"}
    response = client.post(
        "/v0.1/chat/turns", headers=headers, json={"message": "我们有什么数据可问答?"}
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done", events
    answer = next(event["answer"] for event in events if event["type"] == "answer")
    assert answer["kind"] == "explanation"
    assert answer["textOrigin"] == "AI"
    assert answer["evidence"][0]["result"]["definitions"]
    cid = events[0]["conversationId"]
    history = client.get("/v0.1/chat/conversations/" + cid, headers=headers).json()
    assert history["turns"][0]["answer"] == answer


def test_list_conversations_and_continue_conversation(client: TestClient) -> None:
    headers = {"Authorization": "Bearer tenant-a-analyst"}
    # 1. First turn direct calculation
    res1 = client.post("/v0.1/chat/turns", headers=headers, json={"message": "采购订单总额合计"})
    events1 = [json.loads(line) for line in res1.text.splitlines() if line.strip()]
    assert events1[-1]["type"] == "done"
    cid = events1[0]["conversationId"]

    # 2. Check conversation listing includes this conversation
    listing = client.get("/v0.1/chat/conversations", headers=headers)
    assert listing.status_code == 200
    conversations = listing.json()["conversations"]
    assert any(c["id"] == cid and c["turnCount"] == 1 for c in conversations)

    # 3. Continue conversation in the same session
    res2 = client.post(
        "/v0.1/chat/turns",
        headers=headers,
        json={"message": "各区域采购额合计", "conversationId": cid},
    )
    events2 = [json.loads(line) for line in res2.text.splitlines() if line.strip()]
    assert events2[-1]["type"] == "done"
    assert events2[0]["conversationId"] == cid

    # 4. Check loaded session has both turns preserved
    detail = client.get(f"/v0.1/chat/conversations/{cid}", headers=headers).json()
    assert len(detail["turns"]) == 2
    assert detail["turns"][0]["question"] == "采购订单总额合计"
    assert detail["turns"][1]["question"] == "各区域采购额合计"

    # 5. Check listing now reflects 2 turns
    listing2 = client.get("/v0.1/chat/conversations", headers=headers).json()
    updated = next(c for c in listing2["conversations"] if c["id"] == cid)
    assert updated["turnCount"] == 2

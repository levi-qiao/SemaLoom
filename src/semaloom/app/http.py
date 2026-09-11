"""REST/MCP-style semantic API. No SQL/URL/permission request fields."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from semaloom.core.results import MetricSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.eval import EvaluationError, evaluate_named_claim
from semaloom.runtime.studio import save_draft, studio_graph, studio_inspector

router = APIRouter(prefix="/v0.1")

TOKENS: dict[str, RequestActor] = {
    "tenant-a-analyst": RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",)),
    "tenant-a-approver": RequestActor(
        tenant="tenant-a", subject="bob", roles=("approver", "analyst")
    ),
    "tenant-b-analyst": RequestActor(tenant="tenant-b", subject="carol", roles=("analyst",)),
}

FORBIDDEN_KEYS = frozenset({"sql", "url", "permissions", "table", "column", "join"})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryBody(StrictModel):
    metric: str
    bindings: dict[str, str | int]
    period_from: str = Field(alias="periodFrom")
    period_to: str = Field(alias="periodTo")


class ClaimBody(StrictModel):
    claim_id: str = Field(alias="claimId")
    bindings: dict[str, str | int]
    period_from: str = Field(alias="periodFrom")
    period_to: str = Field(alias="periodTo")
    dimensions: dict[str, str] = Field(default_factory=dict)


class ActionPlanBody(StrictModel):
    action_id: str = Field(alias="actionId")
    target: dict[str, str]
    parameters: dict[str, str]


class ActionIdBody(StrictModel):
    plan_id: str = Field(alias="planId")
    parameters: dict[str, str] | None = None


def actor_from_header(authorization: str | None) -> RequestActor:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="UNAUTHENTICATED")
    token = authorization.removeprefix("Bearer ").strip()
    actor = TOKENS.get(token)
    if actor is None:
        raise HTTPException(status_code=401, detail="UNAUTHENTICATED")
    return actor


def reject_forbidden(payload: dict[str, Any]) -> None:
    lowered = {str(key).lower() for key in payload}
    if lowered & FORBIDDEN_KEYS:
        raise HTTPException(status_code=400, detail="INVALID_REQUEST")


@router.post("/query")
def query_metric(
    body: QueryBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    reject_forbidden(body.model_dump())
    reject_forbidden(body.bindings)
    actor = actor_from_header(authorization)
    services = request.app.state.services
    envelope = services.query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(MetricSelect(metric=body.metric, bindings=body.bindings),),
            context=QueryContext(business_period={"from": body.period_from, "to": body.period_to}),
        ),
        actor,
    )
    dumped = envelope.model_dump(mode="json", by_alias=True)
    return dict(dumped)


@router.post("/claims/evaluate")
def evaluate_claim(
    body: ClaimBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_header(authorization)
    services = request.app.state.services
    try:
        claim, observations, diagnostics, digest = evaluate_named_claim(
            services.bundle,
            services.query,
            actor,
            claim_id=body.claim_id,
            bindings=body.bindings,
            period_from=body.period_from,
            period_to=body.period_to,
            dimensions=body.dimensions,
        )
    except EvaluationError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    return {
        "claim": claim.model_dump(mode="json", by_alias=True),
        "observations": [item.model_dump(mode="json", by_alias=True) for item in observations],
        "diagnostics": [item.model_dump() for item in diagnostics],
        "releaseDigest": digest,
    }


@router.post("/actions/plan")
def plan_action(
    body: ActionPlanBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_header(authorization)
    services = request.app.state.services
    plan = services.actions.plan(
        actor, action_id=body.action_id, target=body.target, parameters=body.parameters
    )
    dumped = plan.model_dump(mode="json", by_alias=True)
    return dict(dumped)


@router.post("/actions/approve")
def approve_action(
    body: ActionIdBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    actor = actor_from_header(authorization)
    services = request.app.state.services
    services.actions.approve(actor, body.plan_id)
    return {"status": "APPROVED", "planId": body.plan_id}


@router.post("/actions/execute")
def execute_action(
    body: ActionIdBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_header(authorization)
    services = request.app.state.services
    try:
        execution = services.actions.execute(actor, body.plan_id, parameters=body.parameters)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    dumped = execution.model_dump(mode="json", by_alias=True)
    return dict(dumped)


@router.get("/actions/{plan_id}")
def action_status(
    plan_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor_from_header(authorization)
    services = request.app.state.services
    execution = services.actions.status(plan_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    dumped = execution.model_dump(mode="json", by_alias=True)
    return dict(dumped)


class DraftBody(StrictModel):
    expected_revision: int = Field(alias="expectedRevision")
    payload: dict[str, Any]


@router.get("/studio/graph")
def studio_graph_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor_from_header(authorization)
    return studio_graph(request.app.state.services.bundle)


@router.get("/studio/inspector")
def studio_inspector_endpoint(
    objectId: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor_from_header(authorization)
    payload = studio_inspector(request.app.state.services.bundle, objectId)
    if payload is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return payload


@router.get("/studio/mappings")
def studio_mappings_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor_from_header(authorization)
    bundle = request.app.state.services.bundle
    return {
        "mappings": [
            {
                "id": item.id,
                "target": item.target,
                "sourceId": item.source_id,
                "provider": item.provider,
            }
            for item in bundle.mappings
        ]
    }


@router.put("/studio/drafts/{draft_id}")
def studio_save_draft(
    draft_id: str,
    body: DraftBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, int | str]:
    actor_from_header(authorization)
    try:
        revision = save_draft(
            request.app.state.services.registry.engine,
            draft_id,
            body.payload,
            body.expected_revision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"draftId": draft_id, "revision": revision}


@router.get("/mcp/tools")
def mcp_tools() -> dict[str, Any]:
    return {
        "tools": [
            {"name": "semantic_query", "input": ["metric", "bindings"]},
            {"name": "evaluate_claim", "input": ["claimId", "bindings"]},
            {"name": "plan_action", "input": ["actionId", "target", "parameters"]},
            {"name": "action_status", "input": ["planId"]},
        ]
    }

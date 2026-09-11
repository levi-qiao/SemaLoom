"""REST/MCP-style semantic API. No SQL/URL/permission request fields."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from semaloom.core.bundle import CompiledBundle
from semaloom.core.results import MetricSelect, ObjectSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor, authorize_query
from semaloom.runtime.eval import EvaluationError, evaluate_named_claim
from semaloom.runtime.registry import StaleRevision
from semaloom.runtime.source_registry import SourceRevisionConflict
from semaloom.runtime.source_validation import validate_source, validate_sources
from semaloom.runtime.studio import (
    studio_graph,
    studio_inspector,
    studio_mappings,
    studio_sources,
)
from semaloom.runtime.studio_control import DraftSnapshot, InvalidDraft, RevisionConflict
from semaloom.runtime.studio_release import ReleaseGateError

router = APIRouter(prefix="/v0.1")

SESSION_COOKIE = "semaloom_session"
CSRF_COOKIE = "semaloom_csrf"

TOKENS: dict[str, RequestActor] = {
    "tenant-a-analyst": RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",)),
    "tenant-a-approver": RequestActor(
        tenant="tenant-a", subject="bob", roles=("approver", "analyst")
    ),
    "tenant-b-analyst": RequestActor(tenant="tenant-b", subject="carol", roles=("analyst",)),
    "tenant-a-modeler": RequestActor(tenant="tenant-a", subject="dana", roles=("modeler",)),
    "tenant-b-modeler": RequestActor(tenant="tenant-b", subject="erin", roles=("modeler",)),
    "tenant-a-source-admin": RequestActor(
        tenant="tenant-a", subject="sara", roles=("source-admin",)
    ),
    "tenant-a-publisher": RequestActor(
        tenant="tenant-a", subject="pat", roles=("publisher", "model-viewer")
    ),
    "tenant-a-reviewer": RequestActor(
        tenant="tenant-a", subject="riley", roles=("reviewer", "model-viewer")
    ),
    "tenant-a-model-viewer": RequestActor(
        tenant="tenant-a", subject="victor", roles=("model-viewer",)
    ),
}

DEMO_PERSONAS: dict[str, RequestActor] = {
    "studio-admin": RequestActor(
        tenant="tenant-a",
        subject="local-studio-admin",
        roles=(
            "model-viewer",
            "modeler",
            "source-admin",
            "reviewer",
            "publisher",
            "sample-viewer",
            "analyst",
        ),
    ),
    "modeler": RequestActor(tenant="tenant-a", subject="local-modeler", roles=("modeler",)),
    "viewer": RequestActor(tenant="tenant-a", subject="local-viewer", roles=("model-viewer",)),
    "source-admin": RequestActor(
        tenant="tenant-a", subject="local-source-admin", roles=("source-admin",)
    ),
    "reviewer": RequestActor(
        tenant="tenant-a", subject="local-reviewer", roles=("reviewer", "model-viewer")
    ),
    "publisher": RequestActor(
        tenant="tenant-a", subject="local-publisher", roles=("publisher", "model-viewer")
    ),
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


def actor_from_studio_request(request: Request, authorization: str | None) -> RequestActor:
    if authorization and request.method in {"GET", "HEAD", "OPTIONS"}:
        return actor_from_header(authorization)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        detail = "SESSION_REQUIRED" if authorization else "UNAUTHENTICATED"
        raise HTTPException(status_code=401, detail=detail)
    actor = cast(RequestActor | None, request.app.state.services.sessions.resolve(token))
    if actor is None:
        raise HTTPException(status_code=401, detail="SESSION_EXPIRED")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        expected_origin = str(request.base_url).rstrip("/")
        csrf_header = request.headers.get("x-csrf-token")
        csrf_cookie = request.cookies.get(CSRF_COOKIE)
        if origin != expected_origin:
            raise HTTPException(status_code=403, detail="INVALID_ORIGIN")
        if not csrf_header or csrf_header != csrf_cookie:
            raise HTTPException(status_code=403, detail="INVALID_CSRF")
        if not request.app.state.services.sessions.verify_csrf(token, csrf_header):
            raise HTTPException(status_code=403, detail="INVALID_CSRF")
    return actor


def reject_forbidden(payload: dict[str, Any]) -> None:
    lowered = {str(key).lower() for key in payload}
    if lowered & FORBIDDEN_KEYS:
        raise HTTPException(status_code=400, detail="INVALID_REQUEST")


def require_role(actor: RequestActor, *roles: str) -> None:
    if not set(actor.roles) & set(roles):
        raise HTTPException(status_code=403, detail="FORBIDDEN")


def studio_bundle(request: Request, actor: RequestActor, draft_id: str | None) -> CompiledBundle:
    if draft_id is None:
        return cast(CompiledBundle, request.app.state.services.bundle)
    require_role(actor, "modeler")
    return cast(
        CompiledBundle,
        request.app.state.services.studio_drafts.bundle(actor.tenant, draft_id),
    )


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
    try:
        plan = services.actions.plan(
            actor, action_id=body.action_id, target=body.target, parameters=body.parameters
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    try:
        services.actions.approve(actor, body.plan_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    actor = actor_from_header(authorization)
    services = request.app.state.services
    try:
        execution = services.actions.status(actor, plan_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NOT_FOUND") from exc
    if execution is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    dumped = execution.model_dump(mode="json", by_alias=True)
    return dict(dumped)


class DraftBody(StrictModel):
    expected_revision: int = Field(alias="expectedRevision")
    documents: list[dict[str, Any]]


class SourceProfileBody(StrictModel):
    expected_revision: int = Field(alias="expectedRevision")
    label: str
    provider: str
    binding_ref: str = Field(alias="bindingRef")
    secret_ref: str | None = Field(default=None, alias="secretRef")
    settings: dict[str, Any] = Field(default_factory=dict)


class PublishBody(StrictModel):
    expected_environment_revision: int = Field(alias="expectedEnvironmentRevision")


class DemoSessionBody(StrictModel):
    persona: str = "studio-admin"


class SampleBody(StrictModel):
    object_id: str = Field(alias="objectId")
    identity: str
    properties: list[str] = Field(default_factory=list)


@router.post("/studio/session/demo")
def studio_create_demo_session(
    body: DemoSessionBody, request: Request, response: Response
) -> dict[str, Any]:
    if request.app.state.profile != "local-dev":
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    actor = DEMO_PERSONAS.get(body.persona)
    if actor is None:
        raise HTTPException(status_code=422, detail="UNKNOWN_PERSONA")
    session = request.app.state.services.sessions.create(
        tenant=actor.tenant, subject=actor.subject, roles=actor.roles
    )
    secure = request.url.scheme == "https"
    response.set_cookie(
        SESSION_COOKIE,
        session.token,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=3600,
    )
    response.set_cookie(
        CSRF_COOKIE,
        session.csrf_token,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=3600,
    )
    return {"tenant": actor.tenant, "subject": actor.subject, "roles": actor.roles}


@router.get("/studio/session")
def studio_current_session(
    request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    return {"tenant": actor.tenant, "subject": actor.subject, "roles": actor.roles}


@router.get("/studio/session/bootstrap")
def studio_session_bootstrap(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    actor = cast(
        RequestActor | None,
        None if not token else request.app.state.services.sessions.resolve(token),
    )
    if actor is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "tenant": actor.tenant,
        "subject": actor.subject,
        "roles": actor.roles,
    }


@router.delete("/studio/session")
def studio_logout(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    actor_from_studio_request(request, authorization)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        request.app.state.services.sessions.revoke(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"status": "REVOKED"}


@router.get("/studio/graph")
def studio_graph_endpoint(
    request: Request,
    draftId: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler", "model-viewer", "source-admin")
    return studio_graph(studio_bundle(request, actor, draftId))


@router.post("/studio/sample")
def studio_sample(
    body: SampleBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "sample-viewer")
    services = request.app.state.services
    active_digest = services.registry.current(services.environment)
    if active_digest is None:
        raise HTTPException(status_code=409, detail="NO_ACTIVE_RELEASE")
    bundle = services.registry.load(active_digest)
    object_type = next((item for item in bundle.object_types if item.id == body.object_id), None)
    if object_type is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    envelope = services.query_active(actor.tenant).execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                ObjectSelect(
                    object_type=body.object_id,
                    identity={object_type.identity_keys[0]: body.identity},
                    properties=tuple(body.properties),
                ),
            ),
            context=QueryContext(business_period={"from": "1970-01-01", "to": "9999-12-31"}),
        ),
        actor,
    )
    return dict(envelope.model_dump(mode="json", by_alias=True))


@router.get("/studio/inspector")
def studio_inspector_endpoint(
    objectId: str,
    request: Request,
    draftId: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler", "model-viewer", "source-admin")
    payload = studio_inspector(studio_bundle(request, actor, draftId), objectId)
    if payload is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return payload


@router.get("/studio/mappings")
def studio_mappings_endpoint(
    request: Request,
    draftId: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler", "model-viewer", "source-admin")
    return studio_mappings(studio_bundle(request, actor, draftId))


@router.get("/studio/sources")
def studio_sources_endpoint(
    request: Request,
    draftId: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler", "model-viewer", "source-admin")
    return studio_sources(studio_bundle(request, actor, draftId))


@router.get("/studio/source-profiles")
def studio_source_profiles(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "source-admin", "model-viewer", "modeler", "publisher")
    profiles = request.app.state.services.source_profiles.list(actor.tenant)
    return {"profiles": [item.to_dict() for item in profiles]}


@router.put("/studio/source-profiles/{source_id}")
def studio_save_source_profile(
    source_id: str,
    body: SourceProfileBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "source-admin")
    try:
        profile = request.app.state.services.source_profiles.save(
            tenant=actor.tenant,
            actor=actor.subject,
            source_id=source_id,
            expected_revision=body.expected_revision,
            label=body.label,
            provider=body.provider,
            binding_ref=body.binding_ref,
            secret_ref=body.secret_ref,
            settings=body.settings,
        )
    except SourceRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return cast(dict[str, Any], profile.to_dict())


@router.post("/studio/source-profiles/{source_id}/validate")
def studio_validate_source_profile(
    source_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "source-admin")
    services = request.app.state.services
    try:
        profile = services.source_profiles.get(actor.tenant, source_id)
        status, reason = validate_source(profile, services.environment_bindings)
        updated = services.source_profiles.set_validation(actor.tenant, source_id, status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NOT_FOUND") from exc
    return {**updated.to_dict(), "reason": reason}


@router.post("/studio/source-profiles/validate-all")
def studio_validate_all_source_profiles(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "source-admin")
    services = request.app.state.services
    results = []
    outcomes = validate_sources(
        services.source_profiles.list(actor.tenant), services.environment_bindings
    )
    for profile, status, reason in outcomes:
        updated = services.source_profiles.set_validation(actor.tenant, profile.source_id, status)
        results.append({**updated.to_dict(), "reason": reason})
    return {"profiles": results}


@router.get("/studio/drafts/{draft_id}")
def studio_load_draft(
    draft_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler")
    snapshot: DraftSnapshot = request.app.state.services.studio_drafts.load(actor.tenant, draft_id)
    return snapshot.to_dict()


@router.get("/studio/drafts/{draft_id}/impacts/{semantic_id}")
def studio_draft_impacts(
    draft_id: str,
    semantic_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler")
    impacts = request.app.state.services.studio_drafts.impacts(actor.tenant, draft_id, semantic_id)
    return {"semanticId": semantic_id, "impacts": impacts}


@router.get("/studio/drafts/{draft_id}/history")
def studio_draft_history(
    draft_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler", "reviewer", "publisher")
    items = request.app.state.services.studio_drafts.history(actor.tenant, draft_id)
    return {"draftId": draft_id, "revisions": items}


@router.get("/studio/drafts/{draft_id}/revisions/{revision}")
def studio_draft_revision(
    draft_id: str,
    revision: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler", "reviewer", "publisher")
    try:
        snapshot = request.app.state.services.studio_drafts.load_revision(
            actor.tenant, draft_id, revision
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NOT_FOUND") from exc
    return cast(DraftSnapshot, snapshot).to_dict()


@router.put("/studio/drafts/{draft_id}")
def studio_save_draft(
    draft_id: str,
    body: DraftBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler")
    try:
        snapshot: DraftSnapshot = request.app.state.services.studio_drafts.save(
            actor.tenant,
            actor.subject,
            draft_id,
            body.documents,
            body.expected_revision,
        )
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidDraft as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_DRAFT",
                "diagnostics": [item.model_dump() for item in exc.diagnostics],
            },
        ) from exc
    return snapshot.to_dict()


@router.get("/studio/drafts/{draft_id}/review")
def studio_review_draft(
    draft_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler", "reviewer", "publisher")
    return cast(
        dict[str, Any],
        request.app.state.services.studio_releases.review(actor.tenant, draft_id),
    )


@router.post("/studio/drafts/{draft_id}/validate")
def studio_validate_draft(
    draft_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler")
    services = request.app.state.services
    return cast(
        dict[str, Any],
        services.studio_releases.validate(
            actor.tenant, actor.subject, draft_id, services.environment
        ),
    )


@router.post("/studio/drafts/{draft_id}/approve")
def studio_approve_draft(
    draft_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "reviewer")
    services = request.app.state.services
    try:
        return cast(
            dict[str, Any],
            services.studio_releases.approve(
                actor.tenant, actor.subject, draft_id, services.environment
            ),
        )
    except ReleaseGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/studio/drafts/{draft_id}/publish")
def studio_publish_draft(
    draft_id: str,
    body: PublishBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "publisher")
    services = request.app.state.services
    try:
        return cast(
            dict[str, Any],
            services.studio_releases.publish(
                actor.tenant,
                actor.subject,
                draft_id,
                services.environment,
                body.expected_environment_revision,
            ),
        )
    except ReleaseGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StaleRevision as exc:
        raise HTTPException(status_code=409, detail="ENVIRONMENT_REVISION_CONFLICT") from exc


@router.get("/studio/releases")
def studio_release_history(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler", "reviewer", "publisher", "model-viewer")
    services = request.app.state.services
    digest, revision = services.studio_releases.pointer(actor.tenant, services.environment)
    return {
        "environment": services.environment,
        "activeDigest": digest,
        "environmentRevision": revision,
        "releases": services.studio_releases.history(actor.tenant),
    }


@router.get("/mcp/tools")
def mcp_tools(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    actor = actor_from_header(authorization)
    if not authorize_query(actor, "discover").allowed:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    return {
        "tools": [
            {"name": "semantic_query", "input": ["metric", "bindings"]},
            {"name": "evaluate_claim", "input": ["claimId", "bindings"]},
            {"name": "plan_action", "input": ["actionId", "target", "parameters"]},
            {"name": "action_status", "input": ["planId"]},
        ]
    }

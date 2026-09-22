"""REST/MCP-style semantic API. No SQL/URL/permission request fields."""

from __future__ import annotations

import os
from typing import Any, Self, cast

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator

from semaloom.adapters.spec_import import fetch_spec
from semaloom.app.authentication import AuthenticationError, bearer_token
from semaloom.core.bundle import CompiledBundle
from semaloom.core.provider import IdentityScalar
from semaloom.core.results import (
    MetricSelect,
    ObjectSearchRequest,
    ObjectSelect,
    QueryContext,
    QueryRequest,
)
from semaloom.core.semantic_query import PlanRef, SemanticQuery
from semaloom.core.wire import wire_config
from semaloom.runtime.analysis import AnalysisError, execute, prepare
from semaloom.runtime.auth import RequestActor, authorize_query
from semaloom.runtime.discovery import SemanticDiscovery
from semaloom.runtime.eval import EvaluationError, evaluate_claim_with_evidence
from semaloom.runtime.registry import StaleRevision
from semaloom.runtime.source_introspection import introspect_source, peek_source_rows
from semaloom.runtime.source_registry import SourceRevisionConflict
from semaloom.runtime.source_validation import (
    resolve_environment_binding,
    validate_source,
    validate_sources,
)
from semaloom.runtime.studio import (
    studio_graph,
    studio_inspector,
    studio_mapping_preview,
    studio_mappings,
    studio_sources,
)
from semaloom.runtime.studio_control import DraftSnapshot, InvalidDraft, RevisionConflict

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
            "sample-viewer",
            "analyst",
        ),
    ),
    "modeler": RequestActor(tenant="tenant-a", subject="local-modeler", roles=("modeler",)),
    "viewer": RequestActor(tenant="tenant-a", subject="local-viewer", roles=("model-viewer",)),
    "source-admin": RequestActor(
        tenant="tenant-a", subject="local-source-admin", roles=("source-admin",)
    ),
}

FORBIDDEN_KEYS = frozenset({"sql", "url", "permissions", "table", "column", "join"})


class StrictModel(BaseModel):
    model_config = wire_config(frozen=False)


class PeriodBody(StrictModel):
    period_from: str
    period_to: str

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        QueryContext(business_period={"from": self.period_from, "to": self.period_to})
        return self


class QueryBody(PeriodBody):
    metric: str
    bindings: dict[str, IdentityScalar]


class ClaimBody(PeriodBody):
    claim_id: str
    bindings: dict[str, IdentityScalar]
    dimensions: dict[str, str] = Field(default_factory=dict)


class ActionPlanBody(StrictModel):
    action_id: str
    target: dict[str, str]
    parameters: dict[str, str]


class ActionIdBody(StrictModel):
    plan_id: str
    parameters: dict[str, str] | None = None


def actor_from_header(request: Request, authorization: str | None) -> RequestActor:
    try:
        token = bearer_token(authorization)
        actor = cast(RequestActor, request.app.state.authenticator.authenticate(token))
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="UNAUTHENTICATED") from exc
    return actor


def actor_from_studio_request(request: Request, authorization: str | None) -> RequestActor:
    if authorization and request.method in {"GET", "HEAD", "OPTIONS"}:
        return actor_from_header(request, authorization)
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


def actor_from_read_request(request: Request, authorization: str | None) -> RequestActor:
    """Use explicit bearer credentials or the same guarded Studio session."""
    if authorization is not None:
        return actor_from_header(request, authorization)
    return actor_from_studio_request(request, None)


def reject_forbidden(payload: dict[str, Any]) -> None:
    lowered = {str(key).lower() for key in payload}
    if lowered & FORBIDDEN_KEYS:
        raise HTTPException(status_code=400, detail="INVALID_REQUEST")


def require_role(actor: RequestActor, *roles: str) -> None:
    if not set(actor.roles) & set(roles):
        raise HTTPException(status_code=403, detail="FORBIDDEN")


def studio_bundle(request: Request, actor: RequestActor, draft_id: str | None) -> CompiledBundle:
    if draft_id is None:
        return cast(CompiledBundle, request.app.state.services.query_active(actor.tenant).bundle)
    require_role(actor, "modeler")
    return cast(
        CompiledBundle,
        request.app.state.services.studio_drafts.bundle(actor.tenant, draft_id),
    )


@router.get("/describe")
def describe_semantic(
    request: Request,
    semanticId: str = Query(min_length=1, max_length=200),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_read_request(request, authorization)
    bundle = request.app.state.services.query_active(actor.tenant).bundle
    try:
        return SemanticDiscovery(bundle).describe(semanticId, actor)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="FORBIDDEN") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NOT_FOUND") from exc


@router.get("/search")
def search_semantics(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_read_request(request, authorization)
    bundle = request.app.state.services.query_active(actor.tenant).bundle
    try:
        return SemanticDiscovery(bundle).search(q, actor, limit=limit)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="FORBIDDEN") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_SEARCH") from exc


@router.post("/semantic/prepare")
def semantic_prepare(
    body: SemanticQuery, request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = actor_from_read_request(request, authorization)
    try:
        result = prepare(request.app.state.services.query_active(actor.tenant), body, actor)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="FORBIDDEN") from exc
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json", by_alias=True)


@router.post("/semantic/execute")
def semantic_execute(
    body: PlanRef, request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = actor_from_read_request(request, authorization)
    try:
        result = execute(request.app.state.services.query_active(actor.tenant), body, actor)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="FORBIDDEN") from exc
    except AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json", by_alias=True)


@router.post("/objects/search")
def find_business_objects(
    body: ObjectSearchRequest, request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = actor_from_read_request(request, authorization)
    try:
        return cast(
            dict[str, Any],
            request.app.state.services.query_active(actor.tenant).find_objects(body, actor),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="FORBIDDEN") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/query")
def query_metric(
    body: QueryBody | QueryRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    reject_forbidden(body.model_dump())
    actor = actor_from_read_request(request, authorization)
    services = request.app.state.services
    if isinstance(body, QueryBody):
        reject_forbidden(body.bindings)
        semantic_request = QueryRequest(
            api_version="semaloom/v0.1",
            select=(MetricSelect(metric=body.metric, bindings=body.bindings),),
            context=QueryContext(business_period={"from": body.period_from, "to": body.period_to}),
        )
    else:
        semantic_request = body
    query = services.query_active(actor.tenant)
    envelope = query.execute(semantic_request, actor)
    dumped = envelope.model_dump(mode="json", by_alias=True)
    return dict(dumped)


@router.post("/claims/evaluate")
def evaluate_claim(
    body: ClaimBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    reject_forbidden(body.bindings)
    actor = actor_from_read_request(request, authorization)
    services = request.app.state.services
    query = services.query_active(actor.tenant)
    try:
        claim, observations, diagnostics, digest, activities = evaluate_claim_with_evidence(
            query.bundle,
            query,
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
        "sourceActivities": [item.model_dump(mode="json", by_alias=True) for item in activities],
    }


@router.post("/actions/plan")
def plan_action(
    body: ActionPlanBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_header(request, authorization)
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
    actor = actor_from_header(request, authorization)
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
    actor = actor_from_header(request, authorization)
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
    actor = actor_from_header(request, authorization)
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
    expected_revision: int
    documents: list[dict[str, Any]]


class SourceProfileBody(StrictModel):
    expected_revision: int
    label: str
    provider: str
    binding_ref: str
    secret_ref: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class DemoSessionBody(StrictModel):
    persona: str = "studio-admin"


class SourceRowsBody(StrictModel):
    table: str = Field(min_length=1, max_length=64)
    schema_name: str | None = Field(
        default=None, validation_alias="schema", serialization_alias="schema", max_length=64
    )
    limit: int = Field(default=20, ge=1, le=50)


class SampleBody(StrictModel):
    object_id: str | None = None
    mapping_id: str | None = None
    metric_id: str | None = None
    identity: dict[str, str | int | bool]
    properties: list[str] = Field(default_factory=list)
    bindings: dict[str, IdentityScalar] = Field(default_factory=dict)
    draft_id: str | None = None


class FetchSpecBody(StrictModel):
    url: str
    auth_type: str = "none"
    token: str | None = None
    api_key: str | None = None
    api_key_name: str | None = None
    api_key_in: str | None = None
    username: str | None = None
    password: str | None = None


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
    reject_forbidden(body.bindings)
    if not body.mapping_id and not body.object_id and not body.metric_id:
        raise HTTPException(status_code=422, detail="MAPPING_OR_OBJECT_REQUIRED")
    bundle = studio_bundle(request, actor, body.draft_id)
    query = request.app.state.services.query_for_bundle(bundle, actor.tenant)
    mapping_id = body.mapping_id
    if mapping_id is None and body.metric_id:
        match = next((item for item in bundle.mappings if item.target == body.metric_id), None)
        mapping_id = match.id if match is not None else None
        if mapping_id is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
    if mapping_id:
        payload = studio_mapping_preview(
            bundle,
            query.provider,
            mapping_id=mapping_id,
            tenant=actor.tenant,
            identity=body.identity,
            bindings=body.bindings,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        return payload
    object_id = body.object_id
    object_type = next((item for item in bundle.object_types if item.id == object_id), None)
    if object_id is None or object_type is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if set(body.identity) != set(object_type.identity_keys):
        raise HTTPException(status_code=422, detail="INVALID_IDENTITY")
    envelope = query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                ObjectSelect(
                    object_type=object_id,
                    identity={key: str(body.identity[key]) for key in object_type.identity_keys},
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
    require_role(actor, "source-admin", "model-viewer", "modeler")
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


@router.get("/studio/source-profiles/{source_id}/schema")
def studio_source_schema(
    source_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "source-admin", "modeler")
    services = request.app.state.services
    try:
        profile = services.source_profiles.get(actor.tenant, source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NOT_FOUND") from exc
    url = resolve_environment_binding(profile.binding_ref, services.environment_bindings)
    if url is None:
        return {"provider": profile.provider, "resources": [], "reason": "BINDING_NOT_RESOLVED"}
    return introspect_source(profile.provider, url)


@router.post("/studio/source-profiles/{source_id}/rows")
def studio_source_rows(
    source_id: str,
    body: SourceRowsBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "sample-viewer", "modeler")
    services = request.app.state.services
    try:
        profile = services.source_profiles.get(actor.tenant, source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NOT_FOUND") from exc
    url = resolve_environment_binding(profile.binding_ref, services.environment_bindings)
    if url is None:
        return {"columns": [], "rows": [], "reason": "BINDING_NOT_RESOLVED"}
    try:
        return peek_source_rows(
            profile.provider,
            url,
            body.table,
            body.schema_name,
            actor.tenant,
            body.limit,
            tenant_column=str(profile.settings.get("tenantColumn", "tenant_id")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


@router.post("/studio/apis/fetch-spec")
def studio_fetch_spec(
    body: FetchSpecBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "source-admin", "modeler")
    headers: dict[str, str] = {
        "Accept": "application/json, application/yaml, text/yaml, text/plain, */*"
    }
    params: dict[str, str] = {}
    auth = None
    if body.auth_type == "bearer" and body.token:
        headers["Authorization"] = f"Bearer {body.token}"
    elif body.auth_type == "apiKey" and body.api_key:
        name = body.api_key_name or "X-API-Key"
        if body.api_key_in == "query":
            params[name] = body.api_key
        else:
            headers[name] = body.api_key
    elif body.auth_type == "basic" and body.username:
        auth = httpx.BasicAuth(body.username, body.password or "")

    try:
        return fetch_spec(
            body.url,
            allowed_origins=tuple(
                value.strip()
                for value in os.getenv("SEMALOOM_SPEC_ALLOWED_ORIGINS", "").split(",")
                if value.strip()
            ),
            headers=headers,
            params=params,
            auth=auth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


@router.put("/studio/drafts/{draft_id}")
def studio_save_draft(
    draft_id: str,
    body: DraftBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler")
    services = request.app.state.services
    try:
        snapshot, live = services.studio_releases.save_and_activate(
            actor.tenant,
            actor.subject,
            draft_id,
            services.environment,
            body.documents,
            body.expected_revision,
        )
    except (RevisionConflict, StaleRevision) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidDraft as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_DRAFT",
                "diagnostics": [item.model_dump() for item in exc.diagnostics],
            },
        ) from exc
    return {
        **snapshot.to_dict(),
        "activeDigest": live["digest"],
        "environmentRevision": live["environmentRevision"],
        "status": "ACTIVE",
    }


@router.get("/studio/releases")
def studio_release_history(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = actor_from_studio_request(request, authorization)
    require_role(actor, "modeler", "model-viewer")
    services = request.app.state.services
    digest, revision = services.studio_releases.pointer(actor.tenant, services.environment)
    return {
        "environment": services.environment,
        "activeDigest": digest,
        "environmentRevision": revision,
        "releases": services.studio_releases.history(actor.tenant),
    }


@router.get("/agent/tools")
def agent_tools(
    request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    from semaloom.app.agent_tools import read_tools

    actor = actor_from_read_request(request, authorization)
    if not authorize_query(actor, "discover").allowed:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    return {
        "tools": read_tools(ClaimBody.model_json_schema(by_alias=True)),
        "instructions": (
            "Use semantic definitions and exact business identities. Select among ambiguous "
            "candidates. Quote units, periods, source status and evidence. Never equate "
            "missing with zero, UNKNOWN with FALSE, or a numeric check with compliance. "
            "These are HTTP tools, not MCP transport. "
        ),
    }


@router.get("/mcp/tools")
def mcp_tools(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    actor = actor_from_header(request, authorization)
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

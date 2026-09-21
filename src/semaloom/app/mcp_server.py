"""Official MCP transport backed by the same semantic services and identity as REST."""

from __future__ import annotations

from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from semaloom.app.authentication import AuthenticationError, BearerAuthenticator
from semaloom.app.http import ClaimBody, QueryBody
from semaloom.core.results import MetricSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor, authorize_query
from semaloom.runtime.discovery import SemanticDiscovery
from semaloom.runtime.eval import evaluate_claim_with_evidence


class SemanticTokenVerifier(TokenVerifier):
    """Adapt SemaLoom's single bearer verifier to the MCP SDK auth contract."""

    def __init__(self, authenticator: BearerAuthenticator) -> None:
        self._authenticator = authenticator

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            actor = self._authenticator.authenticate(token)
        except AuthenticationError:
            return None
        return AccessToken(
            token=token,
            client_id=actor.subject,
            subject=actor.subject,
            scopes=list(actor.roles),
            claims={"tenant": actor.tenant, "roles": list(actor.roles)},
        )


def _actor() -> RequestActor:
    access = get_access_token()
    claims = access.claims if access is not None else None
    tenant = claims.get("tenant") if claims else None
    roles = claims.get("roles") if claims else None
    if (
        access is None
        or not isinstance(tenant, str)
        or not isinstance(roles, list)
        or not all(isinstance(role, str) for role in roles)
    ):
        raise PermissionError("UNAUTHENTICATED")
    return RequestActor(
        tenant=tenant, subject=access.subject or access.client_id, roles=tuple(roles)
    )


def build_mcp_server(services: Any, authenticator: BearerAuthenticator) -> FastMCP:
    server = FastMCP(
        "SemaLoom",
        instructions=(
            "Use semantic identifiers and typed business values only. Missing observations are "
            "not zero, and UNKNOWN claims are not FALSE."
        ),
        token_verifier=SemanticTokenVerifier(authenticator),
        auth=AuthSettings(
            issuer_url=authenticator.issuer,
            resource_server_url=None,
            validate_token_resource=False,
        ),
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
    )

    @server.tool(name="semantic_query")
    def semantic_query(request: dict[str, Any]) -> dict[str, Any]:
        """Read objects or metrics through the typed semantic query contract."""
        actor = _actor()
        if "apiVersion" in request:
            query = QueryRequest.model_validate(request)
        else:
            compact = QueryBody.model_validate(request)
            query = QueryRequest(
                api_version="semaloom/v0.1",
                select=(MetricSelect(metric=compact.metric, bindings=compact.bindings),),
                context=QueryContext(
                    business_period={"from": compact.period_from, "to": compact.period_to}
                ),
            )
        result = services.query_active(actor.tenant).execute(query, actor)
        return dict(result.model_dump(mode="json", by_alias=True))

    @server.tool(name="evaluate_claim")
    def evaluate_claim(request: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a named deterministic claim with observations and evidence."""
        actor = _actor()
        body = ClaimBody.model_validate(request)
        query = services.query_active(actor.tenant)
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
        return {
            "claim": claim.model_dump(mode="json", by_alias=True),
            "observations": [item.model_dump(mode="json", by_alias=True) for item in observations],
            "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            "releaseDigest": digest,
            "sourceActivities": [
                item.model_dump(mode="json", by_alias=True) for item in activities
            ],
        }

    @server.tool(name="explain_semantic")
    def explain_semantic(semantic_id: str) -> dict[str, Any]:
        """Explain a governed business definition without exposing physical mappings."""
        actor = _actor()
        if not authorize_query(actor, "discover").allowed:
            raise PermissionError("FORBIDDEN")
        return SemanticDiscovery(services.query_active(actor.tenant).bundle).describe(
            semantic_id, actor
        )

    return server

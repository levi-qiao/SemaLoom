"""Default-deny tenant/role authorization. Decisions include scope."""

from __future__ import annotations

import uuid

from semaloom.core.security import AccessDecision, ResourceScope

ANALYST_ROLES = frozenset({"analyst", "buyer", "approver"})


class RequestActor:
    def __init__(
        self, *, tenant: str, subject: str, roles: tuple[str, ...], token: str | None = None
    ) -> None:
        self.tenant = tenant
        self.subject = subject
        self.roles = roles
        self.token = token


def authorize_query(actor: RequestActor, resource: str) -> AccessDecision:
    decision_id = uuid.uuid4().hex
    scope = ResourceScope(tenants=(actor.tenant,), object_types=(), identities=(), fields=())
    if not actor.tenant or not actor.subject:
        return AccessDecision(
            allowed=False,
            effect="DENY",
            reason="missing actor",
            scope=scope,
            policy_revision="v0.1",
            decision_id=decision_id,
        )
    if not set(actor.roles) & ANALYST_ROLES:
        return AccessDecision(
            allowed=False,
            effect="DENY",
            reason="role not permitted",
            scope=scope,
            policy_revision="v0.1",
            decision_id=decision_id,
        )
    return AccessDecision(
        allowed=True,
        effect="ALLOW",
        reason="tenant-scoped query",
        scope=scope,
        policy_revision="v0.1",
        decision_id=decision_id,
    )

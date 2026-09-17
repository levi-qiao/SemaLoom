"""Action plan, approval, execute, and reconcile. One process, one effect."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from semaloom.core.action import ActionExecution, ActionPlan, ActionStatus
from semaloom.core.bundle import CompiledBundle
from semaloom.runtime.auth import RequestActor, authorize_query


class DraftStore:
    """In-process synthetic draft system with idempotency and version checks."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.idempotency: dict[str, str] = {}
        self.writes = 0

    def create(
        self, *, idempotency_key: str, payload: dict[str, Any], expected_version: int | None = None
    ) -> str:
        if idempotency_key in self.idempotency:
            existing_key = self.idempotency[idempotency_key]
            stored = self.rows[existing_key]
            if stored["payload_digest"] != _digest(payload):
                raise ValueError("IDEMPOTENCY_CONFLICT")
            return str(stored["ref"])
        target_key = _draft_target_key(payload.get("target"))
        current = self.rows.get(target_key)
        if (
            expected_version is not None
            and current is not None
            and int(current["version"]) != expected_version
        ):
            raise ValueError("STALE_PLAN")
        ref = uuid.uuid4().hex
        version = 1 if current is None else int(current["version"]) + 1
        self.rows[target_key] = {
            "ref": ref,
            "payload": payload,
            "payload_digest": _digest(payload),
            "version": version,
        }
        self.idempotency[idempotency_key] = target_key
        self.writes += 1
        return ref

    def get(self, target: object) -> dict[str, Any] | None:
        return self.rows.get(_draft_target_key(target))


class ActionService:
    def __init__(self, bundle: CompiledBundle, engine: Engine, drafts: DraftStore) -> None:
        self.bundle = bundle
        self.engine = engine
        self.drafts = drafts

    def plan(
        self,
        actor: RequestActor,
        *,
        action_id: str,
        target: dict[str, str],
        parameters: dict[str, str],
        expires_in_seconds: int = 3600,
    ) -> ActionPlan:
        decision = authorize_query(actor, "planAction")
        if not decision.allowed:
            raise PermissionError("FORBIDDEN")
        action = next((item for item in self.bundle.actions if item.id == action_id), None)
        if action is None:
            raise KeyError(action_id)
        _validate_action_input(self.bundle, action_id, target, parameters)
        plan_id = uuid.uuid4().hex
        expires = (datetime.now(UTC) + timedelta(seconds=expires_in_seconds)).isoformat()
        digest = _digest(
            {
                "action": action_id,
                "version": action.version,
                "tenant": actor.tenant,
                "actor": actor.subject,
                "target": target,
                "parameters": parameters,
                "release": self.bundle.digest,
            }
        )
        plan = ActionPlan(
            plan_id=plan_id,
            action_id=action_id,
            action_version=action.version,
            tenant=actor.tenant,
            actor=actor.subject,
            target=target,
            parameters=parameters,
            digest=digest,
            release_digest=self.bundle.digest,
            expires_at=expires,
            expected_effect=action.effect,
        )
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO action_plan(plan_id, digest, payload)
                    VALUES (:plan_id, :digest, CAST(:payload AS jsonb))
                    """
                ),
                {
                    "plan_id": plan_id,
                    "digest": digest,
                    "payload": plan.model_dump_json(by_alias=True),
                },
            )
        return plan

    def approve(self, actor: RequestActor, plan_id: str, *, hours: int = 1) -> None:
        if "approver" not in actor.roles:
            raise PermissionError("FORBIDDEN")
        plan = self._load_plan(plan_id)
        if plan.tenant != actor.tenant:
            raise PermissionError("FORBIDDEN")
        if plan.digest != _digest(_plan_body(plan)):
            raise ValueError("STALE_PLAN")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO action_approval(plan_id, approver, expires_at, digest)
                    VALUES (:plan_id, :approver, :expires, :digest)
                    ON CONFLICT (plan_id) DO UPDATE
                    SET approver = :approver, expires_at = :expires, digest = :digest
                    """
                ),
                {
                    "plan_id": plan_id,
                    "approver": actor.subject,
                    "expires": datetime.now(UTC) + timedelta(hours=hours),
                    "digest": plan.digest,
                },
            )

    def execute(
        self, actor: RequestActor, plan_id: str, *, parameters: dict[str, str] | None = None
    ) -> ActionExecution:
        decision = authorize_query(actor, "executeAction")
        if not decision.allowed:
            raise PermissionError("FORBIDDEN")
        plan = self._load_plan(plan_id)
        if plan.tenant != actor.tenant:
            raise PermissionError("FORBIDDEN")
        if parameters is not None and parameters != plan.parameters:
            raise ValueError("STALE_PLAN")
        if datetime.now(UTC) > datetime.fromisoformat(plan.expires_at):
            raise ValueError("EXPIRED")
        with self.engine.connect() as conn:
            approval = conn.execute(
                text(
                    "SELECT approver, expires_at, digest FROM action_approval "
                    "WHERE plan_id = :plan_id"
                ),
                {"plan_id": plan_id},
            ).first()
        if approval is None:
            raise PermissionError("UNAPPROVED")
        if approval.digest != plan.digest:
            raise ValueError("STALE_PLAN")
        expires_at = approval.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires_at:
            raise ValueError("EXPIRED")
        execution_id = uuid.uuid4().hex
        with self.engine.begin() as conn:
            claimed = conn.execute(
                text(
                    """
                    INSERT INTO action_execution(
                        execution_id, plan_id, status, payload_digest, external_ref
                    )
                    VALUES (:execution_id, :plan_id, 'EXECUTING', :digest, NULL)
                    ON CONFLICT (plan_id) DO NOTHING
                    RETURNING execution_id
                    """
                ),
                {
                    "execution_id": execution_id,
                    "plan_id": plan_id,
                    "digest": plan.digest,
                },
            ).first()
            if claimed is None:
                existing = conn.execute(
                    text(
                        "SELECT execution_id, status, payload_digest, external_ref "
                        "FROM action_execution WHERE plan_id = :plan_id"
                    ),
                    {"plan_id": plan_id},
                ).one()
                return ActionExecution(
                    execution_id=str(existing.execution_id),
                    plan_id=plan_id,
                    status=cast(ActionStatus, str(existing.status)),
                    payload_digest=str(existing.payload_digest),
                    external_ref=(
                        None if existing.external_ref is None else str(existing.external_ref)
                    ),
                )
        try:
            ref = self.drafts.create(
                idempotency_key=f"{plan.tenant}:{plan.plan_id}",
                payload={"target": dict(plan.target), "parameters": plan.parameters},
            )
        except ValueError:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE action_execution SET status = 'FAILED' "
                        "WHERE plan_id = :plan_id AND status = 'EXECUTING'"
                    ),
                    {"plan_id": plan_id},
                )
            raise
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE action_execution SET status = 'VERIFIED', external_ref = :ref "
                    "WHERE plan_id = :plan_id AND execution_id = :execution_id"
                ),
                {"plan_id": plan_id, "execution_id": execution_id, "ref": ref},
            )
        return ActionExecution(
            execution_id=execution_id,
            plan_id=plan_id,
            status="VERIFIED",
            payload_digest=plan.digest,
            external_ref=ref,
        )

    def status(self, actor: RequestActor, plan_id: str) -> ActionExecution | None:
        plan = self._load_plan(plan_id)
        if plan.tenant != actor.tenant:
            raise PermissionError("FORBIDDEN")
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT execution_id, plan_id, status, payload_digest, "
                    "external_ref FROM action_execution WHERE plan_id = :plan_id"
                ),
                {"plan_id": plan_id},
            ).first()
        if row is None:
            return None
        return ActionExecution(
            execution_id=str(row.execution_id),
            plan_id=str(row.plan_id),
            status=cast(ActionStatus, str(row.status)),
            payload_digest=str(row.payload_digest),
            external_ref=None if row.external_ref is None else str(row.external_ref),
        )

    def _load_plan(self, plan_id: str) -> ActionPlan:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT payload FROM action_plan WHERE plan_id = :plan_id"),
                {"plan_id": plan_id},
            ).first()
        if row is None:
            raise KeyError(plan_id)
        payload = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
        return ActionPlan.model_validate(payload)


def _plan_body(plan: ActionPlan) -> dict[str, Any]:
    return {
        "action": plan.action_id,
        "version": plan.action_version,
        "tenant": plan.tenant,
        "actor": plan.actor,
        "target": plan.target,
        "parameters": plan.parameters,
        "release": plan.release_digest,
    }


def _draft_target_key(target: object) -> str:
    """Stable draft row key for scalar or structured ObjectIdentity targets."""
    if isinstance(target, dict):
        return json.dumps(target, sort_keys=True, separators=(",", ":"), default=str)
    return str(target)


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _validate_action_input(
    bundle: CompiledBundle,
    action_id: str,
    target: dict[str, str],
    parameters: dict[str, str],
) -> None:
    action = next(item for item in bundle.actions if item.id == action_id)
    object_type = next(item for item in bundle.object_types if item.id == action.target_object)
    if set(target) != set(object_type.identity_keys) or any(not value for value in target.values()):
        raise ValueError("INVALID_TARGET")
    declared = {item.name: item for item in action.parameters}
    if set(parameters) - set(declared):
        raise ValueError("INVALID_PARAMETERS")
    if any(item.required and not parameters.get(item.name) for item in action.parameters):
        raise ValueError("INVALID_PARAMETERS")
    for key, raw in parameters.items():
        value_type = declared[key].value_type
        try:
            if value_type == "INTEGER":
                int(raw)
            elif value_type == "DECIMAL":
                value = Decimal(raw)
                if not value.is_finite():
                    raise ValueError
            elif value_type == "BOOLEAN" and raw.lower() not in {"true", "false"}:
                raise ValueError
            elif value_type == "DATE":
                date.fromisoformat(raw)
            elif value_type == "DATETIME":
                datetime.fromisoformat(raw)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("INVALID_PARAMETERS") from exc

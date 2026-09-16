"""Actor-owned chat history in the existing metadata database."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from semaloom.runtime.auth import RequestActor


class ChatStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        with engine.begin() as conn:
            conn.execute(
                text("""CREATE TABLE IF NOT EXISTS chat_conversation (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                release_digest TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                history JSONB NOT NULL DEFAULT '[]', turns JSONB NOT NULL DEFAULT '[]',
                pending JSONB, query_state JSONB,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""")
            )
            conn.execute(
                text("ALTER TABLE chat_conversation ADD COLUMN IF NOT EXISTS pending JSONB")
            )
            conn.execute(
                text("ALTER TABLE chat_conversation ADD COLUMN IF NOT EXISTS query_state JSONB")
            )

    def load(self, actor: RequestActor, conversation_id: str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    text("""SELECT id,release_digest,revision,history,turns,pending,query_state
                FROM chat_conversation WHERE id=:id AND tenant_id=:tenant AND actor_id=:actor"""),
                    {"id": conversation_id, "tenant": actor.tenant, "actor": actor.subject},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError("CONVERSATION_NOT_FOUND")
        return dict(row)

    def create(self, actor: RequestActor, digest: str) -> dict[str, Any]:
        identity = uuid.uuid4().hex
        with self.engine.begin() as conn:
            conn.execute(
                text("""INSERT INTO chat_conversation(id,tenant_id,actor_id,release_digest)
                VALUES(:id,:tenant,:actor,:digest)"""),
                {"id": identity, "tenant": actor.tenant, "actor": actor.subject, "digest": digest},
            )
        return self.load(actor, identity)

    def save(
        self, actor: RequestActor, row: dict[str, Any], history: list[Any], turn: dict[str, Any]
    ) -> None:
        if len(history) > 100 or len(json.dumps(history)) > 250000 or len(row["turns"]) >= 12:
            raise ValueError("CONTEXT_LIMIT_START_NEW_CHAT")
        with self.engine.begin() as conn:
            updated = conn.execute(
                text("""UPDATE chat_conversation SET history=CAST(:history AS JSONB),
                turns=CAST(:turns AS JSONB),pending=NULL,query_state=CAST(:state AS JSONB),
                revision=revision+1,updated_at=now()
                WHERE id=:id AND tenant_id=:tenant AND actor_id=:actor AND revision=:revision"""),
                {
                    "id": row["id"],
                    "tenant": actor.tenant,
                    "actor": actor.subject,
                    "revision": row["revision"],
                    "history": json.dumps(history),
                    "turns": json.dumps([*row["turns"], turn]),
                    "state": json.dumps(row.get("query_state")),
                },
            )
            if updated.rowcount != 1:
                raise ValueError("CONVERSATION_CONFLICT")

    def save_pending(
        self,
        actor: RequestActor,
        row: dict[str, Any],
        pending: dict[str, Any] | None,
        query_state: dict[str, Any] | None,
        original_question: str,
    ) -> dict[str, Any]:
        with self.engine.begin() as conn:
            updated = conn.execute(
                text("""UPDATE chat_conversation SET pending=CAST(:pending AS JSONB),
                query_state=CAST(:state AS JSONB),revision=revision+1,updated_at=now()
                WHERE id=:id AND tenant_id=:tenant AND actor_id=:actor AND revision=:revision"""),
                {
                    "id": row["id"],
                    "tenant": actor.tenant,
                    "actor": actor.subject,
                    "revision": row["revision"],
                    "pending": json.dumps(pending) if pending is not None else None,
                    "state": json.dumps(
                        {**(query_state or {}), "originalQuestion": original_question}
                    )
                    if query_state is not None or original_question
                    else None,
                },
            )
            if updated.rowcount != 1:
                raise ValueError("CONVERSATION_CONFLICT")
        return self.load(actor, row["id"])

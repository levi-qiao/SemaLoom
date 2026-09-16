"""Studio same-origin chat. The browser submits user text, never tool results or actor claims."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from semaloom.app.chat.choices import submit_choice
from semaloom.app.chat.presentation import visible_answer, without_physical_metadata
from semaloom.app.chat.service import ChatService
from semaloom.app.http import actor_from_read_request
from semaloom.core.semantic_query import ChoiceError, ChoiceSubmit
from semaloom.runtime.auth import RequestActor, authorize_query

router = APIRouter(prefix="/v0.1/chat")


class TurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None, alias="conversationId", pattern=r"^[0-9a-f]{32}$"
    )


def chat_actor(request: Request, authorization: str | None) -> RequestActor:
    actor = actor_from_read_request(request, authorization)
    if not authorize_query(actor, "chat").allowed:
        raise HTTPException(403, "FORBIDDEN")
    return actor


def service(request: Request) -> ChatService:
    chat = getattr(request.app.state, "chat", None)
    if chat is None:
        raise HTTPException(503, "CHAT_NOT_CONFIGURED")
    return cast(ChatService, chat)


@router.get("/status")
def status(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    chat_actor(request, authorization)
    chat = getattr(request.app.state, "chat", None)
    return dict(chat.status()) if chat is not None else {"enabled": False, "ready": False}


@router.get("/conversations/{conversation_id}")
async def conversation(
    conversation_id: str, request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = chat_actor(request, authorization)
    try:
        row = await asyncio.to_thread(service(request).store.load, actor, conversation_id)
    except KeyError as exc:
        raise HTTPException(404, "CONVERSATION_NOT_FOUND") from exc
    turns = [{**turn, "answer": visible_answer(turn["answer"], actor)} for turn in row["turns"]]
    return {
        "id": row["id"],
        "releaseDigest": row["release_digest"],
        "turns": turns,
        "pendingQuestion": row.get("pending"),
        "originalQuestion": (row.get("query_state") or {}).get("originalQuestion"),
    }


class ChoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(alias="conversationId", pattern=r"^[0-9a-f]{32}$")
    question_id: str = Field(alias="questionId")
    revision: int = Field(ge=1)
    option_ids: list[str] = Field(alias="optionIds", min_length=1, max_length=4)
    other_text: str | None = Field(default=None, alias="otherText", max_length=400)


@router.post("/choices")
async def choose(
    body: ChoiceBody, request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = chat_actor(request, authorization)
    chat = service(request)
    query = request.app.state.services.query_active(actor.tenant)
    try:
        result = await asyncio.to_thread(
            submit_choice,
            chat.store,
            query,
            actor,
            body.conversation_id,
            ChoiceSubmit.model_validate(
                {
                    "questionId": body.question_id,
                    "revision": body.revision,
                    "optionIds": body.option_ids,
                    "otherText": body.other_text,
                }
            ),
        )
    except KeyError as exc:
        raise HTTPException(404, "CONVERSATION_NOT_FOUND") from exc
    except ChoiceError as exc:
        raise HTTPException(409, exc.code) from exc
    if result.get("evidence"):
        result = {
            **result,
            "evidence": visible_answer({"evidence": result["evidence"]}, actor)["evidence"],
        }
    if not set(actor.roles) & {"modeler", "model-viewer", "source-admin"}:
        result = without_physical_metadata(result)
    return result


@router.post("/turns")
async def turn(
    body: TurnBody, request: Request, authorization: str | None = Header(default=None)
) -> StreamingResponse:
    actor = chat_actor(request, authorization)
    chat = service(request)
    if not chat.status()["ready"]:
        raise HTTPException(503, "HARNESS_NOT_INSTALLED")
    query = request.app.state.services.query_active(actor.tenant)
    try:
        row = (
            await asyncio.to_thread(chat.store.load, actor, body.conversation_id)
            if body.conversation_id
            else await asyncio.to_thread(chat.store.create, actor, query.bundle.digest)
        )
    except KeyError as exc:
        raise HTTPException(404, "CONVERSATION_NOT_FOUND") from exc
    if row["release_digest"] != query.bundle.digest:
        raise HTTPException(409, "RELEASE_CHANGED_START_NEW_CHAT")
    if len(row["turns"]) >= 12 or len(str(row["history"])) > 220000:
        raise HTTPException(409, "CONTEXT_LIMIT_START_NEW_CHAT")
    if row["id"] in chat.busy or len(chat.busy) >= 4:
        raise HTTPException(409, "CHAT_BUSY")

    def guard() -> RequestActor:
        current = chat_actor(request, authorization)
        if (current.tenant, current.subject) != (actor.tenant, actor.subject):
            raise HTTPException(403, "ACTOR_CHANGED")
        if (
            request.app.state.services.query_active(actor.tenant).bundle.digest
            != query.bundle.digest
        ):
            raise HTTPException(409, "RELEASE_CHANGED_START_NEW_CHAT")
        return current

    return StreamingResponse(
        chat.stream(row, body.message, query, actor, guard),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

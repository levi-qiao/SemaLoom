"""Bounded pi subprocess lifecycle. No Node HTTP server and no business credentials in Node."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from semaloom.app.chat.choices import try_direct_turn
from semaloom.app.chat.i18n import localize_question, message_locale, text
from semaloom.app.chat.presentation import project_browser_answer, visible_answer
from semaloom.app.chat.store import ChatStore
from semaloom.app.chat.tools import SYSTEM_PROMPT, SemanticTools
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.eval import EvaluationError
from semaloom.runtime.query import QueryService


class ChatService:
    def __init__(self, store: ChatStore, config_path: Path) -> None:
        config = json.loads(config_path.read_text())
        base = str(config["baseUrl"]).strip().rstrip("/")
        if not base.startswith("https://"):
            raise ValueError("chat provider requires HTTPS")
        self.provider = {
            "baseUrl": base,
            "apiKey": str(config["apiKey"]),
            "model": str(config.get("model", "deepseek-v4.1-flash")),
        }
        self.decision = self._decision_config()
        source_worker = Path(__file__).resolve().parents[4] / "harness" / "worker.mjs"
        default_worker = (
            source_worker
            if source_worker.is_file()
            else (Path(__file__).parent / "harness" / "worker.mjs")
        )
        self.worker = Path(os.getenv("SEMALOOM_CHAT_WORKER", str(default_worker))).resolve()
        self.node = shutil.which("node")
        self.store = store
        self.busy: set[str] = set()
        self.processes: set[asyncio.subprocess.Process] = set()

    @staticmethod
    def _decision_config() -> dict[str, Any] | None:
        api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
        if not api_key:
            return None
        mode = os.getenv("SEMALOOM_JEV_MODE", "shadow").strip().lower()
        if mode not in {"shadow", "enforce"}:
            raise ValueError("SEMALOOM_JEV_MODE must be shadow or enforce")
        confidence = float(os.getenv("SEMALOOM_JEV_MIN_CONFIDENCE", "0.85"))
        if not 0 <= confidence <= 1:
            raise ValueError("SEMALOOM_JEV_MIN_CONFIDENCE must be between 0 and 1")
        base_url = os.getenv("TYPESAFE_BASE_URL", "").strip() or None
        if base_url is not None and not base_url.startswith("https://"):
            raise ValueError("TypeSafe provider requires HTTPS")
        return {
            "apiKey": api_key,
            "baseURL": base_url,
            "model": os.getenv("TYPESAFE_DEFAULT_MODEL", "jev-latest").strip() or "jev-latest",
            "minConfidence": confidence,
            "mode": mode,
        }

    def status(self) -> dict[str, Any]:
        status = {
            "enabled": True,
            "ready": bool(
                self.node
                and self.worker.is_file()
                and (self.worker.parent / "node_modules/@earendil-works/pi-agent-core").exists()
            ),
            "model": self.provider["model"],
            "provider": "百炼 Token Plan",
            "limits": {"turns": 12, "toolCalls": 20, "seconds": 180},
        }
        if self.decision:
            status.update(
                decisionProvider="TypeSafe Jev",
                decisionModel=self.decision["model"],
                decisionMode=self.decision["mode"],
            )
        return status

    async def close(self) -> None:
        for process in tuple(self.processes):
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def stream(
        self,
        row: dict[str, Any],
        message: str,
        query: QueryService,
        actor: RequestActor,
        guard: Callable[[], RequestActor | None],
        locale: str = "zh-CN",
    ) -> AsyncIterator[str]:
        locale = message_locale(message, locale)
        identity = str(row["id"])
        if identity in self.busy or len(self.busy) >= 4:
            yield event("error", code="CHAT_BUSY")
            return
        self.busy.add(identity)
        process = None
        try:
            guard()
            direct = (
                None
                if self.decision
                else await asyncio.to_thread(try_direct_turn, query, actor, message, locale)
            )
            if direct and (direct.get("answerReady") or direct.get("waiting")):
                direct["question"] = localize_question(direct.get("question"), locale)
                yield event(
                    "start",
                    conversationId=identity,
                    releaseDigest=query.bundle.digest,
                    model=self.provider["model"],
                )
                if direct.get("waiting"):
                    await asyncio.to_thread(
                        self.store.save_pending,
                        actor,
                        row,
                        direct.get("question"),
                        {
                            **(direct.get("query_state") or {}),
                            "query": direct.get("query"),
                            "locale": locale,
                            **(
                                {"mode": direct["mode"], "claimId": direct.get("claimId")}
                                if direct.get("mode")
                                else {}
                            ),
                        },
                        message,
                    )
                    yield event(
                        "choice",
                        conversationId=identity,
                        question=direct.get("question"),
                        originalQuestion=message,
                        releaseDigest=query.bundle.digest,
                    )
                    yield event("done")
                    return
                answer = project_browser_answer(
                    {
                        "kind": "unsupported"
                        if direct.get("status") == "UNSUPPORTED"
                        else "answer",
                        "textOrigin": "ENGINE",
                        "text": direct.get("text") or text(locale, "answer.completed"),
                        "evidence": [
                            {
                                "id": "e1",
                                "tool": direct.get("tool") or "prepare_semantic_query",
                                "result": direct.get("result") or {},
                            }
                        ],
                        "releaseDigest": query.bundle.digest,
                        "followUps": direct.get("followUps") or [],
                        "assumptions": direct.get("assumptions") or [],
                        "query": direct.get("query"),
                        "originalQuestion": message,
                    },
                    query.bundle,
                    locale,
                )
                refreshed = {
                    **row,
                    "query_state": {
                        "query": direct.get("query"),
                        "originalQuestion": message,
                        "locale": locale,
                    },
                }
                new_turn = {"question": message, "answer": answer}
                user_msg = {
                    "role": "user",
                    "content": message,
                    "timestamp": int(time.time() * 1000),
                }
                assistant_msg = {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": answer.get("text") or text(locale, "answer.completed"),
                        }
                    ],
                    "timestamp": int(time.time() * 1000),
                }
                history = [*row.get("history", []), user_msg, assistant_msg]
                try:
                    await asyncio.to_thread(
                        self.store.save,
                        actor,
                        refreshed,
                        history,
                        new_turn,
                    )
                except ValueError:
                    raise
                except Exception:
                    yield event("error", code="CHAT_HISTORY_SAVE_FAILED")
                    return
                current_actor = guard() or actor
                yield event("answer", answer=visible_answer(answer, current_actor))
                yield event("done")
                return
            previous_query = (row.get("query_state") or {}).get("query")
            gateway = SemanticTools(
                query,
                actor,
                user_message=message,
                confirmed_query=previous_query,
                locale=locale,
            )
            guard()
            process = await asyncio.create_subprocess_exec(
                self.node or "node",
                str(self.worker),
                cwd=str(self.worker.parent),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=2**20,
                env={"PATH": os.environ.get("PATH", ""), "LANG": "en_US.UTF-8"},
            )
            self.processes.add(process)
            assert process.stdin is not None and process.stdout is not None
            payload = {
                "type": "start",
                "provider": self.provider,
                "catalog": gateway.catalog(),
                "systemPrompt": SYSTEM_PROMPT
                + "\nBusiness catalog (discovery index only):\n"
                + gateway.overview()
                + "\nPrevious confirmed conversation query (context only; "
                "current user instructions take precedence, do not submit decisions):\n"
                + json.dumps(row.get("query_state") or {}, ensure_ascii=False),
                "history": row.get("history") or [],
                "message": message,
                "releaseDigest": query.bundle.digest,
                "locale": locale,
                "semanticContext": json.loads(gateway.overview()),
                "decision": self.decision,
            }
            process.stdin.write((json.dumps(payload) + "\n").encode())
            await process.stdin.drain()
            yield event(
                "start",
                conversationId=identity,
                releaseDigest=query.bundle.digest,
                model=self.provider["model"],
            )
            received = 0
            async with asyncio.timeout(180):
                while line := await process.stdout.readline():
                    received += len(line)
                    if received > 3_000_000:
                        raise ValueError("HARNESS_OUTPUT_LIMIT")
                    item = json.loads(line)
                    guard()
                    if item["type"] == "progress":
                        yield json.dumps(item) + "\n"
                    elif item["type"] == "call":
                        try:
                            result = await asyncio.to_thread(
                                gateway.call, item["name"], item["args"]
                            )
                        except ValidationError as exc:
                            result = {
                                "error": "INVALID_TYPED_ARGUMENTS",
                                "issues": [
                                    {
                                        "path": ".".join(str(p) for p in e["loc"]),
                                        "type": e["type"],
                                        "message": e["msg"],
                                    }
                                    for e in exc.errors(include_input=False, include_url=False)[:8]
                                ],
                            }
                        except EvaluationError as exc:
                            result = {"error": exc.code}
                        except HTTPException as exc:
                            result = {"error": str(exc.detail)}
                        except (KeyError, ValueError) as exc:
                            result = {
                                "error": str(exc.args[0]) if exc.args else "INVALID_ARGUMENTS"
                            }
                        guard()
                        yield event(
                            "progress",
                            stage="tool_result",
                            name=item["name"],
                            outcome="error" if "error" in result else "ok",
                            code=result.get("error"),
                        )
                        process.stdin.write(
                            (
                                json.dumps({"type": "result", "id": item["id"], "payload": result})
                                + "\n"
                            ).encode()
                        )
                        await process.stdin.drain()
                    elif item["type"] == "error":
                        yield event("error", code=str(item["code"]))
                        return
                    elif item["type"] == "complete":
                        if gateway.pending is not None:
                            guard()
                            await asyncio.to_thread(
                                self.store.save_pending,
                                actor,
                                row,
                                gateway.pending.get("question"),
                                {
                                    **(gateway.pending.get("query_state") or {}),
                                    "query": gateway.pending.get("query"),
                                    "locale": locale,
                                },
                                message,
                            )
                            yield event(
                                "choice",
                                conversationId=identity,
                                question=gateway.pending.get("question"),
                                originalQuestion=message,
                                releaseDigest=query.bundle.digest,
                            )
                            yield event("done")
                            return
                        if gateway.answer is None:
                            raise ValueError("ANSWER_NOT_VALIDATED")
                        guard()
                        browser_answer = project_browser_answer(
                            gateway.answer, query.bundle, locale
                        )
                        new_turn = {"question": message, "answer": browser_answer}
                        if browser_answer.get("query"):
                            row = {
                                **row,
                                "query_state": {
                                    "query": browser_answer["query"],
                                    "originalQuestion": message,
                                    "locale": locale,
                                },
                            }
                        saved_history = item.get("history")
                        if not isinstance(saved_history, list):
                            user_msg = {
                                "role": "user",
                                "content": message,
                                "timestamp": int(time.time() * 1000),
                            }
                            assistant_msg = {
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": browser_answer.get("text")
                                        or text(locale, "answer.completed"),
                                    }
                                ],
                                "timestamp": int(time.time() * 1000),
                            }
                            saved_history = [*row.get("history", []), user_msg, assistant_msg]
                        try:
                            await asyncio.to_thread(
                                self.store.save,
                                actor,
                                row,
                                saved_history,
                                new_turn,
                            )
                        except ValueError:
                            raise
                        except Exception:
                            yield event("error", code="CHAT_HISTORY_SAVE_FAILED")
                            return
                        current_actor = guard() or actor
                        yield event("answer", answer=visible_answer(browser_answer, current_actor))
                        yield event("done")
                        return
                yield event("error", code="HARNESS_EXITED")
        except TimeoutError:
            yield event("error", code="CHAT_TIMEOUT")
        except HTTPException as exc:
            yield event("error", code=str(exc.detail))
        except ValueError as exc:
            code = str(exc.args[0]) if exc.args else "CHAT_FAILED"
            yield event("error", code=code if code.isupper() and len(code) < 70 else "CHAT_FAILED")
        except (OSError, RuntimeError):
            yield event("error", code="HARNESS_UNAVAILABLE")
        except Exception:
            logging.exception("chat turn failed")
            yield event("error", code="CHAT_FAILED")
        finally:
            self.busy.discard(identity)
            if process is not None:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                self.processes.discard(process)


def event(kind: str, **values: Any) -> str:
    return json.dumps({"type": kind, **values}, ensure_ascii=False) + "\n"

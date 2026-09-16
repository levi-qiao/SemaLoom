"""Bounded pi subprocess lifecycle. No Node HTTP server and no business credentials in Node."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from semaloom.app.chat.choices import try_direct_turn
from semaloom.app.chat.presentation import attach_lineage, visible_answer
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
            "model": str(config.get("model", "qwen3.7-plus")),
        }
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

    def status(self) -> dict[str, Any]:
        return {
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
    ) -> AsyncIterator[str]:
        identity = str(row["id"])
        if identity in self.busy or len(self.busy) >= 4:
            yield event("error", code="CHAT_BUSY")
            return
        self.busy.add(identity)
        process = None
        try:
            guard()
            direct = await asyncio.to_thread(try_direct_turn, query, actor, message)
            if direct and (direct.get("answerReady") or direct.get("waiting")):
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
                        {"query": direct.get("query")},
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
                answer = attach_lineage(
                    {
                        "kind": "answer",
                        "textOrigin": "ENGINE",
                        "text": direct.get("text") or "已按发布口径完成计算。",
                        "evidence": [
                            {
                                "id": "e1",
                                "tool": "prepare_semantic_query",
                                "result": direct.get("result") or {},
                            }
                        ],
                        "releaseDigest": query.bundle.digest,
                        "confidence": direct.get("confidence"),
                        "followUps": direct.get("followUps") or [],
                        "assumptions": direct.get("assumptions") or [],
                    },
                    query.bundle,
                )
                refreshed = {
                    **row,
                    "query_state": {
                        "query": direct.get("query"),
                        "originalQuestion": message,
                    },
                }
                try:
                    await asyncio.to_thread(
                        self.store.save,
                        actor,
                        refreshed,
                        list(row.get("history") or []),
                        {"question": message, "answer": answer},
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
            gateway = SemanticTools(query, actor, user_message=message)
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
                "history": row["history"],
                "message": message,
                "releaseDigest": query.bundle.digest,
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
                                {"query": gateway.pending.get("query")},
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
                        browser_answer = attach_lineage(gateway.answer, query.bundle)
                        try:
                            await asyncio.to_thread(
                                self.store.save,
                                actor,
                                row,
                                item["history"],
                                {"question": message, "answer": browser_answer},
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

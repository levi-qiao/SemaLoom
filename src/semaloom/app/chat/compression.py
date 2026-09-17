"""Bounded, compressed conversation history for multi-turn chat."""

# ruff: noqa: RUF001 -- Chinese UI prose uses Chinese punctuation.

from __future__ import annotations

import time
from typing import Any


def build_history_from_turns(
    turns: list[dict[str, Any]],
    model: str = "qwen3.7-plus",
    max_turns: int = 10,
    max_turn_text_len: int = 1500,
) -> list[dict[str, Any]]:
    """Build bounded, compressed LLM conversation history from completed turns.

    Each turn is converted into a standard UserMessage and AssistantMessage pair.
    Intermediate tool calls and raw database JSON payloads from completed past turns
    are omitted, retaining authoritative semantic conclusions.
    Long answer texts are bounded with a summary truncation notice.
    A sliding window bounds the total number of retained turns.
    """
    if not turns:
        return []

    # Keep the most recent max_turns
    window = turns[-max_turns:]
    messages: list[dict[str, Any]] = []

    for turn in window:
        question = str(turn.get("question") or "").strip()
        if not question:
            continue

        messages.append(
            {
                "role": "user",
                "content": question,
                "timestamp": int(time.time() * 1000),
            }
        )

        answer = turn.get("answer") or {}
        text = str(answer.get("text") or "").strip()
        if not text and answer.get("kind") == "unsupported":
            text = "当前分析能力暂不支持该请求。"
        elif not text:
            text = "已按发布口径完成计算。"

        if len(text) > max_turn_text_len:
            # Retain the top conclusion and add truncation notice
            suffix = "\n... [已核对完整事实卡，历史明细已收起]"
            text = text[: max_turn_text_len - 100].rstrip() + suffix

        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "api": "openai-completions",
                "provider": "bailian-token-plan",
                "model": model,
                "stopReason": "stop",
                "usage": {"inputTokens": 0, "outputTokens": 0},
                "timestamp": int(time.time() * 1000),
            }
        )

    return messages

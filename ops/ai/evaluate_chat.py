"""Bounded live Chat evaluation against direct semantic API results.

Cases contain id/question and either kind=clarification or a SemanticQuery.
Reports contain only verdicts, never API keys, questions or business values.
The oracle checks engine evidence, not the truth of arbitrary model prose.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx


def verdict(answer: dict[str, Any], oracle: dict[str, Any] | None, kind: str) -> str:
    analyses = [
        item.get("result", {})
        for item in answer.get("evidence", [])
        if item.get("tool") == "prepare_semantic_query"
    ]
    if oracle is None:
        return (
            "PASS"
            if answer.get("kind") == kind and not analyses
            else "WRONG_ANSWER_KIND_OR_UNREQUESTED_ANALYSIS"
        )
    if answer.get("kind") != kind or not analyses:
        return "MISSING_OR_MISMATCHED_ENGINE_EVIDENCE"
    keys = ("values", "scope", "releaseDigest")
    if all(all(result.get(k) == oracle.get(k) for k in keys) for result in analyses):
        return "PASS"
    return "CONFLICTING_OR_MISMATCHED_ENGINE_EVIDENCE"


def _oracle(client: httpx.Client, query: dict[str, Any]) -> dict[str, Any]:
    prepared = client.post("/v0.1/semantic/prepare", json=query)
    prepared.raise_for_status()
    body = prepared.json()
    if body.get("status") != "READY" or not body.get("plan"):
        raise ValueError("ORACLE_PREPARE_NOT_READY")
    executed = client.post("/v0.1/semantic/execute", json=body["plan"])
    executed.raise_for_status()
    return executed.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-calls", type=int, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    if not 1 <= args.max_calls <= 20 or len(cases) > args.max_calls:
        parser.error("1..20 calls per run; case count must not exceed --max-calls")
    token = os.getenv("SEMALOOM_TOKEN", "tenant-a-analyst")
    rows = []
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=200
    ) as client:
        for case in cases:
            oracle = None
            if "query" in case:
                oracle = _oracle(client, case["query"])
            try:
                response = client.post("/v0.1/chat/turns", json={"message": case["question"]})
                response.raise_for_status()
                events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
                answer = next((e["answer"] for e in events if e["type"] == "answer"), None)
                outcome = (
                    verdict(answer, oracle, case.get("kind", "answer"))
                    if answer
                    else "NO_VALIDATED_ANSWER"
                )
                tools = sum(e.get("stage") == "tool" for e in events)
                rows.append((case["id"], outcome, tools))
            except (httpx.HTTPError, ValueError, KeyError):
                rows.append((case["id"], "TRANSPORT_OR_SCHEMA_FAILURE", 0))
            print(case["id"], rows[-1][1], flush=True)
    report = (
        "# Live Chat evaluation\n\n| Case | Engine evidence verdict | Tool calls |\n|---|---|---|\n"
    )
    report += "\n".join(
        f"| {identity} | {outcome} | {count} |" for identity, outcome, count in rows
    )
    report += (
        "\n\nProse accuracy requires separate review. "
        "Sequential live reads are not a source snapshot.\n"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
    if any(row[1] != "PASS" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

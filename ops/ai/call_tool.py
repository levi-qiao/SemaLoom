"""Invoke SemaLoom's read-only tool catalog from any terminal-capable AI host."""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", nargs="?", default="list")
    args = parser.parse_args()
    base = os.getenv("SEMALOOM_URL", "http://127.0.0.1:8000")
    token = os.getenv("SEMALOOM_TOKEN", "tenant-a-analyst")
    with httpx.Client(
        base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=20
    ) as client:
        response = client.get("/v0.1/agent/tools")
        response.raise_for_status()
        catalog = response.json()
        if args.tool == "list":
            print(json.dumps(catalog, ensure_ascii=False))
            return
        tool = next((item for item in catalog["tools"] if item["name"] == args.tool), None)
        if tool is None:
            parser.error("unknown read-only tool")
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            parser.error("stdin must contain a JSON object")
        # Only catalog routes are dispatched. Model arguments never select an endpoint.
        response = client.request(
            tool["method"],
            tool["path"],
            params=payload if tool["method"] == "GET" else None,
            json=payload if tool["method"] == "POST" else None,
        )
        print(json.dumps(response.json(), ensure_ascii=False))
        if not response.is_success:
            raise SystemExit(1)


if __name__ == "__main__":
    main()

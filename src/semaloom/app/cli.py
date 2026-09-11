"""Command-line entry for identity and the local HTTP composition root."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from semaloom.identity import build_identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semaloom",
        description="SemaLoom local development entry",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("identity", help="Print runtime build identity as JSON")
    serve = subparsers.add_parser("serve", help="Start the local-development HTTP entry")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    command = args.command or "identity"
    if command == "identity":
        payload = build_identity()
        json.dump(payload.to_dict(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if command == "serve":
        import uvicorn

        uvicorn.run(
            "semaloom.app.factory:create_app",
            factory=True,
            host=args.host,
            port=args.port,
        )
        return 0
    parser.error(f"unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

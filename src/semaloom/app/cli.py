"""Command-line entry for identity and the local HTTP composition root."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

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
    compile_cmd = subparsers.add_parser(
        "compile", help="Compile domain packs into an immutable bundle"
    )
    compile_cmd.add_argument("paths", nargs="+", type=Path)
    subparsers.add_parser("load-fixtures", help="Load synthetic PostgreSQL fixtures")
    query_cmd = subparsers.add_parser("query", help="Run a semantic metric point query")
    query_cmd.add_argument("--metric", required=True)
    query_cmd.add_argument(
        "--binding",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Semantic binding; repeat for each business key or perspective",
    )
    query_cmd.add_argument("--period-from", required=True)
    query_cmd.add_argument("--period-to", required=True)
    query_cmd.add_argument("--tenant", default="tenant-a")
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
    if command == "compile":
        from semaloom.compiler import compile_paths

        result = compile_paths(list(args.paths))
        report: dict[str, object] = {
            "ok": result.ok,
            "digest": None if result.bundle is None else result.bundle.digest,
            "onlineValidation": result.online_validation,
            "diagnostics": [item.model_dump() for item in result.diagnostics],
        }
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if result.ok else 1
    if command == "load-fixtures":
        from semaloom.runtime.fixtures import load_synthetic

        load_synthetic()
        sys.stdout.write("loaded synthetic fixtures\n")
        return 0
    if command == "query":
        from semaloom.app.bootstrap import build_services
        from semaloom.core.results import MetricSelect, QueryContext, QueryRequest
        from semaloom.runtime.auth import RequestActor

        try:
            bindings = _parse_bindings(args.binding)
        except ValueError as exc:
            parser.error(str(exc))
        services = build_services(load_data=False)
        envelope = services.query_active(args.tenant).execute(
            QueryRequest(
                api_version="semaloom/v0.1",
                select=(
                    MetricSelect(
                        metric=args.metric,
                        bindings=bindings,
                    ),
                ),
                context=QueryContext(
                    business_period={"from": args.period_from, "to": args.period_to}
                ),
            ),
            RequestActor(tenant=args.tenant, subject="cli", roles=("analyst",)),
        )
        json.dump(
            envelope.model_dump(mode="json", by_alias=True), sys.stdout, indent=2, sort_keys=True
        )
        sys.stdout.write("\n")
        return 0 if envelope.status == "SUCCEEDED" else 1
    parser.error(f"unknown command: {command}")
    return 2


def _parse_bindings(raw: list[str]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for item in raw:
        key, separator, value = item.partition("=")
        if not separator or not key or not value:
            raise ValueError(f"invalid --binding {item!r}; expected KEY=VALUE")
        if key in bindings:
            raise ValueError(f"duplicate --binding key {key!r}")
        bindings[key] = value
    if not bindings:
        raise ValueError("at least one --binding KEY=VALUE is required")
    return bindings


if __name__ == "__main__":
    raise SystemExit(main())

# SemaLoom

[![CI](https://github.com/levi-qiao/SemaLoom/actions/workflows/ci.yml/badge.svg)](https://github.com/levi-qiao/SemaLoom/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.13-3776AB.svg)](pyproject.toml)

**A protocol-neutral enterprise business layer for AI agents and applications.**

SemaLoom compiles business objects, metrics, rules, policies, and controlled actions into immutable
semantic releases. Domain packs own business meaning. Independent integration bindings and adapters
own tables, APIs, credentials, and vendor details. The runtime composes bounded cross-source reads
inside one Python application process.

The repository is a **pre-alpha synthetic proof of concept**. Tax and procurement are examples used
to test reuse; neither domain is built into the core.

![SemaLoom Studio entity graph and inspector](https://raw.githubusercontent.com/levi-qiao/SemaLoom/main/docs/assets/studio-overview.png)

## What works

- Deterministic compilation of two synthetic domain packs.
- PostgreSQL metric and object reads with tenant filters and typed evidence.
- In-process links across databases using declared business identities (first identity key only).
- Exact-decimal numeric rules with distinct TRUE, FALSE, UNKNOWN, and operational failure outcomes.
- Immutable semantic candidate validation, independent approval and release activation, plus a
  plan/approve/execute prototype that writes an in-process draft store.
- Read-only OpenAPI mappings and disjoint PostgreSQL/API properties for the same entity, composed
  inside the Python process.
- FastAPI endpoints and an embedded Studio for graph/inspection, Metric editing, structured
  versioned drafts, mapping/source administration, physical source trace, and review/publish
  history on synthetic data.

Not in this tree: production identity (local demo tokens only; other profiles refuse to start),
MCP SDK transport (`GET /v0.1/mcp/tools` is a static name list), composite-key query, BOOLEAN /
STRING / DATE rule execution, enterprise Action recovery, a finished structured Rule editor, and
the joint Studio gate. See [capabilities and limits](docs/capabilities.md).

For the implemented read-only business-analysis flow, HTTP tool schemas and AI host instructions,
see [AI analysis](docs/ai-analysis.md).

## Quickstart

Requires Python 3.13, [uv](https://docs.astral.sh/uv/), and PostgreSQL 16 on loopback. Docker
Compose **or** Homebrew `postgresql@16` with role `semaloom` are equivalent isolated fixtures.
Do not use private sample databases or a model key.

```bash
uv sync --frozen
docker compose up -d --wait   # skip when Homebrew PostgreSQL already has the four synthetic DBs
uv run semaloom load-fixtures
uv run semaloom compile examples/tax examples/procurement
uv run semaloom query \
  --metric tax.reportedIncome \
  --binding taxpayer=TAXPAYER-A \
  --binding taxYear=2024 \
  --binding perspective=TAX_RETURN \
  --period-from 2024-01-01 \
  --period-to 2025-01-01
uv run semaloom serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/studio/?view=objects&entity=tax.Taxpayer`. Expected query value is the
synthetic decimal `110.1000`. Demo bearer `tenant-a-analyst` is local-dev only. Five example
classes (Query, Evidence, policy period switch, missing/UNKNOWN, draft Action) are in the
[quickstart](docs/quickstart.md).

## Architecture and contribution

- [Architecture](docs/architecture.md) — stable boundaries and decisions.
- [Semantic contract](docs/spec/semantic-contract-v0.1.md) — observable semantics and diagnostics.
- [Studio design](docs/DESIGN.md) — information architecture, interaction, and visual system.
- [Plan](docs/PLAN.md) — implemented slices and remaining gates.
- [Contributing](CONTRIBUTING.md) — development workflow and checks.
- [Security](SECURITY.md) — trust boundaries and private reporting.

Apache-2.0 licensed. See [LICENSE](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md),
[Code of Conduct](CODE_OF_CONDUCT.md), and [Support](SUPPORT.md).

Optional Studio Chat, pi harness setup and provider integration: [Chat Harness](docs/chat-harness.md).

对象集合统计、可读证据和全链路验收：[分析质量与测试任务](docs/analysis-quality.md)。

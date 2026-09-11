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
- In-process links across databases using declared business identities.
- Exact-decimal rules with distinct TRUE, FALSE, UNKNOWN, and operational failure outcomes.
- Immutable release activation and a controlled plan/approve/execute action lifecycle prototype.
- FastAPI endpoints and an embedded Studio prototype for graph, inspector, mapping, and draft views.

Production identity, arbitrary OpenAPI sources, complete Studio publishing, and real enterprise pilots
remain open work. See [capabilities and limits](docs/capabilities.md) for the exact boundary.

## Quickstart

Requires Python 3.13, [uv](https://docs.astral.sh/uv/), and Docker:

```bash
uv sync --frozen
docker compose up -d --wait
uv run semaloom load-fixtures
uv run semaloom compile examples/tax examples/procurement
uv run semaloom query \
  --metric tax.reportedIncome \
  --binding taxpayer=TAXPAYER-A \
  --binding taxYear=2024 \
  --binding perspective=TAX_RETURN \
  --period-from 2024-01-01 \
  --period-to 2025-01-01
uv run semaloom serve
```

Open `http://127.0.0.1:8000/studio/`. The local profile uses documented synthetic credentials and
must not be exposed as production authentication. Full setup and cleanup steps are in the
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

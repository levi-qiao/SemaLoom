# Synthetic quickstart

The quickstart uses synthetic data only. It needs Python 3.13, uv, Docker, Node 22, and Corepack;
no model key or paid service is required.

## Run the backend and Studio

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

The API is at `http://127.0.0.1:8000`; Studio is at `/studio/`. The demo bearer
`tenant-a-analyst` is accepted only by the local-development application. The current Studio bundle
uses it for its synthetic read-only views.

Each logical source has its own environment binding. Override any source independently with
`SEMALOOM_TAX_DATABASE_URL`, `SEMALOOM_ORDERS_DATABASE_URL`,
`SEMALOOM_SUPPLIERS_DATABASE_URL`, or `SEMALOOM_META_DATABASE_URL`.

## Rebuild Studio assets

```bash
cd frontend
corepack enable
corepack install
pnpm install --frozen-lockfile
pnpm check
pnpm build
```

The Vite build writes versioned assets into `src/semaloom/app/static/`, so the Python wheel serves
Studio without a second deployment.

## Verify and clean up

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
docker compose down
```

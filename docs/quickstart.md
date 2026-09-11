# Synthetic quickstart

Requires Python 3.13, uv, and local PostgreSQL on `127.0.0.1:5432` (peer/trust as the OS user is enough). No paid APIs or model keys.

```bash
uv sync --frozen
psql -h 127.0.0.1 -d postgres -c "CREATE DATABASE semaloom_tax;"
psql -h 127.0.0.1 -d postgres -c "CREATE DATABASE semaloom_orders;"
psql -h 127.0.0.1 -d postgres -c "CREATE DATABASE semaloom_suppliers;"
psql -h 127.0.0.1 -d postgres -c "CREATE DATABASE semaloom_meta;"
uv run semaloom load-fixtures
uv run semaloom compile examples/tax examples/procurement
uv run semaloom query --metric tax.reportedIncome --taxpayer TAXPAYER-A --year 2024 --perspective TAX_RETURN
uv run pytest
```

Local HTTP (demo tokens only, not production auth):

```bash
uv run semaloom serve
# Authorization: Bearer tenant-a-analyst
# POST /v0.1/query
```

Studio static UI is served at `/studio/` after `frontend` is built (`pnpm install && pnpm build` in `frontend/`).

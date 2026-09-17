# Synthetic quickstart

This path uses **synthetic tax and procurement fixtures only**. It needs Python 3.13 and
[uv](https://docs.astral.sh/uv/). PostgreSQL 16 must listen on `127.0.0.1:5432` with role
`semaloom` / password `semaloom` and four empty databases: `semaloom_tax`, `semaloom_orders`,
`semaloom_suppliers`, and `semaloom_meta`.

Use Docker Compose **or** an equivalent local Homebrew `postgresql@16`. Do not point the URLs at a
private sample database, a remote host, or any real business database. No model key, MCP SDK, or
paid service is required.

Default bindings:

```text
SEMALOOM_PROFILE=local-dev
SEMALOOM_TAX_DATABASE_URL=postgresql+psycopg://semaloom:semaloom@127.0.0.1:5432/semaloom_tax
SEMALOOM_ORDERS_DATABASE_URL=postgresql+psycopg://semaloom:semaloom@127.0.0.1:5432/semaloom_orders
SEMALOOM_SUPPLIERS_DATABASE_URL=postgresql+psycopg://semaloom:semaloom@127.0.0.1:5432/semaloom_suppliers
SEMALOOM_META_DATABASE_URL=postgresql+psycopg://semaloom:semaloom@127.0.0.1:5432/semaloom_meta
```

`load-fixtures` **drops and recreates** the synthetic business tables in those four databases. Do
not run it against any other database.

## Start PostgreSQL

Docker Compose (ephemeral tmpfs; Docker daemon required):

```bash
docker compose up -d --wait
```

Homebrew `postgresql@16` already listening on loopback is an equivalent isolated fixture. Create
the role and databases once if they do not exist:

```bash
createuser -h 127.0.0.1 --login semaloom || true
psql -h 127.0.0.1 -d postgres -c "ALTER USER semaloom PASSWORD 'semaloom';"
for database in semaloom_tax semaloom_orders semaloom_suppliers semaloom_meta; do
  createdb -h 127.0.0.1 -U semaloom "$database" || true
done
```

## Run the backend and Studio

From a git checkout:

```bash
uv sync --frozen
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

Compile prints `"ok": true` and a 64-character digest; `onlineValidation` is `NOT_RUN` for this
offline compile. Query prints `"status": "SUCCEEDED"` and a `PRESENT` observation whose `value` is
the synthetic decimal `110.1000`. `requestId` / `observedAt` / `releaseDigest` change per process
and active release; do not treat them as golden constants.

The API is at `http://127.0.0.1:8000`. Studio is the same process at `/studio/` (no separate
frontend production server). Deep link:

`http://127.0.0.1:8000/studio/?view=objects&entity=tax.Taxpayer`

The response is the shipped Studio HTML shell (`SemaLoom Studio` plus `/studio/assets/*.js` and
`*.css`), not a JSON/HTML 404 from `/v0.1/query`.

Local-dev **demo bearers** (never production authentication):

| Bearer token | Roles |
| --- | --- |
| `tenant-a-analyst` | analyst |
| `tenant-a-approver` | approver, analyst |
| `tenant-a-reviewer` | reviewer, model-viewer |
| `tenant-a-publisher` | publisher, model-viewer |
| `tenant-a-modeler` | modeler |

Studio can also switch documented local personas through `POST /v0.1/studio/session/demo`. Setting
`SEMALOOM_PROFILE` to anything other than `local-dev` refuses to start: there is no production
identity adapter yet.

`GET /v0.1/mcp/tools` after a demo Bearer returns a **static name list**. It is not an MCP SDK
session or transport.

Business discovery uses the tenant's active release and returns semantic definitions, not physical
source bindings. Search is deterministic ID/label/description matching; multiple candidates require
an explicit selection:

```bash
curl --get 'http://127.0.0.1:8000/v0.1/describe' \
  -H 'Authorization: Bearer tenant-a-analyst' --data-urlencode 'semanticId=tax.reportedIncome'
curl --get 'http://127.0.0.1:8000/v0.1/search' \
  -H 'Authorization: Bearer tenant-a-analyst' --data-urlencode 'q=收入'
```

Query, claim and discovery also accept the existing Studio session. Cookie-authenticated POSTs
require the same Origin/CSRF headers as Studio management; an invalid explicit Bearer does not
fall back to the session. This is local session reuse, not production JWT authentication.

## Five runnable example classes

Start `uv run semaloom serve --host 127.0.0.1 --port 8000` first for the HTTP examples. Values below
are from the public synthetic fixtures, not private financial rows.

### 1. Query

CLI (same as above) or:

```bash
curl -sS http://127.0.0.1:8000/v0.1/query \
  -H 'Authorization: Bearer tenant-a-analyst' \
  -H 'Content-Type: application/json' \
  -d '{
    "metric": "tax.reportedIncome",
    "bindings": {"taxpayer": "TAXPAYER-A", "taxYear": 2024, "perspective": "TAX_RETURN"},
    "periodFrom": "2024-01-01",
    "periodTo": "2025-01-01"
  }'
```

Expected: HTTP 200, `status=SUCCEEDED`, `observations[0].kind=PRESENT`,
`observations[0].value=110.1000`, `observations[0].target=tax.reportedIncome`. SQL, destination
URLs, and caller-asserted permissions are rejected (`400` / `INVALID_REQUEST`).

A second domain on the same interface:

```bash
curl -sS http://127.0.0.1:8000/v0.1/query \
  -H 'Authorization: Bearer tenant-a-analyst' \
  -H 'Content-Type: application/json' \
  -d '{
    "metric": "procurement.orderAmount",
    "bindings": {"orderId": "PO-001"},
    "periodFrom": "2024-01-01",
    "periodTo": "2025-01-01"
  }'
```

Expected: `PRESENT` value `1200.0000`.

### 2. Explain / Evidence

Use the tax query response. Expected: `sourceActivities` is non-empty,
`sourceActivities[0].mappingId=tax.reportedIncome.pg`,
`sourceActivities[0].sourceId=tax_pg`, and the payload does not include SQL text or table names.
This is Evidence on the query envelope; there is no separate `/explain` route.

### 3. Policy period switch

```bash
curl -sS http://127.0.0.1:8000/v0.1/claims/evaluate \
  -H 'Authorization: Bearer tenant-a-analyst' \
  -H 'Content-Type: application/json' \
  -d '{
    "claimId": "tax.incomeReconciles",
    "bindings": {"taxpayer": "TAXPAYER-A", "taxYear": 2024},
    "periodFrom": "2024-01-01",
    "periodTo": "2025-01-01",
    "dimensions": {"jurisdiction": "CN"}
  }'
```

Expected: HTTP 200, `claim.context.policyId=tax.incomeReconcilesY2024`, `claim.truth=TRUE`.

Repeat with `taxYear=2025`, `periodFrom=2025-01-01`, `periodTo=2026-01-01`. Expected:
`policyId=tax.incomeReconcilesY2025`, `claim.truth=UNKNOWN`, reason includes `NULL_INPUT`
(synthetic 2025 audit income is null; UNKNOWN is not FALSE).

A period that straddles both policies (`periodFrom=2024-06-01`, `periodTo=2025-06-01`) returns HTTP
`422` with `POLICY_PERIOD_SPLIT_REQUIRED`.

### 4. Missing vs UNKNOWN

Missing observation (no synthetic row):

```bash
uv run semaloom query \
  --metric tax.reportedIncome \
  --binding taxpayer=TAXPAYER-B \
  --binding taxYear=2025 \
  --binding perspective=TAX_RETURN \
  --period-from 2025-01-01 \
  --period-to 2026-01-01
```

Expected: `status=SUCCEEDED`, `observations[0].kind=MISSING`, `reason=NO_ROW`, `value=null`. This is
not UNKNOWN and not FALSE.

UNKNOWN claim: the 2025 `tax.incomeReconciles` evaluate above. Missing data, a FALSE business claim,
and an operational error are distinct outcomes.

### 5. Draft Action loop

The executor writes an **in-process DraftStore**. Restarting the process loses those drafts; this is
not enterprise write recovery.

```bash
curl -sS http://127.0.0.1:8000/v0.1/actions/plan \
  -H 'Authorization: Bearer tenant-a-analyst' \
  -H 'Content-Type: application/json' \
  -d '{
    "actionId": "tax.CreateTaxAdjustmentDraft",
    "target": {"taxpayerId": "TAXPAYER-A"},
    "parameters": {"amount": "10.00", "taxYear": "2024"}
  }'
```

Expected: HTTP 200 and a `planId`. The same analyst calling `/v0.1/actions/approve` with that
`planId` returns `403`. Extra fields such as `"approved": true` return `422`. Execute before approve
returns `403` / `UNAPPROVED`.

Approve as `Bearer tenant-a-approver`, then execute as the analyst. Expected: execute HTTP 200 with
`status=VERIFIED`. `GET /v0.1/actions/{planId}` then returns the same `VERIFIED` status.

## Install a built wheel

The wheel serves the prebuilt Studio assets from `semaloom/app/static`. Domain packs stay in the
git checkout (or the sdist `examples/` tree); they are not inside the wheel.

```bash
uv build --out-dir dist
uv venv --python 3.13 .venv-dist
uv pip install --python .venv-dist/bin/python dist/semaloom-0.1.0-py3-none-any.whl
export SEMALOOM_PACK_PATHS="$PWD/examples/tax:$PWD/examples/procurement"
.venv-dist/bin/semaloom serve --host 127.0.0.1 --port 8011
```

Open `http://127.0.0.1:8011/studio/?view=objects&entity=tax.Taxpayer`. Node is not required to run
an installed wheel.

## Rebuild Studio assets (UI contributors)

```bash
cd frontend
corepack enable
corepack install
pnpm install --frozen-lockfile
pnpm check
pnpm build
```

The Vite build writes versioned assets into `src/semaloom/app/static/`, so the Python wheel serves
Studio without a second deployment. Public runtime users who only install the wheel can skip Node.

## Verify and clean up

```bash
uv run pytest tests/test_packaging.py tests/test_docs.py tests/test_static.py
uv build
docker compose down   # only if you started Compose
```

Performance, production identity, real MCP transport, composite-key collection-analysis
joins, Action crash recovery, and a signed SBOM are **not** accepted on this path. Point
reads and Link traversal already preserve complete structured identities; see
[capabilities](capabilities.md).

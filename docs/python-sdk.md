# Embedded Python SDK

`semaloom.sdk` is the supported integration entry point for this pre-alpha. It embeds the existing
Compiler and read-only Runtime in your Python process. No Studio, HTTP server, model key, Node
process, metadata database or fixture initialization is required. Python 3.13+ is required.

Keep one `semaloom` distribution: `core` owns contracts, `compiler` owns semantic compilation,
`runtime` owns execution, and `adapters` own physical protocols. The SDK assembles these modules;
it does not implement another engine. The distribution still includes application dependencies
and Studio assets; this is not a separately published minimal `semaloom-core` package.

## Install and query

From a reviewed checkout, use `uv sync --frozen` for development or `uv build` to produce a wheel.
Install that wheel in the consuming project's environment with
`uv pip install --python .venv/bin/python /absolute/path/to/semaloom-0.1.0-py3-none-any.whl`.
These instructions do not imply that this version has been published to PyPI.

The example below reads the synthetic tax fixture described in [quickstart](quickstart.md).
Run it from the checkout after loading that fixture. In an integration, replace the pack path,
source binding and actor with your reviewed model, configured read-only source and authenticated
server-side identity. Neither tenant nor roles should come from an untrusted request body.

```python
import os
from pathlib import Path

from semaloom.adapters.postgres import PostgresReadProvider, engine_from_url
from semaloom.sdk import (
    MetricSelect,
    QueryContext,
    QueryRequest,
    RequestActor,
    SemanticEngine,
    compile_paths,
)

compiled = compile_paths([Path("examples/tax").resolve()])
if compiled.bundle is None:
    raise ValueError([d.model_dump() for d in compiled.diagnostics])

provider = PostgresReadProvider(
    {
        "tax_pg": engine_from_url(os.environ["SEMALOOM_TAX_DATABASE_URL"]),
    }
)
try:
    engine = SemanticEngine(compiled.bundle, provider)
    actor = RequestActor(tenant="tenant-a", subject="example", roles=("analyst",))
    result = engine.query(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=(
                MetricSelect(
                    metric="tax.reportedIncome",
                    bindings={
                        "taxpayerId": "TAXPAYER-A",
                        "taxYear": 2024,
                        "perspective": "TAX_RETURN",
                    },
                ),
            ),
            context=QueryContext(
                business_period={"from": "2024-01-01", "to": "2025-01-01"},
            ),
        ),
        actor=actor,
    )
    # A missing observation or failed execution is never a numeric zero.
    if result.status == "SUCCEEDED" and result.observations[0].kind == "PRESENT":
        print(result.observations[0].value)  # synthetic fixture: 110.1000
    else:
        print(result.status, [o.kind for o in result.observations])
finally:
    provider.close()
```

Providers belong to the host. Share and close them according to their own concurrency/lifecycle
contract; `SemanticEngine` does not close injected resources or create database tables. Calls are
synchronous: use the host framework's thread offloading when calling from an asynchronous server.

## Interface and outcomes

| Interface | Result |
| --- | --- |
| `compile_paths` / `compile_documents` | `CompileResult`: bundle or diagnostics; offline compilation is not approval or source validation |
| `SemanticEngine(bundle, provider)` | Checks bundle digest and format/IR compatibility; takes a private copy so caller mutations do not change its release |
| `query(QueryRequest, actor=...)` | `EvidenceEnvelope`: observations, diagnostics and source activities |
| `prepare(SemanticQuery, actor=...)` | `PrepareResult`: READY, NEEDS_INPUT, UNSUPPORTED or SOURCE_ERROR |
| `execute(PlanRef, actor=...)` | `QueryResult`; checks current role authorization, release and provider plan binding |
| `evaluate_claim(id, actor=..., bindings=..., period_from=..., period_to=..., dimensions=...)` | `EvidenceEnvelope` with Claim truth, inputs, diagnostics and source activities |
| `find_objects(ObjectSearchRequest, actor=...)` | Bounded exact-match page; `hasMore` does not prove completeness |
| `search(text, actor=...)` / `describe(id, actor=...)` | Authorized business definitions, not evidence of source data availability |

Inspect `prepared.status` before executing `prepared.plan`. NEEDS_INPUT requires an explicit
business choice; do not manufacture a plan or silently pick the first option. Missing data remains
MISSING/NULL; a rule can return UNKNOWN without an execution failure. Operational errors remain
diagnostics or `AnalysisError`/`EvaluationError`, and authorization failures remain FORBIDDEN or
`PermissionError`. Invalid model construction raises Pydantic validation errors. These are the
existing runtime outcomes, not a new SDK error taxonomy.

Pass the host's currently authenticated actor on every call. The existing role profile grants
tenant-scoped reads to analyst/buyer/approver; it is not per-resource enterprise authorization or
JWT verification. The host must approve the exact bundle and bind permitted sources. A digest
proves integrity, not provenance or permission. Construct a new engine for a new release;
do not reinterpret an old plan under another model. Evidence may contain source identifiers and
must be filtered before exposing it to untrusted consumers.

## New domains and protocols

New businesses within the supported semantic operators use domain YAML and integration mappings.
Labels, aliases, units, identities, dictionaries, grain, additivity, rules and policies carry business
meaning. They do not carry UI components or Python expressions. New protocols require trusted
adapter code satisfying `ReadProvider`; collection operations additionally need the existing
analysis-provider methods and their behavior guarantees. A point provider does not automatically
support collection analysis.

The shared compiler requires an explicit `MappingCompiler` from `semaloom.core.compilation`.
Its two operations validate mappings into neutral capabilities and derive metric bindings.
SDK compile helpers supply `BuiltinMappingCompiler` for PostgreSQL/OpenAPI by default and accept
`mapping_compiler=` for reviewed alternatives. There is no automatic plugin loading.

Migration from earlier internal imports: use `from semaloom.sdk import compile_paths,
compile_documents`; direct `semaloom.compiler` callers must now supply `mapping_compiler=`.
`document_schemas` remains available in both entries. Existing valid declarations retain the
same semantic format. Selectors lacking a physical binding or conflicting with fixed source
filters now fail compilation instead of being omitted/overwritten; fix and recompile those
declarations. SDK creation rejects unsupported format/IR versions and mutated bundles.

Natural-language interpretation still belongs to the optional Chat module. The SDK makes no
claim to understand arbitrary questions or validate source truth. Its initial public surface is
read-only; production IAM, enterprise Action recovery and remaining [acceptance](acceptance.md)
gates are not closed by embedding it.

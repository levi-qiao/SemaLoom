# Capabilities and limits (v0.1)

This repository is a pre-alpha implementation with public synthetic examples and an optional private local analysis sample. The table distinguishes executable code
from designed interfaces so downstream users do not depend on unimplemented guarantees.

| Area | Current capability | Boundary |
| --- | --- | --- |
| Compiler | Tax, procurement and financial-review domain packs compile to one immutable bundle with stable diagnostics | No external package registry or compatibility migration tool |
| Relational reads | PostgreSQL point reads, tenant filtering, exact cardinality, typed outcomes | No arbitrary joins, caller SQL, batching budget, or snapshot proof |
| Cross-source reads | Declared business links across separate PostgreSQL connections plus disjoint PostgreSQL/OpenAPI properties on one entity, composed in process | No arbitrary federated query language; OpenAPI profiles are fixed read-only GET contracts without a general spec importer |
| Identity keys | `ObjectType.identityKeys` may list more than one key | Point object reads and instance search require one stable scalar key. Composite object reads explicitly reject instead of silently choosing the first key; composite Link/Action identities remain unimplemented |
| Rules | Typed Decimal/INTEGER/BOOLEAN/STRING/DATE/DATETIME inputs and literals, bounded expressions, policy selection, deterministic derived Metrics and TRUE / FALSE / UNKNOWN | No Python `eval` / `exec`; no general-purpose rule language. Claim outputs must be boolean; invalid types fail compilation/read/evaluation |
| Releases | PostgreSQL candidate validation bound to exact source-profile revisions, independent approval bound to that validation, immutable publish history, and transactional tenant-scoped environment activation | Production identity provider, general migration tooling, and long-term audit retention policy remain open |
| Actions | Synthetic plan, approval binding, idempotent execution record, and status read against an in-process `DraftStore` | Not enterprise write recovery. Restarting the process loses in-memory drafts. Action version binding is not the tenant-activated release |
| HTTP | FastAPI query, claim, action, and Studio endpoints; business-only `/v0.1/describe` and bounded `/search` on the tenant release. Query/claim/discovery accept demo Bearer or the guarded Studio session; POST cookie requests require Origin/CSRF. Metric observations include declared units/types. `/objects/search` resolves bounded exact-filter instances; `/agent/tools` exposes five HTTP tool schemas | `/v0.1/mcp/tools` is a **static name list**, not an MCP SDK transport. Search is deterministic ID/label/description matching, not LLM retrieval; fine-grained resource authorization and historical discovery remain open. Anything other than `SEMALOOM_PROFILE=local-dev` refuses to start; there is no JWT issuer/audience/signature path |
| Studio | Embedded graph/directory, inspector, structured canonical drafts, Metric editor, mapping/source management, physical source trace, online validation, review/approval/publish, revision history, and deep links, exercised on public synthetic packs and a private local financial sample | Structured Rule editor is not available. The joint Studio gate (A64–A69) is not closed. No general OpenAPI discovery wizard, collaborative merge UI, or large-graph virtualization |

SemaLoom never accepts SQL, destination URLs, join expressions, or caller-asserted permissions as
agent query inputs. Production identity, independently audited source values, operational recovery, large-scale
capacity claims, signed SBOMs, package signatures, and pilot results are outside the current
evidence.

Runtime dependencies are the locked set in `uv.lock` (inspect with `uv export --frozen --no-dev`).
The project license is Apache-2.0; Studio's bundled React assets are listed in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). This pre-alpha does not publish a signed SBOM
or provenance attestation.

Current business-analysis scope, observed verification and AI integration instructions: [AI analysis](ai-analysis.md). Instance search supports one mapping, exact filters and a capped first page with `hasMore`; it is not full-text or whole-population analytics. Metric grain is required. Objects declaring DATE `period` properties enforce exact half-open period matching for their Metrics. Source reads do not promise a cross-request database snapshot.

Optional embedded Chat now uses official pi core hooks and a server-owned semantic plugin, with streamed progress, cancellation, actor-owned PostgreSQL history and deterministic evidence cards. It needs an explicitly configured provider plus Node only when enabled. Native MCP transport and production JWT remain unimplemented. See [Chat Harness](chat-harness.md).

年度集合分析：对显式声明 Metric.population 的指标支持均值、合计、极值、有效计数及三种明确分母的比较；完整对象集合最多 50 个，超限拒绝，无任意 SQL/group-by/全局快照。Chat 证据表格和图谱工具可用，独立测试与限制见 [分析质量](analysis-quality.md)。

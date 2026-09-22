# Capabilities and limits (v0.1)

This repository is a pre-alpha implementation with public synthetic examples. The table distinguishes executable code
from designed interfaces so downstream users do not depend on unimplemented guarantees.

| Area | Current capability | Boundary |
| --- | --- | --- |
| Compiler | Tax, procurement and financial-review domain packs compile to one immutable bundle with stable diagnostics | No external package registry or compatibility migration tool |
| Python SDK | `semaloom.sdk.SemanticEngine` embeds discovery, point reads, prepare/execute and claims over a pinned release and caller-owned provider; compilation injects physical profile handling from adapters | Read-only, synchronous, pre-alpha; host authenticates each actor and approves releases. Existing coarse tenant/role authorization remains; no new production IAM or Action guarantee. See [SDK](python-sdk.md) |
| Relational reads | PostgreSQL point reads, tenant filtering, exact cardinality, typed outcomes | No arbitrary joins, caller SQL, batching budget, or snapshot proof |
| Cross-source reads | Declared business links across separate PostgreSQL connections plus disjoint PostgreSQL/OpenAPI properties on one entity, composed in process | No arbitrary federated query language; OpenAPI profiles are fixed read-only GET contracts without a general spec importer |
| Identity keys | `ObjectType.identityKeys` may contain multiple keys. Point reads, instance search, Studio previews, AI tool calls, Link traversal, and Action targets preserve the complete structured identity; Link definitions must cover every target identity key exactly once | Collection-analysis joins (same-source SQL and cross-source bind) still require a single Link identity pair and reject composite Links with `LINK_ANALYSIS_UNSUPPORTED` instead of truncating them |
| Rules | Typed Decimal/INTEGER/BOOLEAN/STRING/DATE/DATETIME inputs and literals, bounded expressions, policy selection, deterministic derived Metrics and TRUE / FALSE / UNKNOWN | No Python `eval` / `exec`; no general-purpose rule language. Claim outputs must be boolean; invalid types fail compilation/read/evaluation |
| Releases | PostgreSQL candidate validation bound to exact source-profile revisions, independent approval bound to that validation, immutable publish history, and transactional tenant-scoped environment activation | Production identity provider, general migration tooling, and long-term audit retention policy remain open |
| Actions | Synthetic plan, approval binding, idempotent execution record, and status read against an in-process `DraftStore` | Not enterprise write recovery. Restarting the process loses in-memory drafts. Action version binding is not the tenant-activated release |
| HTTP / MCP | FastAPI query, claim, action, and Studio endpoints; official MCP SDK stateless Streamable HTTP at `/mcp/` for semantic query, claim evaluation, and semantic explain. Both transports share one bearer verifier. `local-dev` accepts only explicit demo tokens; other profiles require signed JWT configuration and validate signature, issuer, audience, expiry, subject, tenant, and roles. Guarded Studio sessions retain Origin/CSRF checks. | `/v0.1/mcp/tools` remains a compatibility catalog, not the transport. Search is deterministic ID/label/description matching, not LLM retrieval; MCP Actions, fine-grained resource authorization, revocation-directory integration, and historical discovery remain open. |
| Studio | Embedded graph/directory, inspector, structured canonical drafts, entity attribute/mapping editors (optional Metric vocabulary entries, no standalone Metric modeling center), source management, physical source trace, online validation, review/approval/publish, revision history, and deep links | Structured Rule editor is not available. The joint Studio gate (A64–A69) is not closed. Declared ONE same-source Links support collection group/filter by related attributes; many-to-many and cross-source JOIN are not open. No general OpenAPI discovery wizard, collaborative merge UI, or large-graph virtualization |

SemaLoom never accepts SQL, destination URLs, join expressions, or caller-asserted permissions as
agent query inputs. Production identity, independently audited source values, operational recovery, large-scale
capacity claims, signed SBOMs, package signatures, and pilot results are outside the current
evidence.

Runtime dependencies are the locked set in `uv.lock` (inspect with `uv export --frozen --no-dev`).
The project license is Apache-2.0; Studio's bundled React assets are listed in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). This pre-alpha does not publish a signed SBOM
or provenance attestation.

Current business-analysis scope, observed verification and AI integration instructions: [AI analysis](ai-analysis.md). Instance search supports one mapping, exact filters and a capped first page with `hasMore`; it is not full-text or whole-population analytics. Metric grain is required. Objects declaring DATE `period` properties enforce exact half-open period matching for their Metrics. Source reads do not promise a cross-request database snapshot.

Optional embedded Chat now uses official pi core hooks and a server-owned semantic plugin, with streamed progress, cancellation, actor-owned PostgreSQL history and deterministic evidence cards. It needs an explicitly configured provider plus Node only when enabled. Chat is separate from the native MCP endpoint and shares the same server-owned semantic/runtime authority. See [Chat Harness](chat-harness.md).

同源同事实表集合分析：对声明 Metric.population 的指标支持过滤、SUM/AVG/MIN/MAX/COUNT、分组，以及 `VALUE` / `RATIO` / `DIFFERENCE` 公式。占比、相对均值、同行计数和上一观测期都是这些公式的结果，不是请求枚举。测量槽声明 Kimball 可加性（默认 FULL；库存/余额 SEMI 不得跨年 SUM）。已声明、基数 ONE、单字段 identity 的 PostgreSQL Link 可用于按关联对象属性分组/筛选：同源 LEFT JOIN；跨源由引擎按业务键分批对齐。声明 `collection: true` 但基数不是 ONE 或身份不是单字段的 Link，在编译期拒绝，并写明缺少展开策略或不支持的身份。证据明细每指标最多 50 行分页，不截断总体聚合；单请求最多 8 个指标、8 个分组键、1000 个结果分组。Chat 仅 `prepare_semantic_query`；HTTP 为 `/v0.1/semantic/prepare` 与 execute。无任意 SQL/全局跨源快照。详见 [分析质量](analysis-quality.md)、[ADR-0013](adr/0013-measure-additivity.md)、[ADR-0014](adr/0014-ontology-dictionaries.md) 与 [ADR-0017](adr/0017-compositional-analysis.md)。

**Metric**：查询与发现的一级公民（稳定 ID）；作者面以测量槽 + 可选词条为主，见 [ADR-0012](adr/0012-facts-and-business-vocabulary.md) 与 [CONTEXT](../CONTEXT.md)。

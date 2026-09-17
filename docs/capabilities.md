# Capabilities and limits (v0.1)

This repository is a pre-alpha implementation with public synthetic examples and an optional private local analysis sample. The table distinguishes executable code
from designed interfaces so downstream users do not depend on unimplemented guarantees.

| Area | Current capability | Boundary |
| --- | --- | --- |
| Compiler | Tax, procurement and financial-review domain packs compile to one immutable bundle with stable diagnostics | No external package registry or compatibility migration tool |
| Relational reads | PostgreSQL point reads, tenant filtering, exact cardinality, typed outcomes | No arbitrary joins, caller SQL, batching budget, or snapshot proof |
| Cross-source reads | Declared business links across separate PostgreSQL connections plus disjoint PostgreSQL/OpenAPI properties on one entity, composed in process | No arbitrary federated query language; OpenAPI profiles are fixed read-only GET contracts without a general spec importer |
| Identity keys | `ObjectType.identityKeys` may contain multiple keys. Point reads, instance search, Studio previews, AI tool calls, and Link traversal preserve the complete structured identity; Link definitions must cover every target identity key exactly once | Cross-source collection-analysis bind joins still require a single Link identity pair and reject composite Links explicitly instead of truncating them |
| Rules | Typed Decimal/INTEGER/BOOLEAN/STRING/DATE/DATETIME inputs and literals, bounded expressions, policy selection, deterministic derived Metrics and TRUE / FALSE / UNKNOWN | No Python `eval` / `exec`; no general-purpose rule language. Claim outputs must be boolean; invalid types fail compilation/read/evaluation |
| Releases | PostgreSQL candidate validation bound to exact source-profile revisions, independent approval bound to that validation, immutable publish history, and transactional tenant-scoped environment activation | Production identity provider, general migration tooling, and long-term audit retention policy remain open |
| Actions | Synthetic plan, approval binding, idempotent execution record, and status read against an in-process `DraftStore` | Not enterprise write recovery. Restarting the process loses in-memory drafts. Action version binding is not the tenant-activated release |
| HTTP | FastAPI query, claim, action, and Studio endpoints; business-only `/v0.1/describe` and bounded `/search` on the tenant release. Link/Metric discovery includes `analysisCapabilities` (`collectionJoin` is true only for declared ONE same-source PostgreSQL links). Query/claim/discovery accept demo Bearer or the guarded Studio session; POST cookie requests require Origin/CSRF. Metric observations include declared units/types. `/objects/search` resolves bounded exact-filter instances; `/agent/tools` exposes five HTTP tool schemas | `/v0.1/mcp/tools` is a **static name list**, not an MCP SDK transport. Search is deterministic ID/label/description matching, not LLM retrieval; fine-grained resource authorization and historical discovery remain open. Anything other than `SEMALOOM_PROFILE=local-dev` refuses to start; there is no JWT issuer/audience/signature path |
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

Optional embedded Chat now uses official pi core hooks and a server-owned semantic plugin, with streamed progress, cancellation, actor-owned PostgreSQL history and deterministic evidence cards. It needs an explicitly configured provider plus Node only when enabled. Native MCP transport and production JWT remain unimplemented. See [Chat Harness](chat-harness.md).

同源同事实表集合分析：对声明 Metric.population 的指标支持过滤、SUM/AVG/MIN/MAX/COUNT、分组、比较与选择题协议。已声明、基数 ONE 的 PostgreSQL Link 可用于按关联对象属性分组/筛选：同源 LEFT JOIN；跨源由引擎按业务键分批对齐，但目前仅支持单字段 Link identity，复合 Link 明确返回 `LINK_ANALYSIS_UNSUPPORTED`。一对多、非 PostgreSQL 目标、多跳与多指标联合排序/比较返回明确 UNSUPPORTED。证据明细每指标最多 50 行分页，不截断总体聚合；单请求预算见 [主责收口](semantic-query-closure.md)。Chat 仅 `prepare_semantic_query`；`POST /v0.1/analyze` 为废弃兼容翻译。无任意 SQL/全局跨源快照。详见 [分析质量](analysis-quality.md)。

**Metric**：查询与发现的一级公民（稳定 ID）；作者面以测量槽 + 可选词条为主，见 [ADR-0012](adr/0012-facts-and-business-vocabulary.md) 与 [CONTEXT](../CONTEXT.md)。

# Capabilities and limits (v0.1)

This repository is a synthetic pre-alpha implementation. The table distinguishes executable code
from designed interfaces so downstream users do not depend on unimplemented guarantees.

| Area | Current capability | Boundary |
| --- | --- | --- |
| Compiler | Tax and procurement domain packs compile to one immutable bundle with stable diagnostics | No external package registry or compatibility migration tool |
| Relational reads | PostgreSQL point reads, tenant filtering, exact cardinality, typed outcomes | No arbitrary joins, caller SQL, batching budget, or snapshot proof |
| Cross-source reads | Declared business links across separate PostgreSQL connections plus disjoint PostgreSQL/OpenAPI properties on one entity, composed in process | No arbitrary federated query language; OpenAPI profiles are fixed read-only GET contracts without a general spec importer |
| Rules | Bounded expression tree, Decimal arithmetic, policy period selection, TRUE/FALSE/UNKNOWN | No Python expression execution or general rules language |
| Releases | PostgreSQL candidate validation bound to exact source-profile revisions, independent approval bound to that validation, immutable publish history, and transactional tenant-scoped environment activation | Production identity provider, general migration tooling, and long-term audit retention policy remain open |
| Actions | Synthetic plan, approval binding, idempotent execution record, and status read | The example executor writes an in-memory draft store, not a real enterprise system |
| HTTP | FastAPI query, claim, action, and Studio endpoints; Studio uses an opaque server-side cookie session with Origin/CSRF enforcement | Local demo personas are disabled by the production profile; a production identity adapter and real MCP transport remain open |
| Studio | Embedded graph/directory, inspector, structured canonical drafts, import/export, mapping/source management, physical source trace, online validation, review/approval/publish, revision history, and responsive browser regression | Current UI and scale evidence use synthetic domain packs and local personas; no general OpenAPI discovery wizard, collaborative merge UI, or large-graph virtualization |

SemaLoom never accepts SQL, destination URLs, join expressions, or caller-asserted permissions as
agent query inputs. Real enterprise data, production identity, operational recovery, large-scale capacity
claims, and pilot results are outside the current evidence.

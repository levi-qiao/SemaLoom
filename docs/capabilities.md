# Capabilities and limits (v0.1)

This repository is a synthetic pre-alpha implementation. The table distinguishes executable code
from designed interfaces so downstream users do not depend on unimplemented guarantees.

| Area | Current capability | Boundary |
| --- | --- | --- |
| Compiler | Tax and procurement domain packs compile to one immutable bundle with stable diagnostics | No external package registry or compatibility migration tool |
| Relational reads | PostgreSQL point reads, tenant filtering, exact cardinality, typed outcomes | No arbitrary joins, caller SQL, batching budget, or snapshot proof |
| Cross-source reads | One declared business link across separate PostgreSQL connections, composed in process | No arbitrary federated query language; API read provider is not implemented |
| Rules | Bounded expression tree, Decimal arithmetic, policy period selection, TRUE/FALSE/UNKNOWN | No Python expression execution or general rules language |
| Releases | PostgreSQL publish and compare-and-swap environment activation | Synthetic publisher identity; migration and durable audit policy remain open |
| Actions | Synthetic plan, approval binding, idempotent execution record, and status read | The example executor writes an in-memory draft store, not a real enterprise system |
| HTTP | FastAPI query, claim, action, and Studio prototype endpoints | Demo bearer identities only; MCP endpoint describes tools but is not an MCP transport |
| Studio | Embedded graph, inspector, mapping list, and optimistic draft save prototype | Structured model editing, API mapping, source administration, secure session, validation, and publishing are not complete |

SemaLoom never accepts SQL, destination URLs, join expressions, or caller-asserted permissions as
agent query inputs. Real enterprise data, production identity, operational recovery, capacity claims,
and pilot results are outside the current evidence.

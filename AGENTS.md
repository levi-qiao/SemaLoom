# SemaLoom agent instructions

## Read by task

- Any implementation: read [CONTEXT.md](CONTEXT.md), [architecture](docs/architecture.md), and the assigned task in [PLAN](docs/PLAN.md). Work only on its declared scope and dependencies.
- DSL, compiler, query, provider, rules, policy or evidence: read [semantic contract](docs/spec/semantic-contract-v0.1.md) and the applicable cases in [acceptance](docs/acceptance.md).
- Authorization, data exposure, persistence or actions: also read [SECURITY.md](SECURITY.md). Action lifecycle and approval binding are defined in the semantic contract.
- Changing a settled architecture decision: read the linked ADR in architecture, record a replacement decision and its migration impact before implementation.
- Studio UI, visual modeling or frontend: read [DESIGN](docs/DESIGN.md), [ADR-0008](docs/adr/0008-studio-and-metadata.md), the [Studio contract](docs/spec/semantic-contract-v0.1.md#12-studio-草稿与管理接口), [acceptance](docs/acceptance.md), and [SECURITY.md](SECURITY.md).
- Build, dependencies, contribution or release: read [CONTRIBUTING.md](CONTRIBUTING.md). Commands marked planned are not existing capabilities.
- Agent harness, LLM execution, chat or session compaction: adhere to Pi's official lifecycle and the three-tier infrastructure reuse hierarchy below.

Document ownership: CONTEXT owns terminology; the semantic contract owns behavior and security semantics; DESIGN owns UI layout and interaction; PLAN owns task scope/dependencies; acceptance owns checks and their final closing tasks. ADRs record decisions and amendments. Update affected owners together; link to details instead of repeating them.

Architecture invariants are settled; signatures, exact fields, package names and budgets marked as drafts are implementation design inputs. Refine them within the assigned task, record the decision, and update affected documents together. Do not ask the owner to approve routine reversible details.

## Invariants

- The project language is Python and the license is Apache-2.0.
- Deploy one Python application process: adapters and recovery tasks run in-process. Compose bounded cross-source reads through declared business links; keep connection settings inside adapters/environment bindings. See [ADR-0007](docs/adr/0007-in-process-source-composition.md).
- Runtime executes approved, immutable semantic releases. Every request pins its release and authenticated tenant/actor context.
- Agent-facing interfaces accept semantic identifiers and typed values. SQL, join expressions, destination URLs and caller-asserted permissions are not request inputs.
- Query providers have read-only effects. Business-system writes use the Action lifecycle, including trusted approval and execution reconciliation. Draft edits, source registration and release activation use the authorized control-plane contracts.
- Treat missing observations, FALSE claims and operational errors as distinct outcomes. Money uses exact decimal arithmetic.
- SemaLoom is a general enterprise business layer. Domain packs own business definitions; the independent integration layer owns physical mappings, protocol adapters and vendor details. Core and the shared compiler depend only on protocol-neutral contracts, never domain or connector implementations. See [ADR-0006](docs/adr/0006-independent-integration-layer.md).
- Authorization and evidence are part of the first working query, including discovery, caches, explanations and errors.
- Python owns semantic compilation, planning and execution semantics. Reuse mature infrastructure; keep third-party ASTs, ORM models and framework request objects out of public semantic contracts. Python expression evaluation is not a rules sandbox.
- Pi agent infrastructure reuse hierarchy (strictly no reinventing wheels): For agent scheduling, context transformation, session compaction, and token budgeting, follow the three-tier hierarchy:
  1. **Pi native foundational capabilities first**: Prioritize official first-class APIs and lifecycle hooks from `@earendil-works/pi-agent-core` and `@earendil-works/pi-ai` (e.g., `AgentOptions.transformContext`, `createCompactionSummaryMessage`, `estimateContextTokens`, `shouldCompact`, `convertToLlm`, `shouldStopAfterTurn`).
  2. **Authoritative, high-star, stable plugins second**: When base capabilities are insufficient or require advanced strategies, adopt authoritative, high-star community plugins or proven extensions (e.g., `pi-compact-plus` patterns for tool-output pruning).
  3. **Custom implementation strictly as last resort**: Only build custom solutions if native capabilities and authoritative plugins cannot satisfy the requirements, and implement them strictly under Pi's native contract inside the harness. Never build ad-hoc, unstable custom wheels (such as application-layer string slicing or synthetic message stitching) outside the harness.
- **Ontology customization vs universal core stability**: The universal core (`core`, `compiler`, `runtime`, `presentation`, `summary`) is domain-agnostic and invariant. It never contains hardcoded domain branches or special casing for specific industries or entities. Domain packs (declarative YAML files) are the sole carrier of customized business logic (objects, properties, dictionaries, metric grain/additivity, links, rules, policies, actions). Any new enterprise domain (logistics, healthcare, manufacturing, HR, finance) is modeled entirely through ontology YAMLs without touching the core engine.
- **Understated universal design and minimal ontology schema (内敛通用设计与本体防膨胀规范)**:
  1. **Lean ontology schema**: Keep the ontology definition pure and business-focused. Never bloat ontology YAMLs with presentation flags, UI rendering templates, or custom layout knobs. The universal engine derives clean human presentation purely from foundational semantic metadata (`label`, `unit`, `values`, `identityKeys`, `properties`).
  2. **Understated presentation (内敛收拢机器内部设计)**: The universal engine must absorb and hide internal machine mechanics, debug placeholders, and security assertions from human-facing text:
     - Never expose raw machine states, internal error codes, or technical tokens (`无额外属性`, `PRESENT`, `SUCCEEDED`, `全量已授权`) in user-visible prose.
     - Never dump formal logic disclaimers (`UNKNOWN 不等于 FALSE，规则成立不自动代表业务合规`) onto simple data/object queries. Reserve compliance policy caveats strictly for evaluated rules.
     - Never clutter prose with toy icons (`• 🔷`) or erratic bullet punctuation. Format numbers naturally according to declared `unit` and precision, eliminating trailing zero spam (`1200.0000 CNY` -> `1200 CNY`).
  3. **Strict two-layer presentation separation**:
     - **Human perception layer (Answer prose)**: Delivers understated, dignified, clear, and natural business conclusions formatted in standard typography and Chinese business punctuation.
     - **Rigorous auditability layer (Evidence cards)**: Completely encapsulates heavy machine designs (data source IDs, table/API operations, physical field paths, execution timestamps, raw precision values, and snapshot hashes) into collapsible evidence drawers (`EvidenceCard`), ensuring 100% provenance and zero hallucination without cluttering the conversation.

## Execute and hand off

1. Inspect the current diff and relevant files; preserve unrelated changes. This initial baseline may not yet be in a Git repository.
2. Check task dependencies and record a short checklist plus settled decisions in the ignored `.agents/<task>/` directory. Pause only work requiring an unresolved owner decision.
3. Make the smallest complete vertical slice. Add packages when behavior needs them; the architecture diagram is not permission to scaffold empty services or speculative extension interfaces.
4. Run the task's acceptance checks, including its named failure cases and the staged ownership in [acceptance](docs/acceptance.md). An early-stage pass never closes a later integration requirement. Report unavailable checks separately from passes. Use project manifests for commands and versions once they exist.
5. Update affected contracts, examples and task status together. Hand off changed files, exact check results, limitations and the next unblocked task in `.agents/<task>/handoff.md`.

For Studio/control-plane work, close one real path from UI action through authorization, persistence, Compiler/Registry behavior and reload before adding the next screen. Keep canonical semantic documents in the control-plane service; UI types and projections are views of that model. Give each behavior one owner and remove superseded prototype paths in the same slice. Add only controls backed by a working authorized endpoint and a visible error/recovery state; keep one primary action per page.

Use absolute task paths and project-local dependencies. Put disposable probes in one task-specific system temporary directory and clean only task-owned artifacts. Never store real business data, secrets or full query results in source control. Do not publish, deploy, grant a license or contact others without applicable user authorization.

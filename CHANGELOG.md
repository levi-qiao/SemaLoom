# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic
versioning for published releases. During `0.x`, incompatible changes are documented explicitly.

## [Unreleased]

### Fixed

- Reject incompatible Rule units, output relabeling, invalid identities/grain, undeclared or
  wrong-version pack references, and invalid Policy dates/dimensions. Invalid old definitions
  must be corrected and recompiled; valid v0.1 definitions retain their meaning.
- Enforce tenant scope on wide-table previews, restrict API document downloads to configured
  origins, and reject unsafe fixture database targets before connecting.
- Pin source bindings per application request and bind prepared analysis to their digest.
  Re-prepare old plans or plans made before a source binding change.
- Save Studio revisions and activate the exact saved release atomically, including publication history.
- Fail missing/empty pack paths, correct quickstart bindings and obsolete approval claims,
  and localize business-period clarification and new source/import errors.


### Repository maintenance

- Remove the unreachable draft editor, duplicate frontend types/helpers and the compiler digest
  forwarding module. Shared definition fields and core digest code retain one implementation.
- Retire superseded agent prompts, execution reports and private sample-import workflows from
  the public tree. Current behavior and limits live in architecture, capabilities and acceptance.
- Reuse real application assembly for isolated browser tests; load only synthetic fixtures,
  reject occupied database ports, support configurable PostgreSQL binaries and clean up on exit.

### Added

- Embedded read-only `semaloom.sdk.SemanticEngine`, sharing the application runtime with pinned
  releases, explicit host identities, typed results and caller-owned providers. See
  [Python SDK](docs/python-sdk.md) for integration and current limits.

- Frozen `SemanticQuery` prepare/choice contract (`READY` / `NEEDS_INPUT` / `UNSUPPORTED` /
  `SOURCE_ERROR`) with direct-compute and two-round samples. Planner selection is ADR-0011;
  product migration is not claimed complete.
- Protocol-neutral Python semantic compiler and in-process query runtime.
- PostgreSQL source adapter, immutable metadata registry, controlled action lifecycle, and Studio
  prototype.
- Tax and procurement synthetic domain packs demonstrating reuse across business domains.
- Synthetic quickstart with five runnable example classes (query, evidence, policy period switch,
  missing/UNKNOWN, draft Action) and expected results.
- Packaging tests that the wheel ships LICENSE plus Studio static assets, and that sdist/wheel
  paths exclude `.agents/`, credentials, and private sample dumps.
- Chat asks for unresolved business scope through ontology-derived choice cards before querying.
  It does not expose confidence scores, raw business identities, or automatically expanded
  provenance in the human answer.
- Optional TypeSafe Jev routing uses the live ontology catalog, bounded conversation context,
  locale, and generic tool schemas. Typed decisions now cover tool routing, bounded ontology
  candidate classification, scope completeness and internal match quality. It fails open to the
  normal Pi loop and cannot authorize or execute a query.
- The procurement pack now demonstrates contracts scoped by string accounting periods, ontology dictionaries, derived amount
  and non-additive ratio metrics, deterministic claims, same-/cross-source links, and two years of
  tenant-isolated synthetic contract rows.
- REST and official MCP Streamable HTTP at `/mcp/` share one bearer authenticator. Non-local
  profiles require signed JWT issuer, audience, and public-key/JWKS configuration and reject
  demo-token fallback. The MCP transport currently exposes semantic query, claim evaluation, and
  semantic explain.
- Chinese and English Chat/UI resources are available. The current message determines answer
  language, with browser locale used only as a fallback for language-neutral input.
- Property dictionaries (`values`) drive dimension/claim choice cards. Year-over-year
  uses `PERIOD_OVER_PERIOD` on SemanticQuery, not window LAG. See ADR-0014.
- Measurement slots declare Kimball additivity (`FULL` / `SEMI` / `NONE`, default `FULL`).
  Collection analysis uses only SemanticQuery prepare/execute; AVG still compiles to
  SUM+COUNT in PostgreSQL. See ADR-0013. Example packs name common business aliases on
  those slots (利润/资产/库存/采购额) and include a non-additive 资产负债率.
- Analysis evidence resolves configured name-like properties and ONE links (e.g. company name)
  instead of showing only opaque IDs.
- Studio entity pages share one two-column sheet. Properties and Mapping sit on the same row;
  table sources preview the first rows so columns and keys can be clicked. Multi-table objects
  prompt for join keys on each Mapping. Mapping preview grows with the window (not a 22rem strip),
  shows sample rows, and switches table versus API as source cards. Primary views share 32px
  control density and do not overflow at 1440×900 or 390×844.

### Changed

- Physical mapping compilation now belongs to adapters, injected through `MappingCompiler`.
  Use SDK compile helpers for built-in profiles; direct compiler calls require explicit injection.
  Unsupported/unbound metric selectors and conflicting fixed filters fail compilation.
- Wheels include the harness context-transform module; sdists include locked frontend/Python
  build inputs. Installed SDK imports and local harness module completeness are verified.

- Observed facts bind through one object Mapping per fact table. Metric documents are
  business vocabulary (stable id, aliases, optional code filter) that inherit grain/unit
  from the object and Mapping; Compiler synthesizes the query Mapping. See ADR-0012.

- Mapping capabilities and semantic field coverage are compiler-generated IR. Object point reads,
  Studio preview, HTTP tools, AI tools, Link traversal, and Action execution preserve complete
  structured identities, including composite keys; legacy identity mapping fields are rejected
  instead of normalized. Discovery advertises `collectionJoin` only for ONE Links with a single
  identity pair; same-source collection JOIN and cross-source bind-join both reject composite Links
  with `LINK_ANALYSIS_UNSUPPORTED`. Metric discovery also projects `additivity` and the aggregations
  that additivity allows.
- Capability and README wording matches current evidence: local-dev demo tokens, official MCP
  Streamable HTTP at `/mcp/` with `/v0.1/mcp/tools` as a compatibility catalog, exact-decimal rules,
  in-process Action drafts, and a joint Studio gate. Composite-key cross-source collection analysis
  remains outside the current boundary.
- Public sdist omits private-sample instructions and the remote importer; contributors still use
  git for those files.

### Fixed

- Metric year choices now require a non-null observation for that exact metric and selector;
  another metric's row no longer advertises an unusable year. Explicit absent-year queries still
  return the engine's empty-population outcome. Confirmed Chat queries can be refined by concise
  follow-ups such as changing only the year, including when Jev is configured.
- Studio entity pages can add, edit and delete judgments and actions the same way they already
  add relations and mappings. The structured input/operator form is on the entity sheet; there
  is still no expression executor in the browser.
- Quickstart no longer implies Docker is the only PostgreSQL fixture or that a model key is
  required.

### Removed

- `POST /v0.1/analyze`, `analyze_population`, `PopulationRequest` and `runtime/population.py`.
  Collection analysis has a single SemanticQuery path.

[Unreleased]: https://github.com/levi-qiao/SemaLoom/commits/main

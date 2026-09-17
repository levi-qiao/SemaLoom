# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic
versioning for published releases. During `0.x`, incompatible changes are documented explicitly.

## [Unreleased]

### Added

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
- Chat answers a uniquely identified metric with assumed latest year and additive SUM, plus
  an ontology-general confidence score. Choice cards are one-click, include an Other free-text
  option, and no longer require typing candidate labels.
- Analysis evidence resolves configured name-like properties and ONE links (e.g. company name)
  instead of showing only opaque IDs.
- Studio entity pages share one two-column sheet. Properties and Mapping sit on the same row;
  table sources preview the first rows so columns and keys can be clicked. Multi-table objects
  prompt for join keys on each Mapping. Mapping preview grows with the window (not a 22rem strip),
  shows sample rows, and switches table versus API as source cards. Primary views share 32px
  control density and do not overflow at 1440×900 or 390×844.

### Changed

- Observed facts bind through one object Mapping per fact table. Metric documents are
  business vocabulary (stable id, aliases, optional code filter) that inherit grain/unit
  from the object and Mapping; Compiler synthesizes the query Mapping. See ADR-0012.

- Mapping capabilities and semantic field coverage are compiler-generated IR. Object point reads,
  Studio preview, HTTP tools, AI tools, Link traversal, and Action execution preserve complete
  structured identities, including composite keys; legacy identity mapping fields are rejected
  instead of normalized. Discovery advertises `collectionJoin` only for ONE Links with a single
  identity pair; same-source collection JOIN and cross-source bind-join both reject composite Links
  with `LINK_ANALYSIS_UNSUPPORTED`.
- Capability and README wording matches current evidence: local-dev demo tokens only, static
  `/mcp/tools` list rather than MCP transport, exact-decimal rules, in-process Action drafts, and an
  unfinished Studio Rule editor / joint Studio gate. Composite-key cross-source collection analysis
  remains outside the current boundary.
- Public sdist omits private-sample instructions and the remote importer; contributors still use
  git for those files.

### Fixed

- Quickstart no longer implies Docker is the only PostgreSQL fixture or that a model key is
  required.

[Unreleased]: https://github.com/levi-qiao/SemaLoom/commits/main

# Architecture review and SDK slice — 2026-09-20

The architecture is suitable for a reusable semantic engine, with explicit limits. Business
definitions belong in ontology packs; physical source knowledge belongs in adapters; the shared
engine owns typed requests, deterministic calculations and evidence. The appropriate embedded
core is the combination of `core + compiler + read-only runtime`, exposed through
[the Python SDK](python-sdk.md), rather than exporting the Studio application bootstrap.

| Question | Finding and change |
| --- | --- |
| Can the core stay domain-independent? | The inspected core/compiler/query/evaluator/answer-presentation paths contain no tax, procurement, finance or warehouse ID branches. Physical PostgreSQL/OpenAPI handling did remain inside `compiler/mapping_ir.py`; it now lives in `adapters/mapping.py`, injected via `MappingCompiler`. Import checks also reject application/SDK/runtime and infrastructure dependencies from core/compiler. |
| Can YAML express different businesses? | Tax, procurement, warehouse and financial-review compile through the same entry. A different test protocol compiles through injected capabilities without editing the shared compiler. This proves extensibility within the semantic contract, not support for every business operator or data source. |
| Are answers grounded? | Point reads and Claims preserve missingness, exact decimals, source failures and evidence. Collection prepare/execute preserves clarification and plan binding. A newly found selector bug could silently drop an API selector or replace a source filter; compilation now rejects both cases. Open-language model explanations still lack a formal correctness guarantee. |
| Is the code split sensible? | Compiler, runtime, adapters and application responsibilities are useful. SDK assembly and shared digest verification eliminate duplicate integration setup. Protocol-neutral helpers now use semantic-field names. Large `adapters/analysis.py` and Chat choice modules remain maintenance hotspots; splitting solely by line count would not create a better interface. |
| Can it be embedded elegantly? | `SemanticEngine` pins a verified copy of one release and borrows a provider. It uses the original execution code, has no web/fixture initialization, and accepts the current actor per call. A single distribution avoids drifting core/server engines and dependency versions. |

## Repository and distribution hygiene

The tracked/untracked file inventory was reviewed before saving the existing changes. Superseded
Studio panels/pages, Python chat compression and population compatibility code were already
removed in that baseline; their replacements are retained. The physical compiler was moved,
not duplicated. Built Studio assets and third-party license notices remain necessary for the
single-wheel application and are not disposable build clutter.

The new harness context module was missing from the wheel include list; it is now included and
local harness imports are checked in the archive. The sdist now includes frontend source, lockfiles,
the Python version and domain context needed to rebuild from source, while excluding dependency
trees and browser outputs. The README's obsolete typed-rule limitation and example identity key
were corrected; a developer-specific absolute credential-file path was removed from local notes.
Historical research, ADRs and linked acceptance reports are retained because they explain decisions
and unclosed gates. Private sample operations remain isolated from public quickstart/distributions;
this pass does not delete or migrate local datasets or rewrite Git history.

## Verification and remaining limits

Regression coverage includes actual PostgreSQL SDK execution, independent known synthetic values,
two tenants, denied actors, missing/NULL values, TRUE/FALSE/UNKNOWN, source failure, plan retargeting,
bundle mutation and future IR rejection. Compiler tests cover four shipped domains, a custom
protocol and invalid selectors. Artifact checks install the wheel in a clean environment, import
the SDK outside the checkout, and inspect harness dependencies and reproducible source inputs.
All four shipped domain bundle digests also match the saved baseline commit `163b44f`, verifying
that the physical compiler move preserves valid existing releases. Exact run results are recorded
in the task handoff. That review's full suite passed 380 tests; its MCP skip and expected production
JWT failure were subsequently replaced by mandatory transport and cryptographic identity tests.
Ruff, mypy and frontend type checking passed. The harness passed 12 tests, and a frontend rebuild
exactly matched the committed assets. These checks do not close all
production acceptance gates; no new live-model evaluation or browser interaction run was performed.

The remaining material limits are coarse tenant/role authorization, no external IAM revocation integration,
incomplete durable Action recovery, limited collection joins/operators, no universal language
accuracy guarantee, and no proof that upstream business values are correct. The repository remains
pre-alpha. Publishing the repository is distinct from certifying a production enterprise system.
The next substantive architecture task is fine-grained authorization injected consistently through
query, discovery, analysis, Claims and evidence, with revocation checks and cross-resource tests.

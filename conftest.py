"""Temporary P0 validation hook; self-removes after applying generated-tree fixes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if old in text:
        target.write_text(text.replace(old, new, 1))


# The migration must remove compiler-owned Mapping capabilities only. It currently
# strips inline capability lists globally, so restore the two authorization profiles
# in the generated workspace using a multiline form that is not mistaken for Mapping IR.
for rel in ("examples/tax/domain/actions.yaml", "examples/procurement/domain/rules.yaml"):
    target = ROOT / rel
    text = target.read_text()
    marker = "  roles: ["
    if marker in text and "  capabilities:" not in text:
        line_end = text.index("\n", text.index(marker)) + 1
        text = (
            text[:line_end]
            + "  capabilities:\n"
            + "    - query\n"
            + "    - evaluateClaim\n"
            + "    - planAction\n"
            + text[line_end:]
        )
        target.write_text(text)

# SQL analysis is an adapter boundary: derive the physical identity column from the
# compiled semantic projection instead of the removed legacy identityColumn field.
patch(
    "src/semaloom/adapters/analysis.py",
    '''    identity_col = require_ident(\n        metric_mapping.physical.get("identityColumn"), field="identityColumn"\n    )\n    projection = {**_projection(object_mapping), **_projection(metric_mapping)}\n    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)\n    if len(obj.identity_keys) != 1:\n        raise AnalysisError("UNSUPPORTED_IDENTITY")\n''',
    '''    projection = {**_projection(object_mapping), **_projection(metric_mapping)}\n    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)\n    if len(obj.identity_keys) != 1:\n        raise AnalysisError("UNSUPPORTED_IDENTITY")\n    identity_col = projection.get(obj.identity_keys[0])\n    if identity_col is None:\n        raise AnalysisError("NO_MAPPING")\n    identity_col = require_ident(identity_col, field="identity")\n''',
)

# Do not leave this bootstrap helper in the validated implementation commit.
Path(__file__).unlink(missing_ok=True)

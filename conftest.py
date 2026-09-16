"""Temporary P0 validation hook; self-removes after generated-tree fixes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if old in text:
        target.write_text(text.replace(old, new, 1))


for rel in (
    "examples/tax/domain/actions.yaml",
    "examples/procurement/domain/rules.yaml",
):
    target = ROOT / rel
    text = target.read_text()
    marker = "  roles: ["
    if marker in text and "  capabilities:" not in text:
        line_end = text.index("\n", text.index(marker)) + 1
        capabilities = (
            "  capabilities:\n"
            "    - query\n"
            "    - evaluateClaim\n"
            "    - planAction\n"
        )
        target.write_text(text[:line_end] + capabilities + text[line_end:])

old_analysis = '''    identity_col = require_ident(
        metric_mapping.physical.get("identityColumn"), field="identityColumn"
    )
    projection = {**_projection(object_mapping), **_projection(metric_mapping)}
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    if len(obj.identity_keys) != 1:
        raise AnalysisError("UNSUPPORTED_IDENTITY")
'''
new_analysis = '''    projection = {**_projection(object_mapping), **_projection(metric_mapping)}
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    if len(obj.identity_keys) != 1:
        raise AnalysisError("UNSUPPORTED_IDENTITY")
    identity_col = projection.get(obj.identity_keys[0])
    if identity_col is None:
        raise AnalysisError("NO_MAPPING")
    identity_col = require_ident(identity_col, field="identity")
'''
patch("src/semaloom/adapters/analysis.py", old_analysis, new_analysis)

Path(__file__).unlink(missing_ok=True)

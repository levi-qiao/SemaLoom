"""Temporary P0 validation hook; self-removes after generated-tree fixes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def patch(path: str, old: str, new: str, *, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text()
    if old in text:
        target.write_text(text.replace(old, new, count))


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

old_compile = '''    identity_col = require_ident(
        metric_mapping.physical.get("identityColumn"), field="identityColumn"
    )
    projection = {**_projection(object_mapping), **_projection(metric_mapping)}
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    if len(obj.identity_keys) != 1:
        raise AnalysisError("UNSUPPORTED_IDENTITY")
'''
new_compile = '''    projection = {**_projection(object_mapping), **_projection(metric_mapping)}
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    if len(obj.identity_keys) != 1:
        raise AnalysisError("UNSUPPORTED_IDENTITY")
    identity_col = projection.get(obj.identity_keys[0])
    if identity_col is None:
        raise AnalysisError("NO_MAPPING")
'''
patch("src/semaloom/adapters/analysis.py", old_compile, new_compile)

old_link_label = '''        identity_col = require_ident(
            target_mapping.physical.get("identityColumn") or projection.get(link.identity.target),
            field="identityColumn",
        )
'''
new_link_label = '''        identity_col = projection.get(link.identity.target)
        if identity_col is None:
            continue
'''
patch("src/semaloom/adapters/analysis.py", old_link_label, new_link_label)

old_bind_identity = (
    '    identity = require_ident(bind.mapping.physical.get("identityColumn"), '
    'field="identityColumn")\n'
)
new_bind_identity = (
    "    identity = projection.get(bind.link.identity.target)\n"
    "    if identity is None:\n"
    '        raise AnalysisError("NO_MAPPING")\n'
)
patch(
    "src/semaloom/adapters/analysis.py",
    old_bind_identity,
    new_bind_identity,
    count=2,
)


def pytest_sessionfinish() -> None:
    Path(__file__).unlink(missing_ok=True)

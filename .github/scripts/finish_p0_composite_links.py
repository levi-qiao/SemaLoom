from __future__ import annotations

from pathlib import Path
import re
from textwrap import dedent


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    p = Path(path)
    text = p.read_text()
    i = text.index(start)
    j = text.index(end, i)
    p.write_text(text[:i] + dedent(replacement).rstrip() + "\n\n" + text[j:])


# The first-stage script deliberately stops after replacing follow_link. Its replacement is
# dedented as a top-level function; restore it as a QueryService method before continuing.
p = Path("src/semaloom/runtime/query.py")
text = p.read_text()
start = text.index("def follow_link(\n")
end = text.index("    def _metric(\n", start)
block = text[start:end]
if not block.startswith("def follow_link(\n"):
    raise SystemExit("unexpected follow_link migration state")
indented = "\n".join(("    " + line if line else line) for line in block.splitlines())
text = text[:start] + indented + "\n" + text[end:]

helper_start = text.index("    def _object_mapping_for_property(\n")
helper_end = text.index("    def _mapping_for_target(\n", helper_start)
helper = '''    def _object_mapping_for_properties(
        self, object_type: str, property_ids: tuple[str, ...]
    ) -> tuple[MappingDef | None, str | None]:
        required = set(property_ids)
        candidates = [
            mapping
            for mapping in self.bundle.mappings
            if mapping.target == object_type and required <= _mapped_object_fields(mapping)
        ]
        if len(candidates) == 1:
            return candidates[0], None
        if len(candidates) > 1:
            return None, "AMBIGUOUS_MAPPING"
        return None, "NO_MAPPING"

    def _object_mapping_for_property(
        self, object_type: str, property_id: str
    ) -> tuple[MappingDef | None, str | None]:
        return self._object_mapping_for_properties(object_type, (property_id,))

'''
p.write_text(text[:helper_start] + helper + text[helper_end:])

# Analysis: same-source SQL joins use every identity pair. Cross-source bind materialization
# remains intentionally scalar and fails explicitly for composite links instead of truncating.
p = Path("src/semaloom/adapters/analysis.py")
text = p.read_text()
anchor = "_BIND_KEY_LIMIT = 1000\n_BIND_BATCH = 50\n"
if anchor not in text:
    raise SystemExit("analysis bind constants changed")
text = text.replace(
    anchor,
    anchor
    + '\n\ndef _single_link_pair(link: LinkDef):\n'
    + '    if len(link.identity) != 1:\n'
    + '        raise AnalysisError("LINK_ANALYSIS_UNSUPPORTED")\n'
    + '    return link.identity[0]\n',
    1,
)
text = text.replace(
    "local_key=resolved.link.identity.source,",
    "local_key=_single_link_pair(resolved.link).source,",
)
text = text.replace(
    "key = resolved.link.identity.source",
    "key = _single_link_pair(resolved.link).source",
)
old_join = '''            target_projection = _projection(target_mapping)
            source_col = projection.get(link.identity.source)
            target_col = target_projection.get(link.identity.target)
            if source_col is None or target_col is None:
                raise AnalysisError("NO_PATH")
            from_sql += (
                f" LEFT JOIN {target_table} AS {alias} ON {alias}.{target_tenant} = :tenant"
                f" AND {alias}.{require_ident(target_col, field='column')} = {source_col}"
            )'''
new_join = '''            target_projection = _projection(target_mapping)
            join_predicates = []
            for pair in link.identity:
                source_col = projection.get(pair.source)
                target_col = target_projection.get(pair.target)
                if source_col is None or target_col is None:
                    raise AnalysisError("NO_PATH")
                join_predicates.append(
                    f"{alias}.{require_ident(target_col, field='column')} = {source_col}"
                )
            from_sql += (
                f" LEFT JOIN {target_table} AS {alias} ON {alias}.{target_tenant} = :tenant"
                + "".join(f" AND {predicate}" for predicate in join_predicates)
            )'''
if old_join not in text:
    raise SystemExit("analysis same-source join block changed")
text = text.replace(old_join, new_join)

# Label decoration is best-effort; scalar links retain the optimization, composite links skip it.
text = text.replace(
    '''        ids = {
            str(item)
            for item in field_ids.get(link.identity.source, set())
            if item not in {"", "None"}
        }''',
    '''        if len(link.identity) != 1:
            continue
        pair = link.identity[0]
        ids = {
            str(item)
            for item in field_ids.get(pair.source, set())
            if item not in {"", "None"}
        }''',
)
text = text.replace(
    "identity_col = projection.get(link.identity.target)",
    "identity_col = projection.get(pair.target)",
)
text = text.replace(
    "found[(link.identity.source, ident)] = name",
    "found[(pair.source, ident)] = name",
)
text = text.replace(
    "identity = projection.get(bind.link.identity.target)",
    "identity = projection.get(_single_link_pair(bind.link).target)",
)
if "link.identity.source" in text or "link.identity.target" in text:
    raise SystemExit("analysis scalar link identity residue remains")
p.write_text(text)

# Reuse the already-written tail for frontend, examples, tests and residue assertions.
source = Path(".github/scripts/fix_p0_composite_links.py").read_text()
marker = "# Frontend relation editor supports an arbitrary non-empty list of identity pairs."
_, tail = source.split(marker, 1)
exec(compile(marker + tail, ".github/scripts/fix_p0_composite_links.py:tail", "exec"), globals())

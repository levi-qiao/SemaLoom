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

# Reuse the already-written tail for frontend, examples, tests and residue assertions.
source = Path(".github/scripts/fix_p0_composite_links.py").read_text()
marker = "# Frontend relation editor supports an arbitrary non-empty list of identity pairs."
_, tail = source.split(marker, 1)
exec(compile(marker + tail, ".github/scripts/fix_p0_composite_links.py:tail", "exec"), globals())

"""JSON camelCase aliases that do not rewrite Python constructors.

Pyright and basedpyright treat ``Field(alias=...)`` as the only ``__init__``
keyword. Call sites use field names, and runtime Pydantic accepts both when
``populate_by_name`` is on — so the IDE reports a false missing-argument error.

``alias_generator`` keeps wire names for validation, serialization and OpenAPI
while constructors stay snake_case. Do not add ``Field(alias=...)``.
"""

from __future__ import annotations

from pydantic import ConfigDict
from pydantic.alias_generators import to_camel


def wire_config(*, frozen: bool = True) -> ConfigDict:
    return ConfigDict(
        extra="forbid",
        frozen=frozen,
        populate_by_name=True,
        validate_by_name=True,
        alias_generator=to_camel,
    )

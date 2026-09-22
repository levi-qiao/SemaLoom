"""Resolve business labels for stored values without presentation YAML.

Sources, in order: authored Property.values, optional mapping lookup tables,
then the stored id itself. Option identity remains the stored value.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import EmbeddedProperty, ObjectTypeDef, PropertyValue


def fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def find_property(bundle: CompiledBundle, field: str) -> EmbeddedProperty | None:
    bare = field.rsplit(".", 1)[-1]
    qualified = field if "." in field else None
    if qualified:
        object_id, prop_id = qualified.rsplit(".", 1)
        obj = next((item for item in bundle.object_types if item.id == object_id), None)
        if obj is not None:
            found = next((prop for prop in obj.properties if prop.id == prop_id), None)
            if found is not None:
                return found
    matches = [prop for obj in bundle.object_types for prop in obj.properties if prop.id == bare]
    return matches[0] if len(matches) == 1 else None


def authored_entry(prop: EmbeddedProperty | None, stored: object) -> PropertyValue | None:
    if prop is None:
        return None
    key = str(stored)
    return next((item for item in prop.values if item.id == key), None)


def display_label(
    prop: EmbeddedProperty | None,
    stored: object,
    lookup: dict[str, str] | None = None,
) -> str:
    key = str(stored)
    authored = authored_entry(prop, stored)
    if authored is not None and authored.label:
        return authored.label
    if lookup and key in lookup:
        return lookup[key]
    return key


def value_terms(
    prop: EmbeddedProperty | None,
    stored: object,
    lookup: dict[str, str] | None = None,
) -> tuple[str, ...]:
    key = str(stored)
    terms = [key, display_label(prop, stored, lookup)]
    authored = authored_entry(prop, stored)
    if authored is not None:
        terms.extend(authored.aliases)
    return tuple(dict.fromkeys(fold(term) for term in terms if term and str(term).strip()))


def mentioned_stored_value(
    text: str,
    candidates: list[Any],
    prop: EmbeddedProperty | None,
    lookup: dict[str, str] | None = None,
) -> Any | None:
    folded = fold(text)
    hits: list[Any] = []
    for stored in candidates:
        if any(len(term) >= 2 and term in folded for term in value_terms(prop, stored, lookup)):
            hits.append(stored)
    return hits[0] if len(hits) == 1 else None


def object_for_metric(bundle: CompiledBundle, metric_id: str) -> ObjectTypeDef | None:
    metric = next((item for item in bundle.metrics if item.id == metric_id), None)
    if metric is None:
        return None
    return next((item for item in bundle.object_types if item.id == metric.object_type), None)

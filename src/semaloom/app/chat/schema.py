"""Inline model-facing JSON Schema references without changing canonical contracts.

Some compatible providers stringify nested $ref/nullable objects. Present concrete
object properties instead; omitted optional properties retain Python defaults.
Never parse a model's arbitrary JSON strings or relax server-side validation.
"""

from __future__ import annotations

from typing import Any


def model_schema(schema: dict[str, Any]) -> dict[str, Any]:
    definitions = schema.get("$defs", {})

    def expand(value: Any, stack: tuple[str, ...] = ()) -> Any:
        if isinstance(value, list):
            return [expand(item, stack) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            ref = value["$ref"]
            if not ref.startswith("#/$defs/"):
                raise ValueError("UNSUPPORTED_MODEL_SCHEMA_REFERENCE")
            target = definitions[ref.removeprefix("#/$defs/")]
            if stack.count(ref) >= 3:
                # Bounded model projection of recursive filters and formulas. The
                # canonical Python contract independently validates the execution budget.
                if ref == "#/$defs/FilterGroup":
                    target = {
                        **target,
                        "properties": {
                            **target["properties"],
                            "args": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"$ref": "#/$defs/FilterAtom"},
                            },
                        },
                    }
                elif ref == "#/$defs/Formula":
                    measure = {"$ref": "#/$defs/MeasureTerm"}
                    target = {
                        **target,
                        "properties": {
                            **target["properties"],
                            "left": measure,
                            "right": {"anyOf": [measure, {"type": "null"}]},
                        },
                    }
                else:
                    raise ValueError("UNSUPPORTED_MODEL_SCHEMA_REFERENCE")
            value = {**target, **{k: v for k, v in value.items() if k != "$ref"}}
            stack = (*stack, ref)
        result = {k: expand(v, stack) for k, v in value.items() if k != "$defs"}
        # Narrow only optional object fields, not primitive unions or required nulls.
        fields = result.get("properties", {}) if result.get("type") == "object" else {}
        for key, field in fields.items():
            if key in result.get("required", []):
                continue
            choices = field.get("anyOf", [])
            concrete = [item for item in choices if item.get("type") != "null"]
            if len(choices) == 2 and len(concrete) == 1 and concrete[0].get("type") == "object":
                result["properties"][key] = {
                    **concrete[0],
                    **{k: v for k, v in field.items() if k not in {"anyOf", "default"}},
                }
        return result

    result: dict[str, Any] = expand(schema)
    return result

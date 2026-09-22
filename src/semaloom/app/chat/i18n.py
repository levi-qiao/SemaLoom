"""Small locale resource seam for Chat-owned copy.

Business labels remain in ontology releases.  This module owns only application
copy and keeps locale selection out of semantic/runtime code.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DEFAULT_LOCALE = "zh-CN"
_RESOURCE_DIR = Path(__file__).with_name("locales")


def normalize_locale(value: str | None) -> str:
    raw = (value or _DEFAULT_LOCALE).split(",", 1)[0].split(";", 1)[0].strip().replace("_", "-")
    if raw.casefold().startswith("zh"):
        return "zh-CN"
    if raw.casefold().startswith("en"):
        return "en"
    return _DEFAULT_LOCALE


_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_CAMEL_EDGE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def message_locale(message: str, requested: str | None = None) -> str:
    """Choose response language from the current message, then client preference."""

    if _HAN.search(message):
        return "zh-CN"
    if _LATIN_WORD.search(message):
        return "en"
    return normalize_locale(requested)


def semantic_label(locale: str, label: str | None, semantic_id: str) -> str:
    """Use ontology copy when localized; otherwise humanize its stable ID."""

    if normalize_locale(locale) != "en" or not label or not _HAN.search(label):
        return label or semantic_id
    tail = semantic_id.rsplit(".", 1)[-1].replace("_", "-")
    return _CAMEL_EDGE.sub(" ", tail).replace("-", " ").strip().title()


@lru_cache(maxsize=8)
def _messages(locale: str) -> dict[str, str]:
    normalized = normalize_locale(locale)
    path = _RESOURCE_DIR / f"{normalized}.json"
    if not path.is_file():
        path = _RESOURCE_DIR / f"{_DEFAULT_LOCALE}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError("INVALID_CHAT_LOCALE_RESOURCE")
    return value


def text(locale: str, key: str, **values: str) -> str:
    messages = _messages(locale)
    template = messages.get(key) or _messages(_DEFAULT_LOCALE).get(key)
    if template is None:
        raise KeyError(key)
    return template.format_map(values)


def localize_question(question: dict[str, object] | None, locale: str) -> dict[str, object] | None:
    """Localize engine choice copy without changing typed semantic choices."""

    if question is None or normalize_locale(locale) != "en":
        return question
    result = dict(question)
    slot = str(result.get("slot") or "")
    prompts = {
        "metric": ("Which metric definition do you mean?", "The metric changes the result."),
        "aggregation": (
            "How should this metric be calculated?",
            "Totals, averages, and other operations have different meanings.",
        ),
        "formula": (
            "Which calculation do you mean?",
            "These calculations use different denominators.",
        ),
        "group": (
            "Which property should group the result?",
            "The grouping property comes from the published ontology.",
        ),
        "dimension": (
            "Choose a business value",
            "This value is declared by the ontology and must not be guessed.",
        ),
        "subject": ("Which object should be compared?", "The subject must identify one object."),
        "filter": ("Choose the intended filter", "The supplied filters conflict."),
        "claim": (
            "Which published rule should be evaluated?",
            "More than one rule matches the question.",
        ),
        "claimSubject": (
            "Which object should be evaluated?",
            "A rule evaluation must identify one object.",
        ),
    }
    if slot == "claimPeriod":
        result["prompt"] = text(locale, "claimPeriod.prompt")
        result["reason"] = text(locale, "claimPeriod.reason")
    if slot in prompts:
        result["prompt"], result["reason"] = prompts[slot]
    options: list[dict[str, object]] = []
    operation_labels = {
        "SUM": "Total",
        "AVG": "Average",
        "MIN": "Minimum",
        "MAX": "Maximum",
        "COUNT": "Observed count",
        "subject-ratio": "Share of the total",
        "mean-delta": "Difference from the mean",
        "peer-fraction": "Share of peers strictly outperformed",
    }
    raw_options = result.get("options")
    for raw in raw_options if isinstance(raw_options, list) else []:
        if not isinstance(raw, dict):
            continue
        option = dict(raw)
        raw_choice = option.get("choice")
        choice: dict[object, object] = raw_choice if isinstance(raw_choice, dict) else {}
        kind = str(choice.get("kind") or "")
        identity = str(choice.get("id") or "")
        if kind == "ABORT":
            option.update(label="Stop", explanation="Stop this request")
        elif kind == "OTHER":
            option.update(label="Other", explanation="Provide another business condition")
        elif kind == "AGGREGATION":
            label = operation_labels.get(identity, identity)
            option.update(label=label, explanation=f"{label} over the selected scope")
        elif kind == "COMPARISON":
            label = operation_labels.get(identity, identity)
            option.update(label=label, explanation="Use this comparison definition")
        elif kind in {"METRIC", "CLAIM"}:
            option["label"] = semantic_label(locale, str(option.get("label") or ""), identity)
            if _HAN.search(str(option.get("explanation") or "")):
                option["explanation"] = "Definition declared by the current ontology"
        elif slot.startswith("scope:"):
            result["prompt"] = "Choose the business scope"
            result["reason"] = "The scope property and values come from the current ontology."
            option["explanation"] = "Observed value for this metric and authorized scope"
        elif slot in {"subject", "claimSubject"}:
            option["explanation"] = "Candidate in the current authorized scope"
        elif slot == "filter":
            option["explanation"] = "Use this filter and replace the conflicting value"
        options.append(option)
    result["options"] = options
    return result


__all__ = [
    "localize_question",
    "message_locale",
    "normalize_locale",
    "semantic_label",
    "text",
]

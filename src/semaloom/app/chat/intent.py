"""Conservative language constraints at the chat boundary, never enterprise formulas.

Only explicit supported wording is recognized. Metric vocabulary comes from the
pinned ontology; unknown language is not a claim of complete intent understanding.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import EmbeddedProperty, ValueType


@dataclass(frozen=True)
class DimensionValueHit:
    field: str
    stored: str
    value_type: ValueType
    label: str


@dataclass(frozen=True)
class DimensionSlot:
    field: str
    source_object: str
    prop: EmbeddedProperty
    terms: tuple[str, ...]


@dataclass(frozen=True)
class TurnIntent:
    year: int | None
    years: tuple[int, ...]
    comparison: str | None
    operation: str | None
    multiple_years: bool
    trend: bool
    recent_year_count: int | None
    direction: Literal["higher", "lower"]
    exclude_allowed: bool
    metric_ids: frozenset[str]
    candidates: tuple[str, ...]
    clarify_comparison: bool
    breakdown: bool
    group_label: bool
    group_prefer: str | None
    period_over_period: bool
    month_over_month: bool
    claim_ids: frozenset[str]
    claim_candidates: tuple[str, ...]
    dimension_filters: tuple[DimensionValueHit, ...]
    group_dimension: str | None
    need_dimension: str | None

    @classmethod
    def read(cls, message: str, bundle: CompiledBundle) -> TurnIntent:
        text = unicodedata.normalize("NFKC", message).casefold()
        patterns = {
            "shareOfTotal": (
                r"占(?:集合|总体|全部)?.{0,30}总(?:额|量)|总额占比|"
                r"shareoftotal|share of (?:the )?total"
            ),
            "percentAboveMean": (
                r"比(?:总体|集合)?(?:平均值|均值|平均水平).{0,8}(?:高|低|百分|"
                r"%)|相对均值|percentabovemean|(?:above|below) (?:the )?(?:mean|average)"
            ),
            "outperforms": (
                r"超过.{0,8}(?:同行|企业)|胜过|优于.{0,8}(?:同行|企业)|"
                r"outperforms|outperform"
            ),
        }
        comparisons = [op for op, pattern in patterns.items() if re.search(pattern, text)]
        deny = bool(
            re.search(
                (
                    r"(?:不要|不能|禁止|不允许|拒绝).{0,8}(?:排除|忽略|"
                    r"缺失)|(?:缺失|缺测).{0,8}(?:不要|不能)|"
                    r"do not exclude|don't exclude|reject missing"
                ),
                text,
            )
        )
        consent = bool(
            re.search(
                r"(?:同意|允许|请).{0,6}(?:排除|忽略)(?:缺失|缺测)|"
                r"(?:排除|忽略)(?:缺失|缺测).{0,4}后|exclude missing",
                text,
            )
        )
        explicit, ambiguous = _match_named(text, _metric_terms(bundle))
        claim_ids, claim_candidates = _match_named(text, _claim_terms(bundle))
        years = set(re.findall(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", text))
        recent_year_count = _recent_year_count(text)
        trend = bool(
            recent_year_count
            or re.search(r"趋势|走势|逐年|按年|历年|yearly|annual trend|over time", text)
        )
        operations = [
            operation
            for operation, pattern in {
                "mean": r"平均|均值|\bmean\b|\baverage\b",
                "sum": r"合计|总和|\bsum\b",
                "min": r"最小值|最低值|\bminimum\b",
                "max": r"最大值|最高值|\bmaximum\b",
                "count": r"有效观测数量|观测数|\bcount\b",
            }.items()
            if re.search(pattern, text)
        ]
        month_over_month = bool(re.search(r"月环比|逐月|按月环比|month.?over.?month", text))
        period_over_period = (not month_over_month) and bool(
            re.search(r"环比|同比|比上年|比去年|year.?over.?year|period.?over.?period", text)
        )
        slots = dimension_slots(bundle)
        value_hits = _match_dimension_values(text, slots)
        mentioned = _mentioned_dimensions(text, slots)
        valued_fields = {hit.field for hit in value_hits}
        group_dimension = next(
            (
                slot.field
                for slot in mentioned
                if slot.field not in valued_fields
                and any(
                    len(term) >= 2 and re.search(r"按" + re.escape(term), text)
                    for term in slot.terms
                )
            ),
            None,
        )
        if group_dimension is None:
            for slot in mentioned:
                if slot.field in valued_fields:
                    continue
                if re.search(r"按|分组|下钻|分别|各", text):
                    group_dimension = slot.field
                    break
        need_dimension = None
        if group_dimension is None:
            pending = [slot.field for slot in mentioned if slot.field not in valued_fields]
            if len(pending) == 1:
                need_dimension = pending[0]
        return cls(
            years=tuple(sorted(int(year) for year in years)),
            operation=operations[0] if len(operations) == 1 and not comparisons else None,
            multiple_years=(len(years) > 1 or recent_year_count is not None)
            and not period_over_period,
            trend=trend and not period_over_period,
            recent_year_count=recent_year_count if not period_over_period else None,
            year=(
                int(max(years))
                if period_over_period and years
                else int(next(iter(years)))
                if len(years) == 1
                else None
            ),
            comparison=comparisons[0] if len(comparisons) == 1 and not period_over_period else None,
            direction="lower" if re.search(r"越小越好|lower is better", text) else "higher",
            exclude_allowed=consent and not deny,
            metric_ids=explicit,
            candidates=tuple(sorted(ambiguous)),
            clarify_comparison=len(comparisons) > 1 or ("占优" in text and not comparisons),
            breakdown=bool(
                re.search(
                    r"各(?:企业|公司|对象|家)|每(?:家|户|个对象)|逐[个家项]|明细|"
                    r"分组|按(?:企业|公司|供应商|组织|对象|sku)|下钻",
                    text,
                )
            ),
            group_label=bool(re.search(r"按(?:企业|公司|供应商|组织)名称|按名称", text)),
            group_prefer=(
                "supplier"
                if "供应商" in text
                else "organization"
                if "组织" in text
                else "company"
                if re.search(r"企业|公司", text)
                else None
            ),
            period_over_period=period_over_period,
            month_over_month=month_over_month,
            claim_ids=claim_ids,
            claim_candidates=tuple(sorted(claim_candidates)),
            dimension_filters=value_hits,
            group_dimension=group_dimension,
            need_dimension=need_dimension,
        )

    def guidance(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "requiredOperation": self.operation,
            "requiredComparison": self.comparison,
            "direction": self.direction,
            "missingPolicy": "exclude permitted" if self.exclude_allowed else "reject only",
            "metricIds": sorted(self.metric_ids),
            "ambiguousMetricCandidates": self.candidates,
            "mustClarify": bool(self.candidates or self.clarify_comparison),
            "multipleYears": self.multiple_years,
            "trend": self.trend,
            "recentYearCount": self.recent_year_count,
            "preferBreakdown": self.breakdown,
            "periodOverPeriod": self.period_over_period,
            "claimIds": sorted(self.claim_ids),
        }


def _fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _recent_year_count(text: str) -> int | None:
    match = re.search(r"(?:近|最近)\s*([0-9一二两三四五六七八九十]+)\s*年", text)
    if match is None:
        return None
    token = match.group(1)
    if token.isdigit():
        value = int(token)
    else:
        digits = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        value = 10 if token == "十" else digits.get(token, 0)
    return value if 2 <= value <= 12 else None


def _match_named(text: str, terms: dict[str, set[str]]) -> tuple[frozenset[str], set[str]]:
    found: list[tuple[int, int, set[str]]] = []
    for term in sorted(terms, key=len, reverse=True):
        for match in re.finditer(re.escape(term), text):
            if not any(a <= match.start() and b >= match.end() for a, b, _ in found):
                found.append((match.start(), match.end(), terms[term]))
    explicit = set().union(*(ids for _, _, ids in found if len(ids) == 1))
    ambiguous = set().union(*(ids for _, _, ids in found if len(ids) > 1 and not ids & explicit))
    return frozenset(explicit), ambiguous


def _metric_terms(bundle: CompiledBundle) -> dict[str, set[str]]:
    terms: dict[str, set[str]] = {}
    for metric in bundle.metrics:
        for term in (metric.id, metric.label, *metric.aliases):
            if term:
                terms.setdefault(_fold(term), set()).add(metric.id)
    return terms


def _claim_terms(bundle: CompiledBundle) -> dict[str, set[str]]:
    terms: dict[str, set[str]] = {}
    for rule in bundle.rules:
        if not rule.claim:
            continue
        for term in (rule.claim, rule.label, *rule.aliases):
            if term:
                terms.setdefault(_fold(term), set()).add(rule.claim)
    return terms


def dimension_slots(bundle: CompiledBundle) -> tuple[DimensionSlot, ...]:
    objects = {item.id: item for item in bundle.object_types}
    slots: list[DimensionSlot] = []
    for obj in bundle.object_types:
        for prop in obj.properties:
            if not prop.values:
                continue
            slots.append(
                DimensionSlot(
                    field=f"{obj.id}.{prop.id}",
                    source_object=obj.id,
                    prop=prop,
                    terms=_property_terms(prop),
                )
            )
        for link in bundle.links:
            if link.source != obj.id or link.cardinality != "ONE":
                continue
            target = objects.get(link.target)
            if target is None:
                continue
            for prop in target.properties:
                if not prop.values:
                    continue
                slots.append(
                    DimensionSlot(
                        field=f"{target.id}.{prop.id}",
                        source_object=obj.id,
                        prop=prop,
                        terms=_property_terms(prop),
                    )
                )
    return tuple(slots)


def slots_for_metric(bundle: CompiledBundle, metric_id: str) -> tuple[DimensionSlot, ...]:
    metric = next((item for item in bundle.metrics if item.id == metric_id), None)
    if metric is None:
        return ()
    return tuple(
        slot for slot in dimension_slots(bundle) if slot.source_object == metric.object_type
    )


def _property_terms(prop: EmbeddedProperty) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            _fold(term) for term in (prop.label or "", prop.id, *prop.aliases) if term.strip()
        )
    )


def _match_dimension_values(
    text: str, slots: tuple[DimensionSlot, ...]
) -> tuple[DimensionValueHit, ...]:
    hits: list[tuple[int, int, DimensionValueHit]] = []
    candidates: list[tuple[str, DimensionValueHit]] = []
    for slot in slots:
        for item in slot.prop.values:
            terms = [
                _fold(term)
                for term in (item.label or "", item.id, *item.aliases)
                if term and str(term).strip()
            ]
            for term in sorted(set(terms), key=len, reverse=True):
                if len(term) < 1:
                    continue
                candidates.append(
                    (
                        term,
                        DimensionValueHit(
                            field=slot.field if "." in slot.field else slot.prop.id,
                            stored=item.id,
                            value_type=slot.prop.value_type,
                            label=item.label or item.id,
                        ),
                    )
                )
    for term, hit in sorted(candidates, key=lambda row: len(row[0]), reverse=True):
        for match in re.finditer(re.escape(term), text):
            if not any(start <= match.start() and end >= match.end() for start, end, _ in hits):
                hits.append((match.start(), match.end(), hit))
    unique: dict[str, DimensionValueHit] = {}
    for _, _, hit in hits:
        unique[hit.field] = hit
    return tuple(unique.values())


def _mentioned_dimensions(text: str, slots: tuple[DimensionSlot, ...]) -> list[DimensionSlot]:
    mentioned: list[DimensionSlot] = []
    seen: set[str] = set()
    for slot in slots:
        if slot.field in seen:
            continue
        if any(term and len(term) >= 2 and term in text for term in slot.terms):
            mentioned.append(slot)
            seen.add(slot.field)
    return mentioned

"""Conservative language constraints at the chat boundary, never enterprise formulas.

Only explicit supported wording is recognized. Metric vocabulary comes from the
pinned ontology; unknown language is not a claim of complete intent understanding.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast

from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import EmbeddedProperty, MetricDef, ValueType


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
class RoleConstraint:
    """Language-adapter output resolved against ontology roles by orchestration."""

    role: str
    value_type: ValueType
    operator: Literal["EQ", "IN"]
    values: tuple[str | int | bool, ...]


@dataclass(frozen=True)
class TurnIntent:
    role_constraints: tuple[RoleConstraint, ...]
    grouping_role: str | None
    grouping_limit: int | None
    formula_shape: Literal["previous", "subject_ratio", "mean_delta", "peer"] | None
    peer_relation: Literal["LT", "GT"] | None
    operation: str | None
    direction: Literal["higher", "lower"]
    exclude_allowed: bool
    metric_ids: frozenset[str]
    candidates: tuple[str, ...]
    clarify_formula: bool
    clarify_grouping: bool
    claim_ids: frozenset[str]
    claim_candidates: tuple[str, ...]
    dimension_filters: tuple[DimensionValueHit, ...]
    group_dimension: str | None
    need_dimension: str | None

    @classmethod
    def read(cls, message: str, bundle: CompiledBundle) -> TurnIntent:
        text = unicodedata.normalize("NFKC", message).casefold()
        shapes = [
            shape
            for shape, pattern in {
                "subject_ratio": (
                    r"占(?:集合|总体|全部)?.{0,30}总(?:额|量)|总额占比|share of (?:the )?total"
                ),
                "mean_delta": (
                    r"比(?:总体|集合)?(?:平均值|均值|平均水平).{0,8}(?:高|低|百分|%)|"
                    r"相对均值|(?:above|below) (?:the )?(?:mean|average)"
                ),
                "peer": r"超过.{0,12}同行|胜过|优于.{0,12}|outperform",
            }.items()
            if re.search(pattern, text)
        ]
        previous = bool(
            re.search(
                r"月环比|逐月|环比|同比|比上年|比去年|较上期|上一期|"
                r"year.?over.?year|period.?over.?period|month.?over.?month",
                text,
            )
        )
        if previous:
            shapes.append("previous")
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
        if not explicit and not ambiguous:
            ambiguous = _overlap_metric_ids(text, bundle)
        claim_ids, claim_candidates = _match_named(text, _claim_terms(bundle))
        years = set(re.findall(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", text))
        recent_count = _recent_period_count(text)
        sequence_requested = bool(
            recent_count
            or re.search(r"趋势|走势|逐年|按年|历年|yearly|annual trend|over time", text)
        )
        operations = [
            operation
            for operation, pattern in {
                "mean": r"平均|均值|\bmean\b|\baverage\b",
                "sum": r"合计|总和|汇总|总计|\bsum\b",
                "min": r"最小值|最低值|\bminimum\b",
                "max": r"最大值|最高值|\bmaximum\b",
                "count": r"有效观测数量|观测数|\bcount\b",
            }.items()
            if re.search(pattern, text)
        ]
        numeric_periods = tuple(sorted(int(value) for value in years))
        # A year token inside YYYY-MM is the month token, not a second constraint.
        if re.search(r"(?<!\d)(?:19|20|21)\d{2}-\d{2}(?!\d)", text):
            numeric_periods = ()
        selected_periods = (
            (max(numeric_periods),) if previous and numeric_periods else numeric_periods
        )
        role_constraints = (
            (
                RoleConstraint(
                    role="integer-scope",
                    value_type="INTEGER",
                    operator="IN" if len(selected_periods) > 1 else "EQ",
                    values=selected_periods,
                ),
            )
            if selected_periods
            else ()
        )
        grouping_role = (
            "scope"
            if (len(selected_periods) > 1 and not previous) or (sequence_requested and not previous)
            else None
        )
        # Dictionary values are scoped to the metric's object graph when the
        # metric is known.  Matching every dictionary in a multi-domain bundle
        # makes short aliases such as ``高`` leak out of unrelated prose (for
        # example, the ``高`` in ``从高到低`` becoming a delivery-risk filter).
        slots = _slots_for_metrics(bundle, explicit or frozenset(ambiguous))
        value_hits = _match_dimension_values(text, slots)
        if not explicit and not ambiguous and value_hits:
            ambiguous = _metrics_for_dimension_hits(bundle, value_hits)
        mentioned = _mentioned_dimensions(text, slots)
        valued_fields = {hit.field for hit in value_hits}
        group_dimension = _group_field(text, bundle, explicit or frozenset(ambiguous))
        if group_dimension in valued_fields:
            group_dimension = None
        grouping_requested = bool(
            re.search(r"分组|下钻", text)
            or re.search(r"按(?!照).{0,16}(?:合计|汇总|统计|分组)", text)
        )
        need_dimension = None
        if group_dimension is None:
            pending = [slot.field for slot in mentioned if slot.field not in valued_fields]
            if len(pending) == 1 and not grouping_requested:
                need_dimension = pending[0]
        direction: Literal["higher", "lower"] = (
            "lower" if re.search(r"越小越好|lower is better", text) else "higher"
        )
        return cls(
            role_constraints=role_constraints,
            grouping_role=grouping_role,
            grouping_limit=recent_count if grouping_role else None,
            formula_shape=(
                cast(
                    Literal["previous", "subject_ratio", "mean_delta", "peer"],
                    shapes[0],
                )
                if len(shapes) == 1
                else None
            ),
            peer_relation="GT" if direction == "lower" else "LT",
            operation=(
                operations[0] if len(operations) == 1 and shapes in ([], ["previous"]) else None
            ),
            direction=direction,
            exclude_allowed=consent and not deny,
            metric_ids=explicit,
            candidates=rank_metric_ids(text, bundle, ambiguous),
            clarify_formula=len(shapes) > 1 or ("占优" in text and not shapes),
            clarify_grouping=grouping_requested and group_dimension is None,
            claim_ids=claim_ids,
            claim_candidates=tuple(sorted(claim_candidates)),
            dimension_filters=value_hits,
            group_dimension=group_dimension,
            need_dimension=need_dimension,
        )

    def guidance(self) -> dict[str, Any]:
        return {
            "roleConstraints": [
                {
                    "role": item.role,
                    "valueType": item.value_type,
                    "operator": item.operator,
                    "values": item.values,
                }
                for item in self.role_constraints
            ],
            "requiredOperation": self.operation,
            "formulaShape": self.formula_shape,
            "direction": self.direction,
            "missingPolicy": "exclude permitted" if self.exclude_allowed else "reject only",
            "metricIds": sorted(self.metric_ids),
            "ambiguousMetricCandidates": self.candidates,
            "mustClarify": bool(self.candidates or self.clarify_formula or self.clarify_grouping),
            "groupingRole": self.grouping_role,
            "groupingLimit": self.grouping_limit,
            "claimIds": sorted(self.claim_ids),
        }


def _group_field(text: str, bundle: CompiledBundle, metric_ids: frozenset[str]) -> str | None:
    """Bind 按{label} to a property using ontology labels and aliases only."""

    metrics = [
        metric
        for metric in bundle.metrics
        if metric.id in metric_ids or (not metric_ids and metric.population is not None)
    ]
    if metric_ids:
        metrics = [metric for metric in bundle.metrics if metric.id in metric_ids]
    objects = {item.id: item for item in bundle.object_types}
    best: tuple[int, str] | None = None
    ambiguous = False
    for metric in metrics:
        owners = [objects.get(metric.object_type)]
        for link in bundle.links:
            if (
                link.source == metric.object_type
                and link.cardinality == "ONE"
                and len(link.identity) == 1
            ):
                owners.append(objects.get(link.target))
        for owner in owners:
            if owner is None:
                continue
            for prop in owner.properties:
                if prop.unit:
                    continue
                field = prop.id if owner.id == metric.object_type else f"{owner.id}.{prop.id}"
                labels = [prop.label or "", *prop.aliases]
                if owner.label and owner.id != metric.object_type:
                    if prop.label:
                        labels.append(f"{owner.label}{prop.label}")
                    labels.extend(f"{owner.label}{alias}" for alias in prop.aliases if alias)
                    descriptive = [
                        item
                        for item in owner.properties
                        if item.unit is None
                        and item.value_type == "STRING"
                        and item.id not in owner.identity_keys
                    ]
                    if len(descriptive) == 1 and prop.id == descriptive[0].id:
                        labels.append(owner.label)
                for label in labels:
                    term = _fold(label)
                    if len(term) < 2 or not re.search("(?:按|各)" + re.escape(term), text):
                        continue
                    if best is None or len(term) > best[0]:
                        best = (len(term), field)
                        ambiguous = False
                    elif len(term) == best[0] and field != best[1]:
                        ambiguous = True
    if best is None or ambiguous:
        return None
    return best[1]


def _fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _recent_period_count(text: str) -> int | None:
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


_MIN_TERM_OVERLAP = 4


def _metric_terms_for(metric: MetricDef) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            _fold(term)
            for term in (metric.id, metric.label or "", *metric.aliases)
            if term and str(term).strip()
        )
    )


def _term_overlap(text: str, term: str) -> int:
    if not term:
        return 0
    if term in text:
        return len(term)
    limit = min(len(term), len(text))
    for length in range(limit, _MIN_TERM_OVERLAP - 1, -1):
        for index in range(len(term) - length + 1):
            if term[index : index + length] in text:
                return length
    return 0


def metric_score(text: str, metric: MetricDef) -> int:
    return max((_term_overlap(text, term) for term in _metric_terms_for(metric)), default=0)


def rank_metric_ids(text: str, bundle: CompiledBundle, ids: Iterable[str]) -> tuple[str, ...]:
    index = {metric.id: metric for metric in bundle.metrics}
    ranked: list[tuple[int, str]] = []
    for metric_id in ids:
        metric = index.get(metric_id)
        if metric is None:
            continue
        ranked.append((-metric_score(text, metric), metric_id))
    ranked.sort()
    return tuple(metric_id for _, metric_id in ranked)


def _overlap_metric_ids(text: str, bundle: CompiledBundle) -> set[str]:
    scored = [
        (metric_score(text, metric), metric.id)
        for metric in bundle.metrics
        if metric_score(text, metric) >= _MIN_TERM_OVERLAP
    ]
    if not scored:
        return set()
    best = max(score for score, _ in scored)
    return {metric_id for score, metric_id in scored if score == best}


def _metrics_for_dimension_hits(
    bundle: CompiledBundle, hits: tuple[DimensionValueHit, ...]
) -> set[str]:
    objects = {hit.field.rsplit(".", 1)[0] for hit in hits if "." in hit.field}
    return {
        metric.id
        for metric in bundle.metrics
        if metric.object_type in objects and metric.population is not None
    }


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
        slot
        for slot in dimension_slots(bundle)
        if slot.source_object == metric.object_type
        and slot.field.split(".")[-1] not in metric.select
    )


def _slots_for_metrics(
    bundle: CompiledBundle, metric_ids: frozenset[str]
) -> tuple[DimensionSlot, ...]:
    if not metric_ids:
        return dimension_slots(bundle)
    slots: list[DimensionSlot] = []
    seen: set[str] = set()
    for metric_id in sorted(metric_ids):
        for slot in slots_for_metric(bundle, metric_id):
            if slot.field not in seen:
                seen.add(slot.field)
                slots.append(slot)
    return tuple(slots)


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
            # One-character dictionary aliases are useful when the user names
            # the property (``交货风险高``), but far too ambiguous on their own.
            # Require a nearby property label/alias so ordinary language such
            # as ``从高到低排名`` cannot become a hidden filter.
            if len(term) <= 1 and not _has_value_context(
                text, match.start(), match.end(), hit, slots
            ):
                continue
            if not any(start <= match.start() and end >= match.end() for start, end, _ in hits):
                hits.append((match.start(), match.end(), hit))
    unique: dict[str, DimensionValueHit] = {}
    for _, _, hit in hits:
        unique[hit.field] = hit
    return tuple(unique.values())


def _has_value_context(
    text: str,
    start: int,
    end: int,
    hit: DimensionValueHit,
    slots: tuple[DimensionSlot, ...],
) -> bool:
    slot = next((item for item in slots if item.field == hit.field), None)
    if slot is None:
        return False
    property_terms = {term for term in slot.terms if len(term) >= 2}
    if not property_terms:
        return False
    window = text[max(0, start - 12) : min(len(text), end + 12)]
    return any(term in window for term in property_terms)


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

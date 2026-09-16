"""Conservative language constraints at the chat boundary, never enterprise formulas.

Only explicit supported wording is recognized. Metric vocabulary comes from the
pinned ontology; unknown language is not a claim of complete intent understanding.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from semaloom.core.bundle import CompiledBundle


@dataclass(frozen=True)
class TurnIntent:
    year: int | None
    years: tuple[int, ...]
    comparison: str | None
    operation: str | None
    multiple_years: bool
    direction: str
    exclude_allowed: bool
    metric_ids: frozenset[str]
    candidates: tuple[str, ...]
    clarify_comparison: bool
    breakdown: bool

    @classmethod
    def read(cls, message: str, bundle: CompiledBundle) -> TurnIntent:
        text = unicodedata.normalize("NFKC", message).casefold()
        patterns = {
            "shareOfTotal": (
                r"占(?:集合|总体|全部)?总(?:额|量)|总额占比|"
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
        terms: dict[str, set[str]] = {}
        for metric in bundle.metrics:
            for term in (metric.id, metric.label, *metric.aliases):
                if term:
                    terms.setdefault(unicodedata.normalize("NFKC", term).casefold(), set()).add(
                        metric.id
                    )
        found: list[tuple[int, int, set[str]]] = []
        for term in sorted(terms, key=len, reverse=True):
            for match in re.finditer(re.escape(term), text):
                if not any(a <= match.start() and b >= match.end() for a, b, _ in found):
                    found.append((match.start(), match.end(), terms[term]))
        explicit = set().union(*(ids for _, _, ids in found if len(ids) == 1))
        ambiguous = set().union(
            *(ids for _, _, ids in found if len(ids) > 1 and not ids & explicit)
        )
        years = set(re.findall(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", text))
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
        return cls(
            years=tuple(sorted(int(year) for year in years)),
            operation=operations[0] if len(operations) == 1 and not comparisons else None,
            multiple_years=len(years) > 1,
            year=int(next(iter(years))) if len(years) == 1 else None,
            comparison=comparisons[0] if len(comparisons) == 1 else None,
            direction="lower" if re.search(r"越小越好|lower is better", text) else "higher",
            exclude_allowed=consent and not deny,
            metric_ids=frozenset(explicit),
            candidates=tuple(sorted(ambiguous)),
            clarify_comparison=len(comparisons) > 1 or ("占优" in text and not comparisons),
            breakdown=bool(
                re.search(
                    r"各(?:企业|公司|对象|家)|每(?:家|户|个对象)|逐[个家项]|明细|"
                    r"分组|按(?:企业|公司|对象|sku)",
                    text,
                )
            ),
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
            "preferBreakdown": self.breakdown,
        }

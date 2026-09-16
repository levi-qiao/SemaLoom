"""Population narratives from engine values, not model arithmetic."""

# ruff: noqa: RUF001 -- Chinese UI prose uses Chinese punctuation.

from __future__ import annotations

from typing import Any

from semaloom.core.bundle import CompiledBundle
from semaloom.core.semantic_query import FilterAtom, FilterGroup, QueryResult, SemanticQuery

OPERATIONS = {
    "mean": "平均值",
    "sum": "合计",
    "min": "最小值",
    "max": "最大值",
    "count": "有效观测数量",
}
COMPARISONS = {
    "shareOfTotal": "占集合总额比例",
    "percentAboveMean": "相对集合均值增幅",
    "outperforms": "严格优于同行比例",
}


def _filter_description(node: FilterAtom | FilterGroup | None) -> str:
    if node is None:
        return "无额外筛选"
    if isinstance(node, FilterAtom):
        value = node.value.value
        rendered = "、".join(str(v) for v in value) if isinstance(value, tuple) else str(value)
        return f"{node.field} {node.op} {rendered}"
    return "(" + (f" {node.kind} ").join(_filter_description(arg) for arg in node.args) + ")"


def semantic_summary(
    bundle: CompiledBundle,
    query: SemanticQuery,
    result: QueryResult,
    assumptions: list[dict[str, str]] | None = None,
    confidence: dict[str, Any] | None = None,
) -> str:
    labels = {metric.id: metric.label or metric.id for metric in bundle.metrics}
    rows: list[str] = []
    headline = _headline(labels, result)
    if headline:
        rows.append(headline)
    rows.append("筛选范围：" + _filter_description(query.filters) + "。")
    scopes = result.scope.get("metrics", {})
    for ref in query.metrics:
        scope = scopes.get(ref.id, result.scope)
        rows.append(
            f"{labels[ref.id]}：范围内 {scope.get('populationCount')} 个对象，"
            f"有效 {scope.get('observedCount')} 个，缺失 {scope.get('missingCount')} 个。"
        )
        if scope.get("reason"):
            rows.append("无法确定数值：" + scope["reason"] + "。缺失不当零。")
    for value in result.values:
        grain = "；".join(
            (
                f"{key} = {value.get('labels', {}).get(key)}（{item}）"
                if value.get("labels", {}).get(key)
                else f"{key} = {item}"
            )
            for key, item in value.get("grain", {}).items()
        )
        operation = OPERATIONS[
            {"SUM": "sum", "AVG": "mean", "MIN": "min", "MAX": "max", "COUNT": "count"}[
                value["aggregation"]
            ]
        ]
        display_value = value["value"] if value["value"] is not None else "未知"
        rows.append(
            f"{labels[value['metric']]}{('（' + grain + '）') if grain else ''}，"
            f"{operation}：{display_value} {value['unit']}。"
        )
    comparison = result.scope.get("comparison")
    if comparison:
        if comparison.get("value") is None:
            rows.append("比较无法确定：" + str(comparison.get("reason")) + "。")
        else:
            rows.append(
                f"{COMPARISONS[comparison['operation']]}：{comparison['value']}%。"
                f"分子 {comparison['numerator']}，分母 {comparison['denominator']}。"
            )
            if query.comparison and query.comparison.op == "STRICT_PEER":
                rows.append(
                    "按越小越好比较。"
                    if query.comparison.direction == "lower"
                    else "按越大越好比较。"
                )
    rows.append(
        "缺失处理："
        + ("按用户选择排除缺失。" if query.missing_policy == "exclude" else "存在缺失则不计算。")
    )
    if assumptions:
        rows.append("系统默认：" + "；".join(_assumption_line(item) for item in assumptions) + "。")
    if confidence:
        rows.append(
            f"置信度：{confidence['label']}（{confidence['score']}）。"
            + "规则只用于评分，不阻止回答。"
        )
    rows.append("结果限于当前授权、筛选范围和来源快照；不自动代表范围外事实或业务认可。")
    return "\n\n".join(rows)


def _headline(labels: dict[str, str], result: QueryResult) -> str | None:
    totals = [item for item in result.values if not item.get("grain")]
    if len(totals) != 1 or totals[0]["value"] is None:
        return None
    value = totals[0]
    operation = OPERATIONS[
        {"SUM": "sum", "AVG": "mean", "MIN": "min", "MAX": "max", "COUNT": "count"}[
            value["aggregation"]
        ]
    ]
    name = labels.get(value["metric"], value["metric"])
    return f"{name}{operation} {value['value']} {value['unit']}。"


def _assumption_line(item: dict[str, str]) -> str:
    if item["slot"] == "year":
        return f"年份未指定，按来源最新年度 {item['id']}"
    if item["slot"] == "aggregation":
        return "未指定统计方式，按金额/数量可加性取合计"
    if item["slot"] == "grain":
        return "未要求明细，按总体回答"
    return item.get("reason") or item["slot"]


def _pairs(value: dict[str, Any]) -> str:
    return "；".join(f"{key} = {item}" for key, item in value.items()) or "无额外筛选"


def evidence_summary(evidence: list[dict[str, Any]]) -> str:
    """Only engine facts enter definitive prose; free model prose cannot assert truth."""
    lines: list[str] = []
    for entry in evidence:
        result = entry["result"]
        for claim_result in [result, *result.get("checks", [])]:
            claim = claim_result.get("claim")
            if claim:
                lines.append(
                    f"命题 {claim.get('claimId')}：{claim.get('truth')}。"
                    f"原因：{_pairs({'原因码': claim.get('reasonCodes', [])})}。"
                )
            elif claim_result.get("error"):
                lines.append(f"规则未完成：{claim_result['error']}。不能判断为通过。")
        for observation in result.get("observations", []):
            observed = observation.get("value") if observation.get("kind") == "PRESENT" else "未知"
            if observation.get("valueType") == "OBJECT":
                observed = "属性见证据表"
            lines.append(
                f"{observation.get('target')}：{observed} "
                f"{observation.get('unit') or ''}（{observation.get('kind')}；"
                f"{observation.get('reason') or '见证据'}）。"
            )
        if "objects" in result:
            lines.append(
                f"本次找到 {len(result['objects'])} 条匹配记录，具体身份与属性见证据表。"
                + ("还有未展示记录。" if result.get("hasMore") else "结果限于当前授权和筛选范围。")
            )
    if not lines:
        raise ValueError("FACTUAL_EVIDENCE_REQUIRED")
    lines.append(
        "以上为来源观测和已定义规则的结果；UNKNOWN 不等于 FALSE，规则成立不自动代表业务合规。"
    )
    return "\n\n".join(lines)

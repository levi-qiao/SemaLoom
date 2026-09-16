"""Ontology-general answer confidence. Not a gate and not per-question rules."""

# ruff: noqa: RUF001 -- Chinese UI copy uses Chinese punctuation.

from __future__ import annotations

from typing import Any

from semaloom.app.chat.intent import TurnIntent
from semaloom.core.bundle import CompiledBundle
from semaloom.core.semantic_query import QueryResult, SemanticQuery

_LEVELS = ((0.85, "high", "高"), (0.6, "medium", "中"), (0.0, "low", "低"))


def score_answer(
    bundle: CompiledBundle,
    intent: TurnIntent,
    query: SemanticQuery,
    result: QueryResult,
    assumptions: list[dict[str, str]],
) -> dict[str, Any]:
    assumed = {item["slot"]: item for item in assumptions}
    factors = [
        _metric_factor(bundle, intent, query),
        _slot_factor("year", intent.year is not None, "year" in assumed, "年份"),
        _slot_factor(
            "aggregation", intent.operation is not None, "aggregation" in assumed, "统计方式"
        ),
        _grain_factor(intent, query, assumed),
        _data_factor(result),
        _rule_factor(result),
    ]
    weights = {
        "METRIC": 0.3,
        "YEAR": 0.2,
        "AGGREGATION": 0.15,
        "GRAIN": 0.1,
        "DATA": 0.15,
        "RULE": 0.1,
    }
    total_weight = sum(weights[item["code"]] for item in factors)
    score = round(sum(item["score"] * weights[item["code"]] for item in factors) / total_weight, 3)
    level, label = next((name, text) for threshold, name, text in _LEVELS if score >= threshold)
    return {"score": score, "level": level, "label": label, "factors": factors}


def _metric_factor(
    bundle: CompiledBundle, intent: TurnIntent, query: SemanticQuery
) -> dict[str, Any]:
    labels = {metric.id: metric.label or metric.id for metric in bundle.metrics}
    names = "、".join(labels.get(item.id, item.id) for item in query.metrics) or "未选定"
    if intent.candidates:
        return {
            "code": "METRIC",
            "score": 0.35,
            "detail": f"业务词对应多个指标，当前按 {names} 回答",
        }
    if intent.metric_ids:
        return {"code": "METRIC", "score": 1.0, "detail": f"与指标「{names}」唯一对应"}
    if query.metrics:
        return {
            "code": "METRIC",
            "score": 0.7,
            "detail": f"按已确认指标「{names}」继续",
        }
    return {"code": "METRIC", "score": 0.2, "detail": "尚未对应到唯一指标"}


def _slot_factor(slot: str, user_stated: bool, assumed: bool, label: str) -> dict[str, Any]:
    code = slot.upper()
    if user_stated:
        return {"code": code, "score": 1.0, "detail": f"{label}由问题明确给出"}
    if assumed:
        return {
            "code": code,
            "score": 0.65,
            "detail": f"{label}未指定，已按本体默认补齐并计入置信度",
        }
    return {"code": code, "score": 0.85, "detail": f"{label}沿用已确认口径"}


def _grain_factor(
    intent: TurnIntent, query: SemanticQuery, assumed: dict[str, dict[str, str]]
) -> dict[str, Any]:
    if intent.breakdown:
        return {"code": "GRAIN", "score": 1.0, "detail": "按用户要求展开明细"}
    if "grain" in assumed or query.group_by:
        return {
            "code": "GRAIN",
            "score": 0.7,
            "detail": "未要求明细，按总体合计回答",
        }
    return {"code": "GRAIN", "score": 0.85, "detail": "总体口径，未展开分组"}


def _data_factor(result: QueryResult) -> dict[str, Any]:
    scope = result.scope.get("metrics") or result.scope
    if isinstance(scope, dict) and result.scope.get("metrics"):
        first = next(iter(result.scope["metrics"].values()), result.scope)
        scope = first if isinstance(first, dict) else result.scope
    reason = scope.get("reason") if isinstance(scope, dict) else None
    missing = int(scope.get("missingCount") or 0) if isinstance(scope, dict) else 0
    observed = int(scope.get("observedCount") or 0) if isinstance(scope, dict) else 0
    if reason:
        return {
            "code": "DATA",
            "score": 0.35,
            "detail": "当前范围未能得到完整数值：" + str(reason),
        }
    if observed == 0:
        return {"code": "DATA", "score": 0.3, "detail": "范围内没有有效观测"}
    if missing:
        return {
            "code": "DATA",
            "score": 0.6,
            "detail": f"有效 {observed} 个，缺失 {missing} 个；缺失不当零",
        }
    return {"code": "DATA", "score": 1.0, "detail": f"范围内 {observed} 个对象全部有效"}


def _rule_factor(result: QueryResult) -> dict[str, Any]:
    checks = result.scope.get("checks") if isinstance(result.scope, dict) else None
    if not isinstance(checks, list) or not checks:
        return {
            "code": "RULE",
            "score": 0.8,
            "detail": "无已覆盖的命题规则；规则只评分，不阻止回答",
        }
    truths = [str(item.get("claim", {}).get("truth") or item.get("error") or "") for item in checks]
    if any(item == "FALSE" for item in truths):
        return {
            "code": "RULE",
            "score": 0.45,
            "detail": "已覆盖规则存在 FALSE，数值仍展示供核对",
        }
    if any(item in {"UNKNOWN", ""} or item.startswith("POLICY") for item in truths):
        return {
            "code": "RULE",
            "score": 0.55,
            "detail": "已覆盖规则未全部确定，不视为通过",
        }
    if all(item == "TRUE" for item in truths):
        return {
            "code": "RULE",
            "score": 1.0,
            "detail": "已覆盖规则均为 TRUE；不等于其他业务判断成立",
        }
    return {"code": "RULE", "score": 0.7, "detail": "已执行部分规则，仅作置信参考"}

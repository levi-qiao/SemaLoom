"""Server-owned choice persist/merge. Clients submit option ids only."""

# ruff: noqa: RUF001 -- Chinese UI prompts use Chinese punctuation.

from __future__ import annotations

import re
import uuid
from typing import Any

from semaloom.app.chat.confidence import score_answer
from semaloom.app.chat.intent import TurnIntent
from semaloom.app.chat.presentation import attach_lineage
from semaloom.app.chat.store import ChatStore
from semaloom.app.chat.summary import semantic_summary
from semaloom.core.bundle import CompiledBundle
from semaloom.core.semantic_query import (
    ChoiceError,
    ChoiceOption,
    ChoiceQuestion,
    ChoiceSubmit,
    ComparisonExpr,
    FilterAtom,
    FilterGroup,
    GroupByItem,
    MetricRef,
    QueryResult,
    SemanticChoice,
    SemanticQuery,
    TypedValue,
    _append_filter,
    equality_value,
    field_constrained,
    merge_decision,
    with_choice_exits,
)
from semaloom.runtime.analysis import AnalysisError, execute, prepare
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService

_AGG = {"mean": "AVG", "sum": "SUM", "min": "MIN", "max": "MAX", "count": "COUNT"}


def _year_property(bundle: CompiledBundle, metric_ids: set[str] | frozenset[str]) -> str | None:
    fields: set[str] = set()
    for metric_id in metric_ids:
        metric = next((item for item in bundle.metrics if item.id == metric_id), None)
        if metric is not None and metric.population is not None:
            fields.add(metric.population.year_property)
    if len(fields) == 1:
        return next(iter(fields))
    return None


def _year_filter(field: str, year: int) -> FilterAtom:
    return FilterAtom(
        field=field,
        op="EQ",
        value=TypedValue(value_type="INTEGER", value=year),
    )


def query_from_intent(intent: TurnIntent, bundle: CompiledBundle) -> SemanticQuery:
    metrics = tuple(MetricRef(id=item) for item in sorted(intent.metric_ids))
    filters = None
    year_field = _year_property(bundle, intent.metric_ids)
    if intent.year is not None and year_field:
        filters = _year_filter(year_field, intent.year)
    if intent.multiple_years and year_field:
        filters = FilterAtom(
            field=year_field, op="IN", value=TypedValue(value_type="INTEGER", value=intent.years)
        )
    aggregation = (
        _AGG.get(intent.operation) if intent.operation else "SUM" if intent.comparison else None
    )
    metrics = tuple(item.model_copy(update={"aggregation": aggregation}) for item in metrics)
    comparison = None
    if intent.comparison and len(metrics) == 1:
        comparison = ComparisonExpr(
            op={
                "shareOfTotal": "SHARE_OF_TOTAL",
                "percentAboveMean": "RELATIVE_TO_MEAN",
                "outperforms": "STRICT_PEER",
            }[intent.comparison],
            metric=metrics[0].id,
            direction=intent.direction,
        )
    group_by: tuple[GroupByItem, ...] = ()
    if intent.breakdown and metrics:
        metric = next((item for item in bundle.metrics if item.id == metrics[0].id), None)
        if metric is not None and metric.population is not None:
            group_by = (GroupByItem(id=metric.population.unit_property),)
    return SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=metrics,
        filters=filters,
        group_by=group_by,
        comparison=comparison,
        missing_policy="exclude" if intent.exclude_allowed else "reject",
    )


def _apply_intent(
    query: SemanticQuery, intent: TurnIntent, bundle: CompiledBundle
) -> SemanticQuery:
    updates: dict[str, Any] = {}
    metrics = query.metrics
    if intent.metric_ids:
        existing = {ref.id for ref in metrics}
        if not existing:
            metrics = tuple(MetricRef(id=item) for item in sorted(intent.metric_ids))
            updates["metrics"] = metrics
        elif not intent.metric_ids <= existing:
            raise AnalysisError("REQUEST_METRIC_DOES_NOT_MATCH_USER")
    year_field = _year_property(bundle, {item.id for item in metrics})
    if intent.year is not None and year_field is not None:
        existing_year = equality_value(query.filters, year_field)
        if field_constrained(query.filters, year_field) and existing_year != intent.year:
            raise AnalysisError("REQUEST_YEAR_DOES_NOT_MATCH_USER")
        if existing_year is None:
            updates["filters"] = _append_filter(
                query.filters, _year_filter(year_field, intent.year)
            )
    if intent.operation and metrics:
        aggregation = _AGG[intent.operation]
        if any(item.aggregation and item.aggregation != aggregation for item in metrics):
            raise AnalysisError("AGGREGATION_DOES_NOT_MATCH_USER")
        updates["metrics"] = tuple(
            item.model_copy(update={"aggregation": aggregation}) for item in metrics
        )
    if (
        query.missing_policy == "exclude"
        and not intent.exclude_allowed
        and not any(
            decision.choice.kind == "MISSING_POLICY" and decision.choice.id == "exclude"
            for decision in query.decisions
        )
    ):
        raise AnalysisError("MISSING_EXCLUSION_NOT_AUTHORIZED")
    if intent.comparison:
        required = {
            "shareOfTotal": "SHARE_OF_TOTAL",
            "percentAboveMean": "RELATIVE_TO_MEAN",
            "outperforms": "STRICT_PEER",
        }[intent.comparison]
        if query.comparison is None or query.comparison.op != required:
            raise AnalysisError("COMPARISON_REQUIRED_BY_USER")
        if intent.comparison == "outperforms" and query.comparison.direction != intent.direction:
            raise AnalysisError("COMPARISON_DIRECTION_DOES_NOT_MATCH_USER")
    if intent.multiple_years:
        # Do not accept a single-year proposal as an answer to a multi-year request.
        def years(node: FilterAtom | FilterGroup | None) -> set[int]:
            if (
                isinstance(node, FilterAtom)
                and year_field
                and node.field.split(".")[-1] == year_field
            ):
                value = node.value.value
                if node.op == "EQ":
                    return {int(str(value))}
                if node.op == "IN" and isinstance(value, tuple):
                    return {int(v) for v in value}
            if isinstance(node, FilterGroup):
                return set().union(*(years(arg) for arg in node.args))
            return set()

        if not set(intent.years) <= years(updates.get("filters", query.filters)):
            raise AnalysisError("REQUEST_YEAR_DOES_NOT_MATCH_USER")
    return query.model_copy(update=updates) if updates else query


def _years_for(service: QueryService, metric_id: str, tenant: str) -> list[int]:
    handler = getattr(service.provider, "analysis_years", None)
    if not callable(handler):
        return []
    try:
        return list(handler(service.bundle, metric_id, tenant))
    except (AnalysisError, ConnectionError, OSError):
        return []


def _apply_defaults(
    query: SemanticQuery,
    intent: TurnIntent,
    bundle: CompiledBundle,
    service: QueryService,
    actor: RequestActor,
) -> tuple[SemanticQuery, list[dict[str, str]]]:
    """Fill only Chat-layer defaults. Engine prepare still rejects incomplete queries."""
    updates: dict[str, Any] = {}
    assumptions: list[dict[str, str]] = []
    decided = {item.choice.kind for item in query.decisions}
    if query.group_by and not intent.breakdown:
        updates["group_by"] = ()
        assumptions.append({"slot": "grain", "id": "total", "reason": "USER_DID_NOT_ASK_BREAKDOWN"})
    elif intent.breakdown and not query.group_by and query.metrics:
        metric = next((item for item in bundle.metrics if item.id == query.metrics[0].id), None)
        if metric is not None and metric.population is not None:
            updates["group_by"] = (GroupByItem(id=metric.population.unit_property),)
    year_field = _year_property(bundle, {item.id for item in query.metrics})
    if (
        year_field
        and intent.year is None
        and "YEAR" not in decided
        and query.metrics
        and not intent.multiple_years
    ):
        existing_year = equality_value(query.filters, year_field)
        if existing_year is None:
            years = _years_for(service, query.metrics[0].id, actor.tenant)
            if years:
                latest = max(years)
                updates["filters"] = _append_filter(query.filters, _year_filter(year_field, latest))
                assumptions.append(
                    {"slot": "year", "id": str(latest), "reason": "LATEST_AVAILABLE_YEAR"}
                )
        else:
            assumptions.append(
                {"slot": "year", "id": str(existing_year), "reason": "LATEST_AVAILABLE_YEAR"}
            )
    if query.metrics and intent.operation is None and "AGGREGATION" not in decided:
        if any(item.aggregation is None or item.aggregation != "SUM" for item in query.metrics):
            updates["metrics"] = tuple(
                item.model_copy(update={"aggregation": "SUM"}) for item in query.metrics
            )
        assumptions.append(
            {"slot": "aggregation", "id": "SUM", "reason": "ADDITIVE_MEASURE_DEFAULT"}
        )
    return query.model_copy(update=updates) if updates else query, assumptions


def _follow_ups(
    bundle: CompiledBundle,
    query: SemanticQuery,
    assumptions: list[dict[str, str]],
    years: list[int],
) -> list[dict[str, str]]:
    labels = {metric.id: metric.label or metric.id for metric in bundle.metrics}
    name = labels.get(query.metrics[0].id, query.metrics[0].id) if query.metrics else ""
    assumed_year = next((item["id"] for item in assumptions if item["slot"] == "year"), None)
    items: list[dict[str, str]] = []
    if assumed_year:
        for year in sorted(years, reverse=True):
            if str(year) != assumed_year:
                items.append({"label": f"{year} 年", "message": f"{name} {year}年合计"})
    if any(item["slot"] == "aggregation" for item in assumptions):
        year_bit = f"{assumed_year}年" if assumed_year else ""
        items.append(
            {
                "label": "看平均值",
                "message": f"{name} {year_bit}平均值".replace("  ", " "),
            }
        )
    if not query.group_by:
        year_bit = f"{assumed_year}年" if assumed_year else ""
        items.append(
            {
                "label": "看各对象明细",
                "message": f"{name} {year_bit}按对象列出明细".replace("  ", " "),
            }
        )
    return items[:3]


def _completed_payload(
    service: QueryService,
    actor: RequestActor,
    message: str,
    semantic: SemanticQuery,
    result: QueryResult,
    assumptions: list[dict[str, str]],
) -> dict[str, Any]:
    intent = TurnIntent.read(message, service.bundle)
    confidence = score_answer(service.bundle, intent, semantic, result, assumptions)
    years = _years_for(service, semantic.metrics[0].id, actor.tenant) if semantic.metrics else []
    return {
        "status": "READY",
        "answerReady": True,
        "textOrigin": "ENGINE",
        "text": semantic_summary(service.bundle, semantic, result, assumptions, confidence),
        "result": result.model_dump(mode="json", by_alias=True),
        "query": semantic.model_dump(mode="json", by_alias=True),
        "originalQuestion": message,
        "releaseDigest": service.bundle.digest,
        "assumptions": assumptions,
        "confidence": confidence,
        "followUps": _follow_ups(service.bundle, semantic, assumptions, years),
    }


_DEFINITION = re.compile(
    r"是什么|什么意思|含义|有哪些|能问什么|怎么用|如何使用|规则和适用范围|介绍一下|定义"
)


def try_direct_turn(
    service: QueryService, actor: RequestActor, message: str
) -> dict[str, Any] | None:
    """Answer or ask from ontology intent without a model when the question is structured."""
    text = message.strip()
    if not text or _DEFINITION.search(text):
        return None
    intent = TurnIntent.read(text, service.bundle)
    if not (
        intent.metric_ids
        or intent.candidates
        or intent.clarify_comparison
        or intent.operation
        or intent.year
        or intent.breakdown
    ):
        return None
    return prepare_turn(service, actor, text)


def prepare_turn(
    service: QueryService, actor: RequestActor, message: str, query: SemanticQuery | None = None
) -> dict[str, Any]:
    intent = TurnIntent.read(message, service.bundle)
    semantic = query or query_from_intent(intent, service.bundle)
    decided_metric = any(d.choice.kind == "METRIC" for d in semantic.decisions)
    if intent.candidates and not decided_metric:
        semantic = semantic.model_copy(update={"metrics": (), "comparison": None})
        options = []
        for metric_id in intent.candidates[:3]:
            metric = next((item for item in service.bundle.metrics if item.id == metric_id), None)
            if metric is None:
                continue
            options.append(
                ChoiceOption(
                    id="opt_metric_" + metric_id.replace(".", "_"),
                    label=metric.label or metric_id,
                    explanation=metric.description or metric_id,
                    choice=SemanticChoice(kind="METRIC", id=metric_id),
                )
            )
        if options:
            question = ChoiceQuestion(
                question_id="q-metric-intent-" + uuid.uuid4().hex,
                revision=1,
                slot="metric",
                prompt="你说的指标是哪种口径？",
                reason="本体中该业务词对应多个指标，口径会改变结果。",
                options=with_choice_exits(options),
            )
            return {
                "status": "NEEDS_INPUT",
                "waiting": True,
                "question": question.model_dump(mode="json", by_alias=True),
                "query": semantic.model_dump(mode="json", by_alias=True),
                "originalQuestion": message,
                "releaseDigest": service.bundle.digest,
            }
    if intent.clarify_comparison and not any(
        d.choice.kind == "COMPARISON" for d in semantic.decisions
    ):
        question = ChoiceQuestion(
            question_id="q-comparison-" + uuid.uuid4().hex,
            revision=1,
            slot="comparison",
            prompt="你希望比较哪一种比例？",
            reason="这些比例的分母和含义不同。",
            options=with_choice_exits(
                [
                    ChoiceOption(
                        id="opt_" + op,
                        label=label,
                        explanation=explanation,
                        choice=SemanticChoice(kind="COMPARISON", id=op),
                    )
                    for op, label, explanation in (
                        ("SHARE_OF_TOTAL", "占总体总额", "主体数值除以总体合计"),
                        ("RELATIVE_TO_MEAN", "相对均值增幅", "主体比总体平均值高多少"),
                        ("STRICT_PEER", "严格优于同行", "严格胜出的同行数量占同行总数"),
                    )
                ]
            ),
        )
        return {
            "status": "NEEDS_INPUT",
            "waiting": True,
            "question": question.model_dump(mode="json", by_alias=True),
            "query": semantic.model_dump(mode="json", by_alias=True),
            "originalQuestion": message,
            "releaseDigest": service.bundle.digest,
        }
    semantic = _apply_intent(semantic, intent, service.bundle)
    semantic, assumptions = _apply_defaults(semantic, intent, service.bundle, service, actor)
    try:
        prepared = prepare(service, semantic, actor)
    except AnalysisError as exc:
        if exc.code != "PROVIDER_UNAVAILABLE":
            raise
        return {
            "status": "SOURCE_ERROR",
            "errorCode": exc.code,
            "retryable": True,
            "releaseDigest": service.bundle.digest,
        }
    payload = prepared.model_dump(mode="json", by_alias=True)
    payload["query"] = semantic.model_dump(mode="json", by_alias=True)
    payload["originalQuestion"] = message
    payload["releaseDigest"] = service.bundle.digest
    payload["assumptions"] = assumptions
    if prepared.status == "READY" and prepared.plan is not None:
        try:
            result = execute(service, prepared.plan, actor)
        except AnalysisError as exc:
            return {
                "status": "SOURCE_ERROR" if exc.code == "PROVIDER_UNAVAILABLE" else "UNSUPPORTED",
                "errorCode": exc.code,
                "retryable": exc.code == "PROVIDER_UNAVAILABLE",
                "releaseDigest": service.bundle.digest,
            }
        completed = _completed_payload(service, actor, message, semantic, result, assumptions)
        payload.update(completed)
    if prepared.status == "NEEDS_INPUT":
        payload["waiting"] = True
    return payload


def submit_choice(
    store: ChatStore,
    service: QueryService,
    actor: RequestActor,
    conversation_id: str,
    submit: ChoiceSubmit,
) -> dict[str, Any]:
    row = store.load(actor, conversation_id)
    if row["release_digest"] != service.bundle.digest:
        raise ChoiceError("VERSION_INVALID")
    pending = row.get("pending")
    if not pending:
        raise ChoiceError("QUESTION_MISMATCH")
    question = ChoiceQuestion.model_validate(pending)
    state = row.get("query_state") or {}
    query = SemanticQuery.model_validate(state.get("query") or {"apiVersion": "semaloom/v0.1"})
    original = str(state.get("originalQuestion") or "")
    selected = [item for item in question.options if item.id in submit.option_ids]
    if any(item.choice.kind == "OTHER" for item in selected):
        if len(submit.option_ids) != 1:
            raise ChoiceError("OTHER_MUST_BE_ALONE")
        text = (submit.other_text or "").strip()
        if not text:
            raise ChoiceError("OTHER_TEXT_REQUIRED")
        combined = original + "\n" + text
        prepared = prepare_turn(service, actor, combined, query)
        return _persist_prepared(store, service, actor, row, original, prepared, query)
    if submit.other_text:
        raise ChoiceError("OTHER_TEXT_NOT_ALLOWED")
    try:
        merged = merge_decision(query, question, submit)
    except ChoiceError as exc:
        if exc.code == "ABORTED":
            store.save_pending(actor, row, None, None, original)
            return {"status": "ABORTED", "errorCode": "ABORTED"}
        raise
    prepared = prepare_turn(service, actor, original, merged)
    return _persist_prepared(store, service, actor, row, original, prepared, merged)


def _persist_prepared(
    store: ChatStore,
    service: QueryService,
    actor: RequestActor,
    row: dict[str, Any],
    original: str,
    prepared: dict[str, Any],
    fallback_query: SemanticQuery,
) -> dict[str, Any]:
    pending_out = prepared.get("question") if prepared.get("status") == "NEEDS_INPUT" else None
    query_state = {
        "query": prepared.get("query") or fallback_query.model_dump(mode="json", by_alias=True)
    }
    follow_question = str(prepared.get("originalQuestion") or original)
    if prepared.get("answerReady"):
        refreshed = {**row, "query_state": {**query_state, "originalQuestion": follow_question}}
        answer = attach_lineage(
            {
                "kind": "answer",
                "textOrigin": "ENGINE",
                "text": prepared.get("text") or "已按发布口径完成计算。",
                "evidence": [
                    {
                        "id": "e1",
                        "tool": "prepare_semantic_query",
                        "result": prepared.get("result") or {},
                    }
                ],
                "releaseDigest": service.bundle.digest,
                "confidence": prepared.get("confidence"),
                "followUps": prepared.get("followUps") or [],
                "assumptions": prepared.get("assumptions") or [],
            },
            service.bundle,
        )
        store.save(
            actor,
            refreshed,
            list(refreshed.get("history") or []),
            {"question": original, "answer": answer},
        )
        prepared["evidence"] = answer["evidence"]
        prepared["textOrigin"] = "ENGINE"
    elif prepared.get("status") == "NEEDS_INPUT":
        store.save_pending(actor, row, pending_out, query_state, follow_question)
    return prepared

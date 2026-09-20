"""Server-owned choice persist/merge. Clients submit option ids only."""

# ruff: noqa: RUF001 -- Chinese UI prompts use Chinese punctuation.

from __future__ import annotations

import re
import time
import unicodedata
import uuid
from collections.abc import Iterable
from typing import Any

from semaloom.app.chat.i18n import localize_question
from semaloom.app.chat.intent import TurnIntent, slots_for_metric
from semaloom.app.chat.presentation import project_browser_answer
from semaloom.app.chat.store import ChatStore
from semaloom.app.chat.summary import capability_message, semantic_summary
from semaloom.core.bundle import CompiledBundle
from semaloom.core.measure import default_aggregation
from semaloom.core.model import ValueType
from semaloom.core.provider import IdentityScalar
from semaloom.core.results import ObjectSearchRequest
from semaloom.core.semantic_query import (
    AggregationOp,
    ChoiceError,
    ChoiceOption,
    ChoiceQuestion,
    ChoiceSubmit,
    ComparisonExpr,
    ComparisonOp,
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
from semaloom.runtime.eval import EvaluationError, evaluate_claim_with_evidence
from semaloom.runtime.query import QueryService

_AGG: dict[str, AggregationOp] = {
    "mean": "AVG",
    "sum": "SUM",
    "min": "MIN",
    "max": "MAX",
    "count": "COUNT",
}
_CMP: dict[str, ComparisonOp] = {
    "shareOfTotal": "SHARE_OF_TOTAL",
    "percentAboveMean": "RELATIVE_TO_MEAN",
    "outperforms": "STRICT_PEER",
}


def _typed_atom(field: str, stored: str, value_type: ValueType) -> FilterAtom:
    parsed: str | int | bool
    if value_type == "BOOLEAN":
        parsed = stored.lower() == "true"
    elif value_type == "INTEGER":
        parsed = int(stored)
    else:
        parsed = stored
    return FilterAtom(
        field=field,
        op="EQ",
        value=TypedValue(value_type=value_type, value=parsed),
    )


def _one_link_name_field(
    bundle: CompiledBundle, object_type: str, prefer: str | None = None
) -> str | None:
    matches: list[str] = []
    for link in bundle.links:
        if link.source != object_type or link.cardinality != "ONE":
            continue
        target = next((item for item in bundle.object_types if item.id == link.target), None)
        if target is None or not any(prop.id == "name" for prop in target.properties):
            continue
        field = f"{target.id}.name"
        haystack = f"{target.id} {target.label or ''}".casefold()
        if prefer and prefer in haystack:
            return field
        matches.append(field)
    return matches[0] if len(matches) == 1 else None


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
    filters: FilterAtom | FilterGroup | None = None
    year_field = _year_property(bundle, intent.metric_ids)
    if intent.year is not None and year_field:
        filters = _year_filter(year_field, intent.year)
    if intent.multiple_years and intent.years and year_field:
        filters = FilterAtom(
            field=year_field, op="IN", value=TypedValue(value_type="INTEGER", value=intent.years)
        )
    aggregation = _AGG.get(intent.operation) if intent.operation else None
    if aggregation is None and intent.comparison and metrics:
        metric = next((item for item in bundle.metrics if item.id == metrics[0].id), None)
        aggregation = default_aggregation(metric.additivity or "FULL") if metric else None
    metrics = tuple(item.model_copy(update={"aggregation": aggregation}) for item in metrics)
    comparison = None
    if intent.period_over_period and len(metrics) == 1:
        comparison = ComparisonExpr(op="PERIOD_OVER_PERIOD", metric=metrics[0].id)
    elif intent.comparison and len(metrics) == 1:
        comparison = ComparisonExpr(
            op=_CMP[intent.comparison],
            metric=metrics[0].id,
            direction=intent.direction,
        )
    for hit in intent.dimension_filters:
        atom = _typed_atom(hit.field, hit.stored, hit.value_type)
        filters = atom if filters is None else _append_filter(filters, atom)
    group_by: tuple[GroupByItem, ...] = ()
    if (intent.trend or intent.multiple_years) and year_field and metrics:
        group_by = (GroupByItem(id=year_field, time_grain="YEAR"),)
    if intent.group_dimension and metrics:
        item = GroupByItem(id=intent.group_dimension)
        group_by = (*group_by, item) if item not in group_by else group_by
    elif (intent.breakdown or intent.group_label) and metrics:
        metric = next((item for item in bundle.metrics if item.id == metrics[0].id), None)
        if metric is not None:
            linked = (
                _one_link_name_field(bundle, metric.object_type, intent.group_prefer)
                if intent.group_label
                else None
            )
            if linked:
                group_by = (GroupByItem(id=linked),)
            elif metric.population is not None:
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
    if intent.period_over_period:
        if query.comparison is None:
            if metrics:
                updates["comparison"] = ComparisonExpr(
                    op="PERIOD_OVER_PERIOD", metric=metrics[0].id
                )
            else:
                raise AnalysisError("COMPARISON_REQUIRED_BY_USER")
        elif query.comparison.op != "PERIOD_OVER_PERIOD":
            raise AnalysisError("COMPARISON_REQUIRED_BY_USER")
    elif intent.comparison:
        required = {
            "shareOfTotal": "SHARE_OF_TOTAL",
            "percentAboveMean": "RELATIVE_TO_MEAN",
            "outperforms": "STRICT_PEER",
        }[intent.comparison]
        if query.comparison is None or query.comparison.op != required:
            raise AnalysisError("COMPARISON_REQUIRED_BY_USER")
        if intent.comparison == "outperforms" and query.comparison.direction != intent.direction:
            raise AnalysisError("COMPARISON_DIRECTION_DOES_NOT_MATCH_USER")
    filters = updates.get("filters", query.filters)
    for hit in intent.dimension_filters:
        if not field_constrained(filters, hit.field.split(".")[-1]):
            filters = _append_filter(filters, _typed_atom(hit.field, hit.stored, hit.value_type))
            updates["filters"] = filters
    if intent.group_dimension and not query.group_by:
        updates["group_by"] = (GroupByItem(id=intent.group_dimension),)
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
    metric = next((m for m in service.bundle.metrics if m.id == metric_id), None)
    if metric is None or not getattr(metric, "population", None):
        return []
    handler = getattr(service.provider, "analysis_years", None)
    if not callable(handler):
        return []
    try:
        years = handler(service.bundle, metric_id, tenant)
    except Exception:
        return []
    if not isinstance(years, Iterable) or isinstance(years, (str, bytes)):
        return []
    return [int(year) for year in years]


def _complete_explicit_scope(
    query: SemanticQuery,
    intent: TurnIntent,
    bundle: CompiledBundle,
    service: QueryService,
    actor: RequestActor,
) -> tuple[SemanticQuery, list[dict[str, str]]]:
    """Resolve explicit scope; leave missing business choices to engine prepare."""
    updates: dict[str, Any] = {}
    assumptions: list[dict[str, str]] = []
    if query.group_by and not (
        intent.breakdown
        or intent.group_label
        or intent.group_dimension
        or intent.trend
        or intent.multiple_years
    ):
        updates["group_by"] = ()
        assumptions.append({"slot": "grain", "id": "total", "reason": "USER_DID_NOT_ASK_BREAKDOWN"})
    elif (
        (intent.breakdown or intent.group_label or intent.group_dimension)
        and not query.group_by
        and query.metrics
    ):
        metric = next((item for item in bundle.metrics if item.id == query.metrics[0].id), None)
        group_id = intent.group_dimension
        if group_id is None and metric is not None and intent.group_label:
            group_id = _one_link_name_field(bundle, metric.object_type, intent.group_prefer)
        if group_id is None and metric is not None and metric.population is not None:
            group_id = metric.population.unit_property
        if group_id:
            updates["group_by"] = (GroupByItem(id=group_id),)
    year_field = _year_property(bundle, {item.id for item in query.metrics})
    if (
        year_field
        and query.metrics
        and (intent.trend or intent.multiple_years)
        and not field_constrained(query.filters, year_field)
    ):
        years = sorted(_years_for(service, query.metrics[0].id, actor.tenant))
        if intent.recent_year_count is not None:
            years = years[-intent.recent_year_count :]
        if years:
            updates["filters"] = _append_filter(
                query.filters,
                FilterAtom(
                    field=year_field,
                    op="IN",
                    value=TypedValue(value_type="INTEGER", value=tuple(years)),
                ),
            )
    return query.model_copy(update=updates) if updates else query, assumptions


def _follow_ups(bundle: CompiledBundle, query: SemanticQuery) -> list[dict[str, str]]:
    if not query.metrics:
        return []
    labels = {metric.id: metric.label or metric.id for metric in bundle.metrics}
    name = "、".join(labels.get(ref.id, ref.id) for ref in query.metrics)
    year_field = _year_property(bundle, {ref.id for ref in query.metrics})
    year = equality_value(query.filters, year_field) if year_field else None
    # Follow-ups are new questions: only suggest a scope we can preserve exactly.
    if query.filters is not None and year is None:
        return []
    if isinstance(query.filters, FilterGroup) and len(query.filters.args) > 1:
        return []
    year_text = f"{year}年" if year is not None else ""
    operations = {ref.aggregation for ref in query.metrics}
    operation = (
        {
            "SUM": "合计",
            "AVG": "平均值",
            "MIN": "最小值",
            "MAX": "最大值",
            "COUNT": "有效观测数量",
        }.get(next(iter(operations)) or "", "")
        if len(operations) == 1
        else ""
    )
    items: list[dict[str, str]] = []
    for slot in slots_for_metric(bundle, query.metrics[0].id)[:2]:
        if not query.group_by or query.group_by[0].id != slot.field:
            label = slot.prop.label or slot.prop.id
            items.append(
                {"label": f"按{label}看", "message": f"{year_text}{name}按{label}{operation}"}
            )
    if not query.group_by:
        items.append(
            {"label": "看各对象明细", "message": f"{year_text}{name}按对象列出明细{operation}"}
        )
    return items[:3]


def _completed_payload(
    service: QueryService,
    actor: RequestActor,
    message: str,
    semantic: SemanticQuery,
    result: QueryResult,
    assumptions: list[dict[str, str]],
    locale: str = "zh-CN",
) -> dict[str, Any]:
    return {
        "status": "READY",
        "answerReady": True,
        "textOrigin": "ENGINE",
        "text": semantic_summary(service.bundle, semantic, result, assumptions, locale),
        "result": result.model_dump(mode="json", by_alias=True),
        "query": semantic.model_dump(mode="json", by_alias=True),
        "originalQuestion": message,
        "releaseDigest": service.bundle.digest,
        "assumptions": assumptions,
        "followUps": _follow_ups(service.bundle, semantic),
    }


_DEFINITION = re.compile(
    r"是什么|什么意思|含义|有哪些|能问什么|怎么用|如何使用|规则和适用范围|介绍一下|定义"
)
_COMPLEX_QUERY = re.compile(
    r"谁|哪个|前[0-9一二两三四五六七八九十]+|最高|最低|最少|偏高|偏低|"
    r"为什么|如何|怎样|怎么样|风险|原因|影响|预测|趋势|如果|假如|"
    r"且|并且|以及|和.*一起|分布|排行|清单|明细|状况|"
    r"对比|延误|异常|差额|违规|超额"
)
_CLAIM_LANGUAGE = re.compile(r"是否|一致|等于|判断|成立|核验")


def _unique_named_option(message: str, question: ChoiceQuestion, kind: str) -> ChoiceOption | None:
    text = unicodedata.normalize("NFKC", message).casefold()
    hits: list[ChoiceOption] = []
    for option in question.options:
        if option.choice.kind != kind:
            continue
        label = unicodedata.normalize("NFKC", option.label).casefold()
        values = [part.split(":", 1)[-1].strip() for part in label.split(";")]
        if any(value and len(value) >= 2 and value in text for value in values):
            hits.append(option)
    return hits[0] if len(hits) == 1 else None


def try_direct_turn(
    service: QueryService, actor: RequestActor, message: str, locale: str = "zh-CN"
) -> dict[str, Any] | None:
    """Answer or ask from ontology intent without a model when the question is structured."""
    text = message.strip()
    if not text or _DEFINITION.search(text):
        return None
    intent = TurnIntent.read(text, service.bundle)
    if intent.claim_ids or intent.claim_candidates:
        return prepare_claim_turn(service, actor, text)
    if re.search(
        r"排名|排行|排序|前[0-9一二两三四五六七八九十]+|从高到低|从低到高|最高|最低",
        text,
    ):
        # Ranking needs a typed orderBy/limit from the model, even when a known
        # dictionary dimension makes the rest of the question look structured.
        return None
    structured = bool(
        intent.period_over_period
        or intent.month_over_month
        or intent.dimension_filters
        or intent.need_dimension
        or intent.group_dimension
        or intent.trend
        or intent.multiple_years
    )
    if structured and (intent.metric_ids or intent.candidates):
        return prepare_turn(service, actor, text, locale=locale)
    if _CLAIM_LANGUAGE.search(text) and not (intent.metric_ids or intent.candidates):
        return prepare_claim_turn(service, actor, text)
    if _COMPLEX_QUERY.search(text):
        return None
    if not (intent.metric_ids or intent.candidates):
        return None
    return prepare_turn(service, actor, text, locale=locale)


def prepare_turn(
    service: QueryService,
    actor: RequestActor,
    message: str,
    query: SemanticQuery | None = None,
    locale: str = "zh-CN",
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
                    # Internal semantic ids remain in the submitted choice,
                    # while the card shows only ontology-authored business copy.
                    explanation=metric.description or metric.label or metric_id,
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
    if intent.month_over_month:
        return {
            "status": "UNSUPPORTED",
            "kind": "unsupported",
            "answerReady": True,
            "textOrigin": "ENGINE",
            "text": capability_message("TIME_GRAIN_UNSUPPORTED", locale),
            "errorCode": "TIME_GRAIN_UNSUPPORTED",
            "query": semantic.model_dump(mode="json", by_alias=True),
            "originalQuestion": message,
            "releaseDigest": service.bundle.digest,
        }
    metric_ids = {item.id for item in semantic.metrics} or intent.metric_ids
    if intent.period_over_period and metric_ids:
        kinds = [
            next(
                (row.additivity or "FULL" for row in service.bundle.metrics if row.id == item),
                "FULL",
            )
            for item in metric_ids
        ]
        if any(kind == "NONE" for kind in kinds):
            return {
                "status": "UNSUPPORTED",
                "kind": "unsupported",
                "answerReady": True,
                "textOrigin": "ENGINE",
                "text": capability_message("ADDITIVITY_VIOLATION", locale),
                "errorCode": "ADDITIVITY_VIOLATION",
                "query": semantic.model_dump(mode="json", by_alias=True),
                "originalQuestion": message,
                "releaseDigest": service.bundle.digest,
            }
    if (
        intent.need_dimension
        and semantic.metrics
        and not any(
            decision.choice.kind == "DIMENSION_VALUE"
            and (decision.choice.field == intent.need_dimension)
            for decision in semantic.decisions
        )
        and not field_constrained(semantic.filters, intent.need_dimension.split(".")[-1])
    ):
        slot = next(
            (
                item
                for item in slots_for_metric(service.bundle, semantic.metrics[0].id)
                if item.field == intent.need_dimension
            ),
            None,
        )
        if slot is not None:
            options = [
                ChoiceOption(
                    id="opt_dim_" + item.id.replace(".", "_"),
                    label=item.label or item.id,
                    explanation=f"按 {slot.prop.label or slot.field} 精确筛选",
                    choice=SemanticChoice(
                        kind="DIMENSION_VALUE",
                        id=item.id,
                        field=slot.field,
                        predicate=_typed_atom(slot.field, item.id, slot.prop.value_type),
                    ),
                )
                for item in slot.prop.values[:6]
            ]
            if options:
                question = ChoiceQuestion(
                    question_id="q-dimension-" + uuid.uuid4().hex,
                    revision=1,
                    slot="dimension",
                    prompt=f"请选择{(slot.prop.label or slot.prop.id)}",
                    reason="这个问题依赖本体配置的取值字典，不能猜测未说出的选项。",
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
    semantic = _apply_intent(semantic, intent, service.bundle)
    semantic, assumptions = _complete_explicit_scope(
        semantic, intent, service.bundle, service, actor
    )
    try:
        prepared = prepare(service, semantic, actor)
    except AnalysisError as exc:
        if exc.code == "INVALID_PROPERTIES":
            return {
                "status": "UNSUPPORTED",
                "kind": "unsupported",
                "answerReady": True,
                "textOrigin": "ENGINE",
                "text": capability_message(exc.code, locale),
                "errorCode": exc.code,
                "retryable": False,
                "query": semantic.model_dump(mode="json", by_alias=True),
                "releaseDigest": service.bundle.digest,
            }
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
    if (
        prepared.status == "NEEDS_INPUT"
        and prepared.question is not None
        and prepared.question.slot == "subject"
        and query is None
    ):
        picked = _unique_named_option(message, prepared.question, "SUBJECT")
        if picked is not None:
            semantic = merge_decision(
                semantic,
                prepared.question,
                ChoiceSubmit(
                    question_id=prepared.question.question_id,
                    revision=prepared.question.revision,
                    option_ids=(picked.id,),
                ),
            )
            return prepare_turn(service, actor, message, semantic, locale)
    if prepared.status == "UNSUPPORTED":
        text = capability_message(prepared.capability or prepared.error_message, locale)
        payload.update(
            {
                "status": "UNSUPPORTED",
                "kind": "unsupported",
                "answerReady": True,
                "textOrigin": "ENGINE",
                "text": text,
                "errorCode": prepared.capability or prepared.error_code or "OPERATOR_NOT_SUPPORTED",
            }
        )
        return payload
    if prepared.status == "READY" and prepared.plan is not None:
        try:
            result = execute(service, prepared.plan, actor)
        except AnalysisError as exc:
            if exc.code == "PROVIDER_UNAVAILABLE":
                return {
                    "status": "SOURCE_ERROR",
                    "errorCode": exc.code,
                    "retryable": True,
                    "releaseDigest": service.bundle.digest,
                }
            text = capability_message(exc.code, locale)
            return {
                "status": "UNSUPPORTED",
                "kind": "unsupported",
                "answerReady": True,
                "textOrigin": "ENGINE",
                "text": text,
                "errorCode": exc.code,
                "retryable": False,
                "releaseDigest": service.bundle.digest,
            }
        completed = _completed_payload(
            service, actor, message, semantic, result, assumptions, locale
        )
        payload.update(completed)
    if prepared.status == "NEEDS_INPUT":
        payload["waiting"] = True
    return payload


def prepare_claim_turn(
    service: QueryService,
    actor: RequestActor,
    message: str,
    *,
    claim_id: str | None = None,
    identity: dict[str, str] | None = None,
) -> dict[str, Any]:
    intent = TurnIntent.read(message, service.bundle)
    if claim_id is None and len(intent.claim_ids) == 1:
        claim_id = next(iter(intent.claim_ids))
    if claim_id is None and len(intent.claim_candidates) == 1:
        claim_id = intent.claim_candidates[0]
    if claim_id is None:
        listed = [*sorted(intent.claim_ids), *intent.claim_candidates]
        if not listed:
            listed = [row.claim for row in service.bundle.rules if row.claim]
        options = []
        seen: set[str] = set()
        for item in listed:
            if item in seen:
                continue
            seen.add(item)
            rule = next((row for row in service.bundle.rules if row.claim == item), None)
            if rule is None:
                continue
            options.append(
                ChoiceOption(
                    id="opt_claim_" + item.replace(".", "_"),
                    label=rule.label or item,
                    explanation=rule.description or item,
                    choice=SemanticChoice(kind="CLAIM", id=item),
                )
            )
            if len(options) >= 6:
                break
        if len(options) >= 1:
            question = ChoiceQuestion(
                question_id="q-claim-" + uuid.uuid4().hex,
                revision=1,
                slot="claim",
                prompt="要核验哪条已发布规则？",
                reason="问题对应多条判断，口径不同，不能猜测。",
                options=with_choice_exits(options),
            )
            return {
                "status": "NEEDS_INPUT",
                "waiting": True,
                "mode": "claim",
                "question": question.model_dump(mode="json", by_alias=True),
                "query": {"apiVersion": "semaloom/v0.1"},
                "query_state": {"mode": "claim", "originalQuestion": message},
                "originalQuestion": message,
                "releaseDigest": service.bundle.digest,
            }
        return {
            "status": "UNSUPPORTED",
            "kind": "unsupported",
            "answerReady": True,
            "textOrigin": "ENGINE",
            "text": "当前问题没有匹配到已发布的判断规则。",
            "errorCode": "UNKNOWN_CLAIM",
            "originalQuestion": message,
            "releaseDigest": service.bundle.digest,
        }
    rule = next((row for row in service.bundle.rules if row.claim == claim_id), None)
    if rule is None or not rule.inputs or rule.inputs[0].metric is None:
        return {
            "status": "UNSUPPORTED",
            "kind": "unsupported",
            "answerReady": True,
            "textOrigin": "ENGINE",
            "text": "这条规则缺少可定位的指标输入。",
            "errorCode": "UNKNOWN_CLAIM",
            "originalQuestion": message,
            "releaseDigest": service.bundle.digest,
        }
    metric = next(item for item in service.bundle.metrics if item.id == rule.inputs[0].metric)
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    year = intent.year
    filters: dict[str, str | int | bool] = dict(identity or {})
    if year is not None and obj.population is not None:
        filters[obj.population.year_property] = year
    display = [
        prop.id
        for prop in obj.properties
        if prop.value_type == "STRING" and prop.id not in obj.identity_keys
    ][:3]
    period_fields: tuple[str, ...] = ()
    if obj.period is not None:
        period_fields = (obj.period.from_property, obj.period.to_property)
    requested = tuple(
        dict.fromkeys(
            [
                *display,
                *period_fields,
                *rule.applicability,
                *([obj.population.year_property] if obj.population else []),
            ]
        )
    )
    found = service.find_objects(
        ObjectSearchRequest(
            object_type=obj.id,
            filters=filters,
            properties=requested,
            limit=50,
        ),
        actor,
    )
    rows = list(found.get("objects") or [])
    named = []
    folded = unicodedata.normalize("NFKC", message).casefold()
    for row in rows:
        labels = [str(value) for value in (row.get("identity") or {}).values()]
        props = row.get("properties") or {}
        labels.extend(str(props[name]) for name in display if props.get(name) not in {None, ""})
        if any(
            len(label) >= 2 and unicodedata.normalize("NFKC", label).casefold() in folded
            for label in labels
        ):
            named.append(row)
    if len(named) == 1:
        rows = named
    elif named:
        rows = named
    if len(rows) != 1 or (found.get("hasMore") and identity is None):
        options = []
        subjects = {}
        for index, row in enumerate(rows[:4]):
            ident = row.get("identity") or {}
            key = obj.identity_keys[0]
            value = str(ident.get(key, ""))
            props = row.get("properties") or {}
            parts = [str(props[name]) for name in display if props.get(name) not in {None, ""}]
            if "name" in props and props.get("name") not in {None, ""}:
                parts = [
                    str(props["name"]),
                    *[item for item in parts if item != str(props["name"])],
                ]
            label = " · ".join(dict.fromkeys(parts)) or value
            if obj.population and props.get(obj.population.year_property) is not None:
                label += f" · {props[obj.population.year_property]} 年"
            subjects[f"opt_claim_subject_{index}"] = ident
            options.append(
                ChoiceOption(
                    id=f"opt_claim_subject_{index}",
                    label=label,
                    explanation="当前筛选范围内的候选对象",
                    choice=SemanticChoice(kind="SUBJECT", id=value, field=key),
                )
            )
        if not options:
            return {
                "status": "UNSUPPORTED",
                "kind": "unsupported",
                "answerReady": True,
                "textOrigin": "ENGINE",
                "text": "当前范围没有可核验的对象，请核对名称或年份。",
                "errorCode": "COMPARISON_SUBJECT_NOT_FOUND",
                "originalQuestion": message,
                "releaseDigest": service.bundle.digest,
            }
        question = ChoiceQuestion(
            question_id="q-claim-subject-" + uuid.uuid4().hex,
            revision=1,
            slot="claimSubject",
            prompt="要核验哪个对象？",
            reason="判断必须钉到唯一对象；以下是当前范围内的候选。",
            options=with_choice_exits(options),
        )
        return {
            "status": "NEEDS_INPUT",
            "waiting": True,
            "mode": "claim",
            "claimId": claim_id,
            "question": question.model_dump(mode="json", by_alias=True),
            "query": {"apiVersion": "semaloom/v0.1"},
            "query_state": {
                "mode": "claim",
                "claimId": claim_id,
                "originalQuestion": message,
                "subjects": subjects,
            },
            "originalQuestion": message,
            "releaseDigest": service.bundle.digest,
        }
    row = rows[0]
    bindings: dict[str, IdentityScalar] = {
        str(key): str(value) for key, value in (row.get("identity") or {}).items()
    }
    if year is not None and obj.population is not None:
        year_prop = obj.population.year_property
        metric_grain = set(metric.grain)
        if year_prop in metric_grain or year_prop in obj.identity_keys:
            bindings[year_prop] = year
    props = row.get("properties") or {}
    period_from = str(props.get(period_fields[0])) if period_fields else ""
    period_to = str(props.get(period_fields[1])) if len(period_fields) > 1 else ""
    if not period_from or period_from == "None":
        if year is None:
            question = ChoiceQuestion(
                question_id="q-claim-year-" + uuid.uuid4().hex,
                revision=1,
                slot="claimYear",
                prompt="要按哪个业务年度核验？",
                reason="规则可能随期间变化，请补充业务年度。",
                options=with_choice_exits([]),
            )
            return {
                "status": "NEEDS_INPUT",
                "waiting": True,
                "question": question.model_dump(mode="json", by_alias=True),
                "query_state": {"mode": "claim", "claimId": claim_id, "identity": bindings},
                "originalQuestion": message,
                "releaseDigest": service.bundle.digest,
            }
        period_from = f"{year}-01-01"
        period_to = f"{year + 1}-01-01"
    dimensions = {
        key: str(props[key]) for key in rule.applicability if props.get(key) not in {None, ""}
    }
    try:
        claim, observations, diagnostics, digest, activities = evaluate_claim_with_evidence(
            service.bundle,
            service,
            actor,
            claim_id=claim_id,
            bindings=bindings,
            period_from=period_from,
            period_to=period_to,
            dimensions=dimensions,
        )
    except EvaluationError as exc:
        return {
            "status": "UNSUPPORTED",
            "kind": "unsupported",
            "answerReady": True,
            "textOrigin": "ENGINE",
            "text": f"规则未能完成核验（{exc.code}）。",
            "errorCode": exc.code,
            "originalQuestion": message,
            "releaseDigest": service.bundle.digest,
        }
    truth = claim.truth
    if truth == "TRUE":
        status_desc = "规则成立"
    elif truth == "FALSE":
        status_desc = "规则不成立"
    else:
        status_desc = "现有数据不足以判断"
    label = rule.label or claim_id
    text = (
        f"**{label}：{status_desc}。**\n\n"
        f"核验对象：{'、'.join(str(value) for value in bindings.values())}。"
        f"业务期间：{period_from} 至 {period_to}（不含止日）。"
        "本次仅核验该规则，不代表来源真实性或其他业务判断。"
    )
    return {
        "status": "READY",
        "answerReady": True,
        "textOrigin": "ENGINE",
        "text": text,
        "tool": "evaluate_claim",
        "result": {
            "claim": claim.model_dump(mode="json", by_alias=True),
            "observations": [item.model_dump(mode="json", by_alias=True) for item in observations],
            "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            "sourceActivities": [
                item.model_dump(mode="json", by_alias=True) for item in activities
            ],
            "releaseDigest": digest,
        },
        "query": {"apiVersion": "semaloom/v0.1"},
        "query_state": {"mode": "claim", "claimId": claim_id, "originalQuestion": message},
        "originalQuestion": message,
        "releaseDigest": service.bundle.digest,
        "followUps": [],
    }


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
    if submit.question_id != question.question_id:
        raise ChoiceError("QUESTION_MISMATCH")
    if submit.revision != question.revision:
        raise ChoiceError("VERSION_INVALID")
    if not question.multi_select and len(submit.option_ids) != 1:
        raise ChoiceError("SINGLE_SELECT_REQUIRED")
    if any(
        option_id not in {item.id for item in question.options} for option_id in submit.option_ids
    ):
        raise ChoiceError("UNKNOWN_OPTION")
    state = row.get("query_state") or {}
    locale = str(state.get("locale") or "zh-CN")
    query = SemanticQuery.model_validate(state.get("query") or {"apiVersion": "semaloom/v0.1"})
    original = str(state.get("originalQuestion") or "")
    selected = [item for item in question.options if item.id in submit.option_ids]
    claim_flow = question.slot in {"claim", "claimSubject"} or state.get("mode") == "claim"
    if any(item.choice.kind == "OTHER" for item in selected):
        if len(submit.option_ids) != 1:
            raise ChoiceError("OTHER_MUST_BE_ALONE")
        text = (submit.other_text or "").strip()
        if not text:
            raise ChoiceError("OTHER_TEXT_REQUIRED")
        combined = original + "\n" + text
        if state.get("mode") in {"clarification", "object_scope"}:
            store.save_pending(actor, row, None, None, original)
            return {"status": "CONTINUE", "message": combined}
        prepared = (
            prepare_claim_turn(
                service,
                actor,
                combined,
                claim_id=state.get("claimId"),
                identity=state.get("identity"),
            )
            if claim_flow
            else prepare_turn(service, actor, combined, query, locale)
        )
        return _persist_prepared(store, service, actor, row, original, prepared, query)
    if submit.other_text:
        raise ChoiceError("OTHER_TEXT_NOT_ALLOWED")
    if any(item.choice.kind == "ABORT" for item in selected):
        store.save_pending(actor, row, None, None, original)
        return {"status": "ABORTED", "errorCode": "ABORTED"}
    if claim_flow:
        if question.multi_select is False and len(submit.option_ids) != 1:
            raise ChoiceError("SINGLE_SELECT_REQUIRED")
        chosen = next((item for item in question.options if item.id == submit.option_ids[0]), None)
        if chosen is None:
            raise ChoiceError("UNKNOWN_OPTION")
        if question.slot == "claim":
            prepared = prepare_claim_turn(service, actor, original, claim_id=chosen.choice.id)
        else:
            if chosen.choice.field is None:
                raise ChoiceError("SUBJECT_FIELD_REQUIRED")
            prepared = prepare_claim_turn(
                service,
                actor,
                original,
                claim_id=str(state.get("claimId") or ""),
                identity=state.get("subjects", {}).get(chosen.id)
                or {chosen.choice.field: chosen.choice.id},
            )
        return _persist_prepared(store, service, actor, row, original, prepared, query)
    try:
        merged = merge_decision(query, question, submit)
    except ChoiceError as exc:
        if exc.code == "ABORTED":
            store.save_pending(actor, row, None, None, original)
            return {"status": "ABORTED", "errorCode": "ABORTED"}
        raise
    prepared = prepare_turn(service, actor, original, merged, locale)
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
    locale = str((row.get("query_state") or {}).get("locale") or "zh-CN")
    prepared["question"] = localize_question(prepared.get("question"), locale)
    pending_out = prepared.get("question") if prepared.get("status") == "NEEDS_INPUT" else None
    query_state = {
        "query": prepared.get("query") or fallback_query.model_dump(mode="json", by_alias=True),
        "view": (row.get("query_state") or {}).get("view", "auto"),
        "locale": (row.get("query_state") or {}).get("locale", "zh-CN"),
        **(prepared.get("query_state") or {}),
    }
    if prepared.get("mode"):
        query_state["mode"] = prepared["mode"]
    if prepared.get("claimId"):
        query_state["claimId"] = prepared["claimId"]
    follow_question = str(prepared.get("originalQuestion") or original)
    if prepared.get("answerReady"):
        refreshed = {**row, "query_state": {**query_state, "originalQuestion": follow_question}}
        unsupported = prepared.get("status") == "UNSUPPORTED"
        kind = "unsupported" if unsupported else "answer"
        evidence_result = prepared.get("result") or (
            {
                "status": prepared.get("status"),
                "errorCode": prepared.get("errorCode"),
                "capability": prepared.get("capability"),
            }
            if unsupported
            else {}
        )
        locale = str(query_state["locale"])
        answer = project_browser_answer(
            {
                "kind": kind,
                "textOrigin": "ENGINE",
                "text": prepared.get("text")
                or (
                    "Calculated from the published semantic definition."
                    if locale.startswith("en")
                    else "已按发布口径完成计算。"
                ),
                "evidence": [
                    {
                        "id": "e1",
                        "tool": prepared.get("tool") or "prepare_semantic_query",
                        "result": evidence_result,
                    }
                ],
                "releaseDigest": service.bundle.digest,
                "followUps": prepared.get("followUps") or [],
                "assumptions": prepared.get("assumptions") or [],
                "query": prepared.get("query"),
                "originalQuestion": follow_question,
                "views": [{"evidenceId": "e1", "view": query_state["view"]}],
            },
            service.bundle,
            locale,
        )
        new_turn = {"question": original, "answer": answer}
        user_msg = {
            "role": "user",
            "content": original,
            "timestamp": int(time.time() * 1000),
        }
        assistant_msg = {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": answer.get("text")
                    or (
                        "Calculated from the published semantic definition."
                        if locale.startswith("en")
                        else "已按发布口径完成计算。"
                    ),
                }
            ],
            "timestamp": int(time.time() * 1000),
        }
        history = [*refreshed.get("history", []), user_msg, assistant_msg]
        store.save(
            actor,
            refreshed,
            history,
            new_turn,
        )
        prepared["evidence"] = answer["evidence"]
        prepared["presentation"] = answer.get("presentation")
        prepared["textOrigin"] = "ENGINE"
        prepared["kind"] = kind
    elif prepared.get("status") == "NEEDS_INPUT":
        store.save_pending(actor, row, pending_out, query_state, follow_question)
    return prepared

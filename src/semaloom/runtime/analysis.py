"""Same-source PostgreSQL SemanticQuery prepare/execute. No caller SQL."""

from __future__ import annotations

import uuid
from typing import Any, cast

from semaloom.core.measure import aggregations_for, scope_dimensions_held
from semaloom.core.model import EmbeddedProperty, MetricDef
from semaloom.core.semantic_query import (
    UNSUPPORTED_OPERATORS,
    AggregationOp,
    ChoiceOption,
    ChoiceQuestion,
    FilterAtom,
    PlanRef,
    PrepareResult,
    QueryResult,
    SemanticChoice,
    SemanticQuery,
    TypedValue,
    conflicting_equalities,
    field_constrained,
    formula_needs_subject,
    with_choice_exits,
)
from semaloom.core.semantic_query import (
    AnalysisError as AnalysisError,
)
from semaloom.runtime.auth import RequestActor, authorize_query
from semaloom.runtime.query import QueryService
from semaloom.runtime.vocabulary import display_label

_AGG_LABELS: dict[AggregationOp, str] = {
    "SUM": "合计",
    "AVG": "平均值",
    "MIN": "最小值",
    "MAX": "最大值",
    "COUNT": "有效观测数量",
}


def _aggregation_choices(
    metric: MetricDef, query: SemanticQuery
) -> list[tuple[AggregationOp, str]]:
    additivity = metric.additivity or "FULL"
    scope = metric.population.scope_properties if metric.population else ()
    allowed = aggregations_for(additivity)
    if additivity == "SEMI" and not scope_dimensions_held(query, scope):
        allowed = tuple(op for op in allowed if op != "SUM")
    return [(op, _AGG_LABELS[op]) for op in allowed]


def prepare(service: QueryService, query: SemanticQuery, actor: RequestActor) -> PrepareResult:
    if not authorize_query(actor, "query").allowed:
        raise PermissionError("FORBIDDEN")
    try:
        return _prepare(service, query, actor)
    except AnalysisError as exc:
        if exc.code in UNSUPPORTED_OPERATORS or exc.code in {
            "OPERATOR_NOT_SUPPORTED",
            "TIME_GRAIN_UNSUPPORTED",
            "MULTI_METRIC_ORDER_COMPARISON_UNSUPPORTED",
            "LINK_ANALYSIS_UNSUPPORTED",
            "CROSS_SOURCE_SQL",
            "BUDGET_EXCEEDED",
            "ADDITIVITY_VIOLATION",
            "POPULATION_NOT_DECLARED",
        }:
            return PrepareResult(
                status="UNSUPPORTED",
                error_code="OPERATOR_NOT_SUPPORTED",
                error_message=exc.code,
                capability=exc.code,
            )
        if exc.code == "PROVIDER_UNAVAILABLE":
            return PrepareResult(status="SOURCE_ERROR", error_code=exc.code, retryable=True)
        raise
    except ConnectionError:
        return PrepareResult(
            status="SOURCE_ERROR",
            error_code="PROVIDER_UNAVAILABLE",
            error_message="PROVIDER_UNAVAILABLE",
            retryable=True,
        )


def _prepare(service: QueryService, query: SemanticQuery, actor: RequestActor) -> PrepareResult:
    conflicts = conflicting_equalities(query.filters)
    if conflicts:
        return PrepareResult(
            status="NEEDS_INPUT",
            question=ChoiceQuestion(
                question_id="q-conflict-" + uuid.uuid4().hex,
                revision=1,
                slot="filter",
                prompt="筛选条件存在矛盾，请选择实际需要的条件。",
                reason="同一字段被同时要求等于不同值，不能当作没有业务数据。",
                options=with_choice_exits(
                    [
                        ChoiceOption(
                            id="opt_filter_" + str(index),
                            label=f"{atom.field} = {atom.value.value}",
                            explanation="替换该字段相互矛盾的条件",
                            choice=SemanticChoice(kind="FILTER", id=str(index), predicate=atom),
                        )
                        for index, atom in enumerate(conflicts[:4])
                    ]
                ),
            ),
        )
    if not query.metrics:
        options = [
            ChoiceOption(
                id="opt_metric_" + metric.id.replace(".", "_"),
                label=metric.label or metric.id,
                # Keep the stable id in the typed choice payload. Human cards
                # use only ontology-authored business copy.
                explanation=metric.description or metric.label or " ",
                choice=SemanticChoice(kind="METRIC", id=metric.id),
            )
            for metric in service.bundle.metrics
            if metric.population is not None
        ][:3]
        return PrepareResult(
            status="NEEDS_INPUT",
            question=ChoiceQuestion(
                question_id="q-metric-" + service.bundle.digest[:8],
                revision=1,
                slot="metric",
                prompt="请选择要看的指标。",
                reason="这项还对应多个指标，选定后继续。",
                options=with_choice_exits(options),
            ),
        )
    metric = _metric(service, query.metrics[0].id)
    missing_scope = _missing_scope_property(metric, query)
    if missing_scope is not None:
        prop = _property(service, metric, missing_scope)
        values = _backend(service, "analysis_dimension_values")(
            service.bundle, metric.id, missing_scope, actor.tenant
        )
        options = [
            ChoiceOption(
                id=f"opt_scope_{index}",
                label=_value_label(prop, value),
                explanation=f"已发布来源中出现的{prop.label or prop.id}",
                choice=SemanticChoice(
                    kind="DIMENSION_VALUE",
                    id=str(value),
                    field=missing_scope,
                    predicate=FilterAtom(
                        field=missing_scope,
                        op="EQ",
                        value=TypedValue(value_type=prop.value_type, value=value),
                    ),
                ),
            )
            for index, value in enumerate(values[:5])
        ]
        return PrepareResult(
            status="NEEDS_INPUT",
            question=ChoiceQuestion(
                question_id="q-scope-" + metric.id.replace(".", "_") + "-" + missing_scope,
                revision=1,
                slot="scope:" + missing_scope,
                prompt=(
                    f"要看{metric.label}，请选择{prop.label or prop.id}。"
                    if metric.label
                    else f"请选择{prop.label or prop.id}。"
                ),
                reason="选定后继续计算。",
                options=with_choice_exits(options),
            ),
        )
    for ref in query.metrics[1:]:
        extra = _metric(service, ref.id)
        if _missing_scope_property(extra, query) is not None:
            raise AnalysisError("INCOMPLETE_METRIC_PERIOD")
    if any(ref.aggregation is None for ref in query.metrics):
        choices = _aggregation_choices(metric, query)
        if not choices:
            raise AnalysisError("ADDITIVITY_VIOLATION")
        return PrepareResult(
            status="NEEDS_INPUT",
            question=ChoiceQuestion(
                question_id="q-aggregation-" + uuid.uuid4().hex,
                revision=1,
                slot="aggregation",
                prompt="希望如何统计这个指标？",
                reason="合计和平均值等计算含义不同，需要明确。",
                options=with_choice_exits(
                    [
                        ChoiceOption(
                            id="opt_agg_" + op,
                            label=label,
                            explanation=label + "（按当前筛选范围）",
                            choice=SemanticChoice(kind="AGGREGATION", id=op),
                        )
                        for op, label in choices
                    ]
                ),
            ),
        )
    if query.formula and formula_needs_subject(query.formula):
        subjects = _backend(service, "analysis_subjects")(service.bundle, query, actor.tenant)
        if query.formula.subject is None or len(subjects) > 1:
            subject_options = tuple(
                ChoiceOption(
                    id="opt_subject_" + str(index),
                    label=label,
                    explanation="当前筛选范围内的对象",
                    choice=SemanticChoice(kind="SUBJECT", id=value, field=field),
                )
                for index, (field, value, label) in enumerate(subjects[:4])
            )
            if not subject_options:
                return PrepareResult(
                    status="UNSUPPORTED",
                    error_code="COMPARISON_SUBJECT_NOT_FOUND",
                    error_message="当前范围没有可匹配的对象，请核对名称或补充资料。",
                )
            return PrepareResult(
                status="NEEDS_INPUT",
                question=ChoiceQuestion(
                    question_id="q-subject-" + uuid.uuid4().hex,
                    revision=1,
                    slot="subject",
                    prompt="你要比较哪个对象？",
                    reason="主体必须明确且唯一；以下是当前范围内的候选。",
                    options=with_choice_exits(subject_options),
                ),
            )
    digest = _backend(service, "prepare_analysis")(service.bundle, query, actor.tenant)
    return PrepareResult(
        status="READY",
        plan=PlanRef(
            plan_id=uuid.uuid4().hex,
            release_digest=service.bundle.digest,
            query=query,
            compiled_digest=digest,
        ),
    )


def _missing_scope_property(metric: MetricDef, query: SemanticQuery) -> str | None:
    if metric.population is None:
        return None
    return next(
        (
            field
            for field in metric.population.scope_properties
            if not field_constrained(query.filters, field)
            and not any(item.id.rsplit(".", 1)[-1] == field for item in query.group_by)
        ),
        None,
    )


def _property(service: QueryService, metric: MetricDef, field: str) -> EmbeddedProperty:
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    return next(prop for prop in obj.properties if prop.id == field)


def _value_label(prop: EmbeddedProperty, value: str | int | bool) -> str:
    return display_label(prop, value)


def _metric(service: QueryService, metric_id: str) -> MetricDef:
    metric = next((item for item in service.bundle.metrics if item.id == metric_id), None)
    if metric is None:
        raise AnalysisError("UNKNOWN_METRIC")
    return metric


def _backend(service: QueryService, method: str) -> Any:
    handler = getattr(service.provider, method, None)
    if not callable(handler):
        raise AnalysisError("OPERATOR_NOT_SUPPORTED")
    return handler


def execute(service: QueryService, plan: PlanRef, actor: RequestActor) -> QueryResult:
    if not authorize_query(actor, "query").allowed:
        raise PermissionError("FORBIDDEN")
    if plan.release_digest != service.bundle.digest:
        raise AnalysisError("VERSION_INVALID")
    return cast(
        QueryResult, _backend(service, "execute_analysis")(service.bundle, plan, actor.tenant)
    )

"""Same-source PostgreSQL SemanticQuery prepare/execute. No caller SQL."""

from __future__ import annotations

import uuid
from typing import Any, cast

from semaloom.core.measure import aggregations_for, time_dimension_held
from semaloom.core.model import MetricDef
from semaloom.core.semantic_query import (
    UNSUPPORTED_OPERATORS,
    AggregationOp,
    ChoiceOption,
    ChoiceQuestion,
    PlanRef,
    PrepareResult,
    QueryResult,
    SemanticChoice,
    SemanticQuery,
    conflicting_equalities,
    field_constrained,
    with_choice_exits,
)
from semaloom.core.semantic_query import (
    AnalysisError as AnalysisError,
)
from semaloom.runtime.auth import RequestActor, authorize_query
from semaloom.runtime.query import QueryService

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
    year = metric.population.year_property if metric.population else None
    allowed = aggregations_for(additivity)
    if additivity == "SEMI" and not time_dimension_held(query, year):
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
                explanation=metric.description or metric.id,
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
                prompt="你说的指标是哪种口径？",
                reason="缺少影响结果的指标选择。",
                options=with_choice_exits(options),
            ),
        )
    metric = _metric(service, query.metrics[0].id)
    if metric.population is not None and not field_constrained(
        query.filters, metric.population.year_property
    ):
        years = _backend(service, "analysis_years")(service.bundle, metric.id, actor.tenant)
        options = [
            ChoiceOption(
                id=f"opt_year_{year}",
                label=f"{year} 年",
                explanation="已发布来源中出现的业务年度",
                choice=SemanticChoice(
                    kind="YEAR", id=str(year), field=metric.population.year_property
                ),
            )
            for year in years[:3]
        ]
        return PrepareResult(
            status="NEEDS_INPUT",
            question=ChoiceQuestion(
                question_id="q-year-" + metric.id.replace(".", "_"),
                revision=1,
                slot="year",
                prompt="要计算哪一年？",
                reason="该指标按年度统计，缺少年份无法确定集合。",
                options=with_choice_exits(options),
            ),
        )
    for ref in query.metrics[1:]:
        extra = _metric(service, ref.id)
        if extra.population and not field_constrained(
            query.filters, extra.population.year_property
        ):
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
    if query.comparison and query.comparison.op != "PERIOD_OVER_PERIOD":
        subjects = _backend(service, "analysis_subjects")(service.bundle, query, actor.tenant)
        if not query.comparison.subject or len(subjects) > 1:
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

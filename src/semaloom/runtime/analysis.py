"""Same-source PostgreSQL SemanticQuery prepare/execute. No caller SQL."""

from __future__ import annotations

import uuid
from typing import Any, cast

from semaloom.core.model import MetricDef
from semaloom.core.results import PopulationRequest
from semaloom.core.semantic_query import (
    UNSUPPORTED_OPERATORS,
    ChoiceOption,
    ChoiceQuestion,
    ComparisonExpr,
    FilterAtom,
    FilterGroup,
    MetricRef,
    PlanRef,
    PrepareResult,
    QueryResult,
    SemanticChoice,
    SemanticQuery,
    SubjectSelector,
    TypedValue,
    conflicting_equalities,
    field_constrained,
    with_choice_exits,
)
from semaloom.core.semantic_query import (
    AnalysisError as AnalysisError,
)
from semaloom.runtime.auth import RequestActor, authorize_query
from semaloom.runtime.query import QueryService

_POP_AGG = {"mean": "AVG", "sum": "SUM", "min": "MIN", "max": "MAX", "count": "COUNT"}
_CMP = {
    "shareOfTotal": "SHARE_OF_TOTAL",
    "percentAboveMean": "RELATIVE_TO_MEAN",
    "outperforms": "STRICT_PEER",
}


def from_population_request(request: PopulationRequest, year_property: str) -> SemanticQuery:
    year_atom = FilterAtom(
        field=year_property,
        op="EQ",
        value=TypedValue(value_type="INTEGER", value=request.year),
    )
    extras = [
        FilterAtom(
            field=key,
            op="EQ",
            value=TypedValue(
                value_type="BOOLEAN"
                if isinstance(val, bool)
                else "INTEGER"
                if isinstance(val, int)
                else "STRING",
                value=val,
            ),
        )
        for key, val in request.filters.items()
        if key != year_property
    ]
    filters: FilterAtom | FilterGroup = (
        FilterGroup(kind="AND", args=(year_atom, *extras)) if extras else year_atom
    )
    comparison = None
    if request.comparison is not None:
        subject = (
            SubjectSelector(identity=request.comparison.identity)
            if request.comparison.identity
            else SubjectSelector(filters=request.comparison.filters)
        )
        comparison = ComparisonExpr(
            op=_CMP[request.comparison.operation],
            metric=request.metric,
            subject=subject,
            direction=request.comparison.direction,
        )
    return SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=(MetricRef(id=request.metric, aggregation=_POP_AGG[request.operation]),),
        filters=filters,
        comparison=comparison,
        missing_policy=request.missing_policy,
        evidence_limit=50,
    )


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


def execute_population(
    service: QueryService, request: PopulationRequest, actor: RequestActor
) -> dict[str, Any]:
    metric = _metric(service, request.metric)
    if metric.population is None:
        raise AnalysisError("POPULATION_NOT_DECLARED")
    spec = metric.population
    if spec.year_property in request.filters and str(request.filters[spec.year_property]) != str(
        request.year
    ):
        raise AnalysisError("CONFLICTING_YEAR")
    query = from_population_request(request, year_property=spec.year_property)
    prepared = prepare(service, query, actor)
    if prepared.status == "NEEDS_INPUT":
        if prepared.question and prepared.question.slot == "subject":
            raise AnalysisError("AMBIGUOUS_COMPARISON_SUBJECT")
        raise AnalysisError("NEEDS_INPUT")
    if prepared.status == "UNSUPPORTED":
        raise AnalysisError(prepared.capability or "OPERATOR_NOT_SUPPORTED")
    if prepared.status == "SOURCE_ERROR":
        raise AnalysisError(prepared.error_code or "PROVIDER_ERROR")
    if prepared.plan is None:
        raise AnalysisError("PROVIDER_ERROR")
    result = execute(service, prepared.plan, actor)
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    key = obj.identity_keys[0]
    scope = result.scope
    members = [
        {
            "identity": {key: row[0]},
            "properties": {},
            "observation": {
                "kind": "NULL" if row[1] in {"None", "", "—"} else "PRESENT",
                "value": None if row[1] in {"None", "", "—"} else row[1],
            },
        }
        for row in result.evidence.rows
    ]
    return {
        "kind": "PopulationAnalysis",
        "metric": metric.id,
        "label": metric.label,
        "releaseDigest": service.bundle.digest,
        "status": "UNAVAILABLE" if scope.get("reason") else "SUCCEEDED",
        "reason": scope.get("reason"),
        "value": result.values[0]["value"] if result.values else None,
        "unit": "count" if request.operation == "count" else metric.unit,
        "operation": request.operation,
        "year": request.year,
        "filters": {**request.filters, spec.year_property: request.year},
        "statisticalUnit": spec.unit_property,
        "populationDescription": spec.description,
        "populationCount": scope["populationCount"],
        "observedCount": scope["observedCount"],
        "missingCount": scope["missingCount"],
        "missingPolicy": request.missing_policy,
        "complete": True,
        "consistency": scope["consistency"],
        "decimalPrecision": 28,
        "comparison": scope.get("comparison"),
        "comparisonRequest": _comparison_request(request, result, key),
        "members": members,
        "sourceActivities": list(result.source_activities),
    }


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
                        for op, label in (
                            ("SUM", "合计"),
                            ("AVG", "平均值"),
                            ("MIN", "最小值"),
                            ("MAX", "最大值"),
                            ("COUNT", "有效观测数量"),
                        )
                    ]
                ),
            ),
        )
    if query.comparison:
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


def _comparison_request(
    request: PopulationRequest, result: QueryResult, identity_key: str
) -> dict[str, Any] | None:
    if request.comparison is None:
        return None
    payload = request.comparison.model_dump(mode="json")
    ident = result.scope.get("subjectIdentity")
    if ident is not None:
        payload["identity"] = {identity_key: ident}
        payload["filters"] = None
    return payload


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

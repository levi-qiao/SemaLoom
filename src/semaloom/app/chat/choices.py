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
from semaloom.app.chat.i18n import text as locale_text
from semaloom.app.chat.intent import RoleConstraint, TurnIntent, slots_for_metric
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
    FilterAtom,
    FilterGroup,
    Formula,
    GroupByItem,
    MeasureTerm,
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
from semaloom.runtime.vocabulary import display_label, mentioned_stored_value


def _choice_context(
    message: str, semantic: SemanticQuery, bundle: CompiledBundle
) -> dict[str, Any]:
    """Frozen ontology snapshot for spoken card copy. Option ids stay server-owned."""
    metric_doc = None
    object_doc = None
    if semantic.metrics:
        metric = next((item for item in bundle.metrics if item.id == semantic.metrics[0].id), None)
        if metric is not None:
            metric_doc = {
                "id": metric.id,
                "label": metric.label,
                "perspective": metric.perspective,
                "objectType": metric.object_type,
            }
            obj = next(
                (item for item in bundle.object_types if item.id == metric.object_type), None
            )
            if obj is not None:
                object_doc = {
                    "id": obj.id,
                    "label": obj.label,
                    "properties": [
                        {
                            "id": prop.id,
                            "label": prop.label,
                            "roles": list(prop.semantic_roles),
                        }
                        for prop in obj.properties
                    ],
                }
    return {
        "userQuestion": message,
        "metric": metric_doc,
        "objectType": object_doc,
    }


def _period_from_year_bindings(
    obj: Any,
    bindings: dict[str, IdentityScalar],
    period_from: str,
    period_to: str,
) -> tuple[str, str]:
    if period_from and period_from != "None":
        return period_from, period_to
    integers = [
        prop
        for prop in obj.properties
        if prop.value_type == "INTEGER" and bindings.get(prop.id) not in {None, ""}
    ]
    tagged = [prop for prop in integers if "time.year" in prop.semantic_roles]
    chosen = tagged if len(tagged) == 1 else integers if len(integers) == 1 else []
    for prop in chosen:
        raw = bindings.get(prop.id)
        if raw in {None, ""}:
            continue
        year = int(raw)
        return f"{year}-01-01", f"{year + 1}-01-01"
    return period_from, period_to


_AGG: dict[str, AggregationOp] = {
    "mean": "AVG",
    "sum": "SUM",
    "min": "MIN",
    "max": "MAX",
    "count": "COUNT",
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


def _scope_property_for_role(
    bundle: CompiledBundle,
    metric_ids: set[str] | frozenset[str],
    role: str,
    value_type: ValueType | None = None,
) -> str | None:
    scopes: set[tuple[str, ...]] = set()
    objects: set[str] = set()
    for metric_id in metric_ids:
        metric = next((item for item in bundle.metrics if item.id == metric_id), None)
        if metric is not None and metric.population is not None:
            scopes.add(metric.population.scope_properties)
            objects.add(metric.object_type)
    if len(scopes) != 1:
        return None
    fields = set(next(iter(scopes)))
    props = [
        prop
        for obj in bundle.object_types
        if obj.id in objects
        for prop in obj.properties
        if prop.id in fields and (value_type is None or prop.value_type == value_type)
    ]
    if role == "scope":
        return next(iter(fields)) if len(fields) == 1 else None
    if role == "integer-scope":
        typed = [prop.id for prop in props if prop.value_type == "INTEGER"]
        return typed[0] if len(typed) == 1 else None
    matches = [prop.id for prop in props if role in prop.semantic_roles]
    if len(matches) == 1:
        return matches[0]
    typed = [prop.id for prop in props]
    return typed[0] if len(typed) == 1 else None


def _role_constraint_filter(field: str, constraint: RoleConstraint) -> FilterAtom:
    value: str | int | bool | tuple[str | int | bool, ...]
    value = constraint.values[0] if constraint.operator == "EQ" else constraint.values
    return FilterAtom(
        field=field,
        op=constraint.operator,
        value=TypedValue(value_type=constraint.value_type, value=value),
    )


def _resolved_role_constraints(
    bundle: CompiledBundle,
    metric_ids: set[str] | frozenset[str],
    intent: TurnIntent,
) -> tuple[tuple[str, RoleConstraint], ...]:
    resolved: list[tuple[str, RoleConstraint]] = []
    for constraint in intent.role_constraints:
        field = _scope_property_for_role(bundle, metric_ids, constraint.role, constraint.value_type)
        if field is not None:
            resolved.append((field, constraint))
    return tuple(resolved)


def _contains_filter_field(node: FilterAtom | FilterGroup | None, field: str) -> bool:
    if isinstance(node, FilterAtom):
        return node.field.split(".")[-1] == field.split(".")[-1]
    if isinstance(node, FilterGroup):
        return any(_contains_filter_field(arg, field) for arg in node.args)
    return False


def _without_filter_field(
    node: FilterAtom | FilterGroup | None, field: str
) -> FilterAtom | FilterGroup | None:
    """Remove a confirmed slot before applying an explicit follow-up replacement."""
    if isinstance(node, FilterAtom):
        return None if _contains_filter_field(node, field) else node
    if node is None:
        return None
    if node.kind == "OR" and _contains_filter_field(node, field):
        # Removing one OR arm would silently retain a different scope. Rebuild
        # the explicit slot from the follow-up instead.
        return None
    kept = tuple(
        item for arg in node.args if (item := _without_filter_field(arg, field)) is not None
    )
    if not kept:
        return None
    if node.kind == "NOT":
        return FilterGroup(kind="NOT", args=kept)
    if len(kept) == 1:
        return kept[0]
    return FilterGroup(kind=node.kind, args=kept)


def query_from_intent(intent: TurnIntent, bundle: CompiledBundle) -> SemanticQuery:
    metrics = tuple(MetricRef(id=item) for item in sorted(intent.metric_ids))
    filters: FilterAtom | FilterGroup | None = None
    for field, constraint in _resolved_role_constraints(bundle, intent.metric_ids, intent):
        atom = _role_constraint_filter(field, constraint)
        filters = atom if filters is None else _append_filter(filters, atom)
    aggregation = _AGG.get(intent.operation) if intent.operation else None
    if aggregation is None and intent.formula_shape and metrics:
        metric = next((item for item in bundle.metrics if item.id == metrics[0].id), None)
        aggregation = default_aggregation(metric.additivity or "FULL") if metric else "SUM"
    metrics = tuple(item.model_copy(update={"aggregation": aggregation}) for item in metrics)
    formula = _formula_from_shape(intent, metrics[0].id, aggregation or "SUM") if metrics else None
    for hit in intent.dimension_filters:
        atom = _typed_atom(hit.field, hit.stored, hit.value_type)
        filters = atom if filters is None else _append_filter(filters, atom)
    group_by: tuple[GroupByItem, ...] = ()
    group_field = (
        _scope_property_for_role(bundle, intent.metric_ids, intent.grouping_role)
        if intent.grouping_role
        else None
    )
    if group_field and metrics:
        # Pre-bucketed business periods are ordinary ontology properties.
        # A physical DATE/DATETIME roll-up uses an adapter-declared timeGrain.
        group_by = (GroupByItem(id=group_field),)
    if intent.group_dimension and metrics:
        item = GroupByItem(id=intent.group_dimension)
        group_by = (*group_by, item) if item not in group_by else group_by
    return SemanticQuery(
        api_version="semaloom/v0.1",
        metrics=metrics,
        filters=filters,
        group_by=group_by,
        formula=formula,
        missing_policy="exclude" if intent.exclude_allowed else "reject",
    )


def _formula_from_shape(
    intent: TurnIntent, metric: str, aggregation: AggregationOp
) -> Formula | None:
    shape = intent.formula_shape
    if shape == "previous":
        return Formula(
            op="VALUE",
            left=MeasureTerm(metric=metric, aggregation=aggregation, previous_observed=True),
        )
    if shape == "subject_ratio":
        return Formula(
            op="RATIO",
            left=MeasureTerm(metric=metric, aggregation="SUM", scope="SUBJECT"),
            right=MeasureTerm(metric=metric, aggregation="SUM"),
        )
    if shape == "mean_delta":
        return Formula(
            op="RATIO",
            left=Formula(
                op="DIFFERENCE",
                left=MeasureTerm(metric=metric, aggregation="SUM", scope="SUBJECT"),
                right=MeasureTerm(metric=metric, aggregation="AVG"),
            ),
            right=MeasureTerm(metric=metric, aggregation="AVG"),
        )
    if shape == "peer":
        relation = intent.peer_relation or "LT"
        return Formula(
            op="RATIO",
            left=MeasureTerm(
                metric=metric, aggregation="COUNT", scope="PEERS", value_relation=relation
            ),
            right=MeasureTerm(metric=metric, aggregation="COUNT", scope="PEERS"),
        )
    return None


def _formula_signature(node: Formula | MeasureTerm) -> tuple[Any, ...]:
    if isinstance(node, MeasureTerm):
        return (node.aggregation, node.scope, node.value_relation, node.previous_observed)
    return (
        node.op,
        _formula_signature(node.left),
        None if node.right is None else _formula_signature(node.right),
    )


def _grouping_question(
    service: QueryService, message: str, semantic: SemanticQuery, intent: TurnIntent
) -> dict[str, Any]:
    bundle = service.bundle
    metric_ids = {item.id for item in semantic.metrics} or set(intent.metric_ids)
    objects = {item.id: item for item in bundle.object_types}
    options: list[ChoiceOption] = []
    seen: set[str] = set()
    for metric in bundle.metrics:
        if metric.id not in metric_ids:
            continue
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
                if field in seen:
                    continue
                seen.add(field)
                label = prop.label or prop.id
                if owner.id != metric.object_type and owner.label and prop.label:
                    label = f"{owner.label}{prop.label}"
                options.append(
                    ChoiceOption(
                        id="opt_group_" + field.replace(".", "_"),
                        label=label,
                        explanation="按这个属性分组",
                        choice=SemanticChoice(kind="GROUP", id=field),
                    )
                )
    question = ChoiceQuestion(
        question_id="q-group-" + uuid.uuid4().hex,
        revision=1,
        slot="group",
        prompt="要按哪个属性分组？",
        reason="这句话里的分组没有对上已发布的属性。",
        options=with_choice_exits(options[:6]),
    )
    return {
        "status": "NEEDS_INPUT",
        "waiting": True,
        "question": question.model_dump(mode="json", by_alias=True),
        "query": semantic.model_dump(mode="json", by_alias=True),
        "originalQuestion": message,
        "releaseDigest": bundle.digest,
    }


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
    for field, constraint in _resolved_role_constraints(
        bundle, {item.id for item in metrics}, intent
    ):
        if field_constrained(query.filters, field):
            existing = equality_value(query.filters, field)
            if constraint.operator != "EQ" or existing != constraint.values[0]:
                raise AnalysisError("REQUEST_SCOPE_DOES_NOT_MATCH_USER")
        else:
            updates["filters"] = _append_filter(
                updates.get("filters", query.filters),
                _role_constraint_filter(field, constraint),
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
    if intent.formula_shape:
        operation = intent.operation or "sum"
        expected = _formula_from_shape(
            intent,
            metrics[0].id if metrics else "",
            _AGG[operation],
        )
        if expected is None or query.formula is None:
            raise AnalysisError("FORMULA_REQUIRED_BY_USER")
        if query.formula.op != expected.op or _formula_signature(
            query.formula
        ) != _formula_signature(expected):
            raise AnalysisError("FORMULA_REQUIRED_BY_USER")
    filters = updates.get("filters", query.filters)
    for hit in intent.dimension_filters:
        if not field_constrained(filters, hit.field.split(".")[-1]):
            filters = _append_filter(filters, _typed_atom(hit.field, hit.stored, hit.value_type))
            updates["filters"] = filters
    if intent.group_dimension and not query.group_by:
        updates["group_by"] = (GroupByItem(id=intent.group_dimension),)
    for field, constraint in _resolved_role_constraints(
        bundle, {item.id for item in metrics}, intent
    ):
        if constraint.operator != "IN":
            continue

        # A model proposal must preserve every explicit value from the adapter.
        def constrained_values(
            node: FilterAtom | FilterGroup | None, target_field: str = field
        ) -> set[str]:
            if (
                isinstance(node, FilterAtom)
                and node.field.split(".")[-1] == target_field.split(".")[-1]
            ):
                value = node.value.value
                if node.op == "EQ":
                    return {str(value)}
                if node.op == "IN" and isinstance(value, tuple):
                    return {str(item) for item in value}
            if isinstance(node, FilterGroup):
                return set().union(*(constrained_values(arg) for arg in node.args))
            return set()

        if not {str(item) for item in constraint.values} <= constrained_values(
            updates.get("filters", query.filters)
        ):
            raise AnalysisError("REQUEST_SCOPE_DOES_NOT_MATCH_USER")
    return query.model_copy(update=updates) if updates else query


def _scope_values_for(
    service: QueryService, metric_id: str, field: str, tenant: str
) -> list[str | int | bool]:
    metric = next((m for m in service.bundle.metrics if m.id == metric_id), None)
    if metric is None or not getattr(metric, "population", None):
        return []
    handler = getattr(service.provider, "analysis_dimension_values", None)
    if not callable(handler):
        return []
    try:
        values = handler(service.bundle, metric_id, field, tenant)
    except Exception:
        return []
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return []
    return list(values)


def _observed_scope_values(
    service: QueryService, metric_id: str, field: str, tenant: str
) -> list[str | int | bool] | None:
    """Return observed values, preserving source failure as unknown rather than empty."""
    handler = getattr(service.provider, "analysis_dimension_values", None)
    if not callable(handler):
        return None
    try:
        values = handler(service.bundle, metric_id, field, tenant)
    except Exception:
        return None
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return None
    return list(values)


def _revalidate_carried_scope(
    query: SemanticQuery,
    intent: TurnIntent,
    service: QueryService,
    actor: RequestActor,
) -> SemanticQuery:
    """Drop a stale implicit scope after the user names a metric with no value there."""
    if not intent.metric_ids or not query.metrics:
        return query
    explicit_fields = {hit.field.split(".")[-1] for hit in intent.dimension_filters}
    explicit_fields.update(
        field
        for field, _ in _resolved_role_constraints(
            service.bundle, {item.id for item in query.metrics}, intent
        )
    )
    filters = query.filters
    stale_fields: set[str] = set()
    for ref in query.metrics:
        metric = next((item for item in service.bundle.metrics if item.id == ref.id), None)
        if metric is None or metric.population is None:
            continue
        for field in metric.population.scope_properties:
            if field in explicit_fields or not field_constrained(filters, field):
                continue
            selected = equality_value(filters, field)
            if selected is None:
                continue
            observed = _observed_scope_values(service, metric.id, field, actor.tenant)
            if observed is None:
                continue
            if not any(str(value) == str(selected) for value in observed):
                filters = _without_filter_field(filters, field)
                stale_fields.add(field)
    if not stale_fields:
        return query
    decisions = tuple(
        decision
        for decision in query.decisions
        if not (decision.choice.kind == "DIMENSION_VALUE" and decision.choice.field in stale_fields)
    )
    return query.model_copy(update={"filters": filters, "decisions": decisions})


def _complete_explicit_scope(
    query: SemanticQuery,
    intent: TurnIntent,
    bundle: CompiledBundle,
    service: QueryService,
    actor: RequestActor,
    message: str = "",
) -> tuple[SemanticQuery, list[dict[str, str]]]:
    """Resolve explicit scope; leave missing business choices to engine prepare."""
    updates: dict[str, Any] = {}
    assumptions: list[dict[str, str]] = []
    if query.group_by and not (intent.group_dimension or intent.grouping_role):
        updates["group_by"] = ()
        assumptions.append({"slot": "grain", "id": "total", "reason": "USER_DID_NOT_ASK_BREAKDOWN"})
    elif intent.group_dimension and not query.group_by and query.metrics:
        updates["group_by"] = (GroupByItem(id=intent.group_dimension),)
    scope_field = (
        _scope_property_for_role(bundle, {item.id for item in query.metrics}, intent.grouping_role)
        if intent.grouping_role
        else None
    )
    if (
        scope_field
        and query.metrics
        and intent.grouping_role
        and not field_constrained(query.filters, scope_field)
    ):
        values = sorted(
            _scope_values_for(service, query.metrics[0].id, scope_field, actor.tenant),
            key=str,
        )
        if intent.grouping_limit is not None:
            values = values[-intent.grouping_limit :]
        if values:
            obj = next(
                item
                for item in bundle.object_types
                if item.id
                == next(m for m in bundle.metrics if m.id == query.metrics[0].id).object_type
            )
            prop = next(item for item in obj.properties if item.id == scope_field)
            updates["filters"] = _append_filter(
                query.filters,
                FilterAtom(
                    field=scope_field,
                    op="IN",
                    value=TypedValue(value_type=prop.value_type, value=tuple(values)),
                ),
            )
    current = query.model_copy(update=updates) if updates else query
    mentioned = _bind_mentioned_observed_values(current, message, bundle, service, actor)
    if mentioned is not current:
        current = mentioned
    return current, assumptions


def _bind_mentioned_observed_values(
    query: SemanticQuery,
    message: str,
    bundle: CompiledBundle,
    service: QueryService,
    actor: RequestActor,
) -> SemanticQuery:
    """If the user already named an observed scope value, do not ask again."""
    if not query.metrics or not message.strip():
        return query
    filters = query.filters
    changed = False
    for ref in query.metrics:
        metric = next((item for item in bundle.metrics if item.id == ref.id), None)
        if metric is None or metric.population is None:
            continue
        obj = next((item for item in bundle.object_types if item.id == metric.object_type), None)
        for field in metric.population.scope_properties:
            if field_constrained(filters, field):
                continue
            values = _scope_values_for(service, metric.id, field, actor.tenant)
            if not values:
                continue
            prop = None
            if obj is not None:
                prop = next((item for item in obj.properties if item.id == field), None)
            hit = mentioned_stored_value(message, values, prop)
            if hit is None:
                continue
            value_type = prop.value_type if prop is not None else "STRING"
            filters = _append_filter(filters, _typed_atom(field, str(hit), value_type))
            changed = True
    if not changed:
        return query
    return query.model_copy(update={"filters": filters})


def _follow_ups(bundle: CompiledBundle, query: SemanticQuery) -> list[dict[str, str]]:
    if not query.metrics:
        return []
    labels = {metric.id: metric.label or metric.id for metric in bundle.metrics}
    name = "、".join(labels.get(ref.id, ref.id) for ref in query.metrics)
    scope_fields = {
        field
        for ref in query.metrics
        for metric in bundle.metrics
        if metric.id == ref.id and metric.population is not None
        for field in metric.population.scope_properties
    }
    scope_field = next(iter(scope_fields)) if len(scope_fields) == 1 else None
    scope_value = equality_value(query.filters, scope_field) if scope_field else None
    # Follow-ups are new questions: only suggest a scope we can preserve exactly.
    if query.filters is not None and scope_value is None:
        return []
    if isinstance(query.filters, FilterGroup) and len(query.filters.args) > 1:
        return []
    scope_text = f"{scope_value} " if scope_value is not None else ""
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
                {"label": f"按{label}看", "message": f"{scope_text}{name}按{label}{operation}"}
            )
    if not query.group_by:
        items.append(
            {"label": "看各对象明细", "message": f"{scope_text}{name}按对象列出明细{operation}"}
        )
    return items[:3]


def _continue_after_duplicate(
    service: QueryService,
    actor: RequestActor,
    message: str,
    semantic: SemanticQuery,
    locale: str,
    assumptions: list[dict[str, str]],
) -> dict[str, Any]:
    """Ask for a missing business condition instead of stopping on a grain clash."""
    retry = prepare(service, semantic, actor)
    if retry.status == "NEEDS_INPUT" and retry.question is not None:
        payload = retry.model_dump(mode="json", by_alias=True)
        payload.update(
            {
                "query": semantic.model_dump(mode="json", by_alias=True),
                "originalQuestion": message,
                "releaseDigest": service.bundle.digest,
                "assumptions": assumptions,
                "waiting": True,
            }
        )
        return payload
    question = ChoiceQuestion(
        question_id="q-refine-scope-" + uuid.uuid4().hex,
        revision=1,
        slot="scope",
        prompt=locale_text(locale, "duplicateUnit.prompt"),
        reason=locale_text(locale, "duplicateUnit.reason"),
        options=with_choice_exits(()),
    )
    return {
        "status": "NEEDS_INPUT",
        "waiting": True,
        "question": question.model_dump(mode="json", by_alias=True),
        "query": semantic.model_dump(mode="json", by_alias=True),
        "originalQuestion": message,
        "releaseDigest": service.bundle.digest,
        "assumptions": assumptions,
    }


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
    service: QueryService,
    actor: RequestActor,
    message: str,
    locale: str = "zh-CN",
    confirmed_query: dict[str, Any] | SemanticQuery | None = None,
) -> dict[str, Any] | None:
    """Answer or ask from ontology intent without a model when the question is structured."""
    text = message.strip()
    if not text or _DEFINITION.search(text):
        return None
    intent = TurnIntent.read(text, service.bundle)
    if confirmed_query is not None and not (intent.metric_ids or intent.candidates):
        prior = SemanticQuery.model_validate(confirmed_query)
        explicit_refinement = bool(
            intent.role_constraints
            or intent.operation
            or intent.dimension_filters
            or intent.group_dimension
            or intent.formula_shape
        )
        if explicit_refinement and prior.metrics:
            updates: dict[str, Any] = {}
            filters = prior.filters
            for field, constraint in _resolved_role_constraints(
                service.bundle, {item.id for item in prior.metrics}, intent
            ):
                filters = _without_filter_field(filters, field)
                filters = _append_filter(filters, _role_constraint_filter(field, constraint))
            if filters is not prior.filters:
                updates["filters"] = filters
            if intent.operation:
                updates["metrics"] = tuple(
                    item.model_copy(update={"aggregation": None}) for item in prior.metrics
                )
            return prepare_turn(
                service,
                actor,
                text,
                prior.model_copy(update=updates) if updates else prior,
                locale,
            )
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
        intent.formula_shape
        or intent.clarify_grouping
        or intent.dimension_filters
        or intent.need_dimension
        or intent.group_dimension
        or intent.grouping_role
        or intent.role_constraints
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
        semantic = semantic.model_copy(update={"metrics": (), "formula": None})
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
                    explanation=metric.description or metric.label or " ",
                    choice=SemanticChoice(kind="METRIC", id=metric_id),
                )
            )
        if options:
            question = ChoiceQuestion(
                question_id="q-metric-intent-" + uuid.uuid4().hex,
                revision=1,
                slot="metric",
                prompt="请选择要看的指标。",
                reason="这句话对应多项，选定后结果会不同。",
                options=with_choice_exits(options),
            )
            return {
                "status": "NEEDS_INPUT",
                "waiting": True,
                "question": question.model_dump(mode="json", by_alias=True),
                "query": semantic.model_dump(mode="json", by_alias=True),
                "originalQuestion": message,
                "releaseDigest": service.bundle.digest,
                "choiceContext": _choice_context(message, semantic, service.bundle),
            }
    if intent.clarify_formula and not any(
        d.choice.kind == "COMPARISON" for d in semantic.decisions
    ):
        question = ChoiceQuestion(
            question_id="q-formula-" + uuid.uuid4().hex,
            revision=1,
            slot="formula",
            prompt="你希望怎样比较？",
            reason="这几种算法的分母不同。",
            options=with_choice_exits(
                [
                    ChoiceOption(
                        id="opt_" + op,
                        label=label,
                        explanation=explanation,
                        choice=SemanticChoice(kind="COMPARISON", id=op),
                    )
                    for op, label, explanation in (
                        ("subject-ratio", "占总体合计", "主体数值除以总体合计"),
                        ("mean-delta", "相对总体均值", "主体与总体平均值的差，再除以平均值"),
                        ("peer-fraction", "严格优于同行的比例", "严格胜出的同行数量除以同行数量"),
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
    if intent.clarify_grouping and not any(d.choice.kind == "GROUP" for d in semantic.decisions):
        return _grouping_question(service, message, semantic, intent)
    metric_ids = {item.id for item in semantic.metrics} or intent.metric_ids
    if intent.formula_shape == "previous" and metric_ids:
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
    semantic = _revalidate_carried_scope(semantic, intent, service, actor)
    semantic = _apply_intent(semantic, intent, service.bundle)
    semantic, assumptions = _complete_explicit_scope(
        semantic, intent, service.bundle, service, actor, message
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
            if exc.code == "DUPLICATE_OR_MISSING_STATISTICAL_UNIT":
                return _continue_after_duplicate(
                    service, actor, message, semantic, locale, assumptions
                )
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
        payload["choiceContext"] = _choice_context(message, semantic, service.bundle)
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
    identity_payload: dict[str, str | int | bool] = dict(identity or {})
    resolved_constraints = _resolved_role_constraints(service.bundle, {metric.id}, intent)
    for field, constraint in resolved_constraints:
        if constraint.operator == "EQ":
            identity_payload[field] = constraint.values[0]
    filters = {key: value for key, value in identity_payload.items() if key in obj.identity_keys}
    extra_bindings = {
        key: value for key, value in identity_payload.items() if key not in obj.identity_keys
    }
    display = [
        prop.id
        for prop in obj.properties
        if prop.value_type == "STRING" and prop.id not in obj.identity_keys
    ][:3]
    period_fields: tuple[str, ...] = ()
    if obj.period is not None:
        period_fields = (obj.period.from_property, obj.period.to_property)
    requested = tuple(dict.fromkeys([*display, *period_fields, *rule.applicability]))
    try:
        found = service.find_objects(
            ObjectSearchRequest(
                object_type=obj.id,
                filters=filters,
                properties=requested,
                limit=50,
            ),
            actor,
        )
    except ValueError:
        found = {"objects": [], "hasMore": False}
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
            if obj.population:
                scope_parts = [
                    str(props[field])
                    for field in obj.population.scope_properties
                    if props.get(field) is not None
                ]
                if scope_parts:
                    label += " · " + " / ".join(scope_parts)
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
                "text": "当前范围没有可核验的对象，请核对对象名称或范围条件。",
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
    metric_grain = set(metric.grain)
    for field, constraint in resolved_constraints:
        if constraint.operator == "EQ" and field in obj.identity_keys:
            bindings[field] = constraint.values[0]
    scope_values = {**extra_bindings}
    for field, constraint in resolved_constraints:
        if constraint.operator == "EQ" and field in metric_grain and field not in obj.identity_keys:
            scope_values[field] = constraint.values[0]
    props = row.get("properties") or {}
    period_from = str(props.get(period_fields[0])) if period_fields else ""
    period_to = str(props.get(period_fields[1])) if len(period_fields) > 1 else ""
    if not period_from or period_from == "None":
        period_from, period_to = _period_from_year_bindings(
            obj, {**bindings, **scope_values}, period_from, period_to
        )
    if (not period_from or period_from == "None") and metric.population:
        missing_scope = next(
            (
                field
                for field in metric.population.scope_properties
                if field not in bindings and field not in scope_values
            ),
            None,
        )
        if missing_scope is not None:
            observed_scope = _scope_values_for(service, metric.id, missing_scope, actor.tenant)
            prop = next((item for item in obj.properties if item.id == missing_scope), None)
            if prop is not None and observed_scope:
                mentioned = mentioned_stored_value(message, observed_scope, prop)
                if mentioned is not None:
                    bindings[missing_scope] = mentioned
                    period_from, period_to = _period_from_year_bindings(
                        obj, bindings, period_from, period_to
                    )
                else:
                    options = [
                        ChoiceOption(
                            id=f"opt_claim_scope_{index}",
                            label=display_label(prop, value),
                            explanation=prop.label or prop.id,
                            choice=SemanticChoice(
                                kind="DIMENSION_VALUE",
                                id=str(value),
                                field=missing_scope,
                                predicate=_typed_atom(missing_scope, str(value), prop.value_type),
                            ),
                        )
                        for index, value in enumerate(observed_scope[:5])
                    ]
                    question = ChoiceQuestion(
                        question_id="q-claim-scope-" + uuid.uuid4().hex,
                        revision=1,
                        slot="scope:" + missing_scope,
                        prompt=(
                            f"要核验{rule.label or '这条规则'}，请选择{prop.label or prop.id}。"
                        ),
                        reason="选定后继续判断，不猜测期间。",
                        options=with_choice_exits(options),
                    )
                    return {
                        "status": "NEEDS_INPUT",
                        "waiting": True,
                        "mode": "claim",
                        "claimId": claim_id,
                        "question": question.model_dump(mode="json", by_alias=True),
                        "query_state": {
                            "mode": "claim",
                            "claimId": claim_id,
                            "identity": bindings,
                            "originalQuestion": message,
                        },
                        "originalQuestion": message,
                        "releaseDigest": service.bundle.digest,
                    }
    if not period_from or period_from == "None":
        question = ChoiceQuestion(
            question_id="q-claim-period-" + uuid.uuid4().hex,
            revision=1,
            slot="claimPeriod",
            prompt="要按哪个业务期间核验？",
            reason="这条规则还需要一个生效期间。",
            options=with_choice_exits(()),
        )
        return {
            "status": "NEEDS_INPUT",
            "waiting": True,
            "question": question.model_dump(mode="json", by_alias=True),
            "query_state": {"mode": "claim", "claimId": claim_id, "identity": bindings},
            "originalQuestion": message,
            "releaseDigest": service.bundle.digest,
        }
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
            "text": "这条规则还不能完成核验，请补充对象或期间后再试。",
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
        elif chosen.choice.kind == "DIMENSION_VALUE" and chosen.choice.field:
            identity = dict(state.get("identity") or {})
            identity[chosen.choice.field] = chosen.choice.id
            prepared = prepare_claim_turn(
                service,
                actor,
                original,
                claim_id=str(state.get("claimId") or ""),
                identity=identity,
            )
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

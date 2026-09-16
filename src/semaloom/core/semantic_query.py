"""Composable semantic analysis contract (Q0). Execution lives in runtime (Q1).

Callers submit semantic identifiers and typed values only. SQL, join text,
permissions and arbitrary plan patches are not request inputs.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field, model_validator

from semaloom.core.model import ValueType
from semaloom.core.values import scalar_value
from semaloom.core.wire import wire_config

PREPARE_STATUSES = ("READY", "NEEDS_INPUT", "UNSUPPORTED", "SOURCE_ERROR")
PrepareStatus = Literal["READY", "NEEDS_INPUT", "UNSUPPORTED", "SOURCE_ERROR"]
FilterOp = Literal["EQ", "NE", "LT", "LE", "GT", "GE", "IN", "BETWEEN"]
BoolOp = Literal["AND", "OR", "NOT"]
AggregationOp = Literal["SUM", "MIN", "MAX", "COUNT", "AVG"]
TimeGrain = Literal["YEAR", "MONTH"]
ComparisonOp = Literal["SHARE_OF_TOTAL", "RELATIVE_TO_MEAN", "STRICT_PEER"]
ChoiceKind = Literal[
    "METRIC",
    "YEAR",
    "AGGREGATION",
    "COMPARISON",
    "MISSING_POLICY",
    "SUBJECT",
    "DIMENSION_VALUE",
    "ABORT",
    "FILTER",
    "OTHER",
]
AbortCode = Literal["unclear", "mismatch"]
MissingPolicy = Literal["reject", "exclude"]

SUPPORTED_FILTER_OPS: frozenset[str] = frozenset(
    {"EQ", "NE", "LT", "LE", "GT", "GE", "IN", "BETWEEN", "AND", "OR", "NOT"}
)
SUPPORTED_AGGREGATIONS: frozenset[str] = frozenset({"SUM", "MIN", "MAX", "COUNT", "AVG"})
SUPPORTED_TIME_GRAINS: frozenset[str] = frozenset({"YEAR", "MONTH"})
SUPPORTED_COMPARISONS: frozenset[str] = frozenset(
    {"SHARE_OF_TOTAL", "RELATIVE_TO_MEAN", "STRICT_PEER"}
)
UNSUPPORTED_OPERATORS: frozenset[str] = frozenset(
    {
        "WINDOW_LAG",
        "WINDOW_LEAD",
        "NTILE",
        "RECURSIVE_CTE",
        "CROSS_SOURCE_SQL",
        "RAW_SQL",
        "UDF",
        "DISTINCT_AMOUNT_DEDUP",
        "COALESCE_MISSING_TO_ZERO",
        "FLOAT_ARITHMETIC",
        "UNBOUNDED_MANY_TO_MANY",
        "CUSTOM_WINDOW_FRAME",
    }
)


class AnalysisError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ChoiceError(ValueError):
    """Predictable choice-submit failure. ``code`` is the stable machine token."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Frozen(BaseModel):
    model_config = wire_config()


class TypedValue(_Frozen):
    value_type: ValueType
    value: str | int | bool | tuple[str | int | bool, ...]

    @model_validator(mode="after")
    def shape_matches_op_context(self) -> TypedValue:
        if isinstance(self.value, tuple) and not self.value:
            raise ValueError("typed value sequence must not be empty")
        values = self.value if isinstance(self.value, tuple) else (self.value,)
        for value in values:
            if self.value_type == "BOOLEAN" and not isinstance(value, bool):
                raise ValueError("BOOLEAN requires a boolean")
            if self.value_type != "BOOLEAN" and isinstance(value, bool):
                raise ValueError("boolean is not a numeric or text value")
            if self.value_type == "STRING" and not isinstance(value, str):
                raise ValueError("STRING requires a string")
            scalar_value(str(value), self.value_type)
        return self


class FilterAtom(_Frozen):
    kind: Literal["PRED"] = "PRED"
    field: str
    op: FilterOp
    value: TypedValue

    @model_validator(mode="after")
    def value_arity(self) -> FilterAtom:
        raw = self.value.value
        if self.op == "BETWEEN":
            if not isinstance(raw, tuple) or len(raw) != 2:
                raise ValueError("BETWEEN requires exactly two typed values")
        elif self.op == "IN":
            if not isinstance(raw, tuple):
                raise ValueError("IN requires a non-empty sequence")
        elif isinstance(raw, tuple):
            raise ValueError(f"{self.op} does not accept a sequence")
        return self


class FilterGroup(_Frozen):
    kind: BoolOp
    args: tuple[FilterAtom | FilterGroup, ...]

    @model_validator(mode="after")
    def args_match_kind(self) -> FilterGroup:
        if self.kind == "NOT":
            if len(self.args) != 1:
                raise ValueError("NOT requires exactly one argument")
        elif len(self.args) < 1:
            raise ValueError(f"{self.kind} requires at least one argument")
        return self


FilterGroup.model_rebuild()


class MetricRef(_Frozen):
    id: str
    aggregation: AggregationOp | None = None


class GroupByItem(_Frozen):
    id: str
    time_grain: TimeGrain | None = None


class OrderByItem(_Frozen):
    field: str
    direction: Literal["ASC", "DESC"] = "DESC"


class SubjectSelector(_Frozen):
    identity: dict[str, str] | None = None
    filters: dict[str, str | int | bool] | None = None

    @model_validator(mode="after")
    def one_selector(self) -> SubjectSelector:
        if bool(self.identity) == bool(self.filters):
            raise ValueError("provide exactly one non-empty identity or filters")
        return self


class ComparisonExpr(_Frozen):
    op: ComparisonOp
    metric: str
    subject: SubjectSelector | None = None
    direction: Literal["higher", "lower"] = "higher"


class SemanticChoice(_Frozen):
    kind: ChoiceKind
    id: str
    field: str | None = None
    predicate: FilterAtom | None = None


class ChoiceOption(_Frozen):
    id: str
    label: str
    explanation: str
    choice: SemanticChoice


def abort_option(
    code: AbortCode = "unclear",
    label: str = "都不符合 / 暂不清楚",
    explanation: str = "停止本次计算，不猜测口径",  # noqa: RUF001
) -> ChoiceOption:
    return ChoiceOption(
        id="opt_abort_" + code,
        label=label,
        explanation=explanation,
        choice=SemanticChoice(kind="ABORT", id=code),
    )


def other_option() -> ChoiceOption:
    return ChoiceOption(
        id="opt_other_input",
        label="其他",
        explanation="用一句话补充年份、口径或对象，系统按原问题继续",  # noqa: RUF001
        choice=SemanticChoice(kind="OTHER", id="free_text"),
    )


def with_choice_exits(
    options: list[ChoiceOption] | tuple[ChoiceOption, ...],
) -> tuple[ChoiceOption, ...]:
    live = [item for item in options if item.choice.kind not in {"ABORT", "OTHER"}]
    return tuple([*live, other_option(), abort_option()])


class ChoiceQuestion(_Frozen):
    question_id: str
    revision: int = Field(ge=1)
    slot: str
    prompt: str
    reason: str
    multi_select: bool = False
    options: tuple[ChoiceOption, ...]

    @model_validator(mode="after")
    def options_are_usable(self) -> ChoiceQuestion:
        if not (2 <= len(self.options) <= 8):
            raise ValueError("choice questions must offer 2-8 options")
        ids = [item.id for item in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("option ids must be unique")
        kinds = {item.choice.kind for item in self.options}
        if "ABORT" not in kinds:
            raise ValueError("choice questions must include an ABORT option")
        if self.multi_select and self.slot in {"metric", "year", "missingPolicy"}:
            raise ValueError("metric, year and missingPolicy questions are single-select")
        return self


class ChoiceSubmit(_Frozen):
    question_id: str
    revision: int = Field(ge=1)
    option_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    other_text: str | None = Field(default=None, max_length=400)


class Decision(_Frozen):
    slot: str
    option_id: str
    choice: SemanticChoice
    question_id: str
    revision: int


class SemanticQuery(_Frozen):
    api_version: Literal["semaloom/v0.1"]
    metrics: tuple[MetricRef, ...] = Field(default=(), max_length=8)
    group_by: tuple[GroupByItem, ...] = Field(default=(), max_length=8)
    filters: FilterAtom | FilterGroup | None = None
    order_by: tuple[OrderByItem, ...] = ()
    limit: int | None = Field(default=None, ge=1, le=1000)
    comparison: ComparisonExpr | None = None
    missing_policy: MissingPolicy | None = None
    evidence_limit: int = Field(default=50, ge=1, le=50)
    decisions: tuple[Decision, ...] = ()

    @model_validator(mode="after")
    def bounded_filters(self) -> SemanticQuery:
        pending = [(self.filters, 0)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if depth > 12 or count > 100:
                raise ValueError("query filter budget exceeded")
            if isinstance(node, FilterGroup):
                pending.extend((arg, depth + 1) for arg in node.args)
        return self


class PlanRef(_Frozen):
    plan_id: str
    release_digest: str
    query: SemanticQuery
    compiled_digest: str


class EvidenceColumn(_Frozen):
    id: str
    label: str


class EvidenceTable(_Frozen):
    columns: tuple[EvidenceColumn, ...]
    rows: tuple[tuple[str, ...], ...]
    truncated: bool = False
    row_count: int | None = None


class PrepareResult(_Frozen):
    status: PrepareStatus
    plan: PlanRef | None = None
    question: ChoiceQuestion | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    capability: str | None = None

    @model_validator(mode="after")
    def payload_matches_status(self) -> PrepareResult:
        if self.status == "READY":
            if self.plan is None or self.question is not None:
                raise ValueError("READY requires a plan and no question")
        elif self.status == "NEEDS_INPUT":
            if self.question is None or self.plan is not None:
                raise ValueError("NEEDS_INPUT requires a question and no plan")
        elif self.status in {"UNSUPPORTED", "SOURCE_ERROR"}:
            if not self.error_code or self.plan is not None or self.question is not None:
                raise ValueError(f"{self.status} requires errorCode and no plan/question")
            if self.status == "SOURCE_ERROR" and not self.retryable:
                raise ValueError("SOURCE_ERROR must be retryable")
            if self.status == "UNSUPPORTED" and not self.capability:
                raise ValueError("UNSUPPORTED requires a capability name")
        return self


class QuerySessionState(_Frozen):
    conversation_id: str
    tenant_id: str
    actor_id: str
    release_digest: str
    original_question: str
    query: SemanticQuery
    pending_question: ChoiceQuestion | None = None
    plan_id: str | None = None
    result_id: str | None = None
    question_revision: int = 0


class QueryResult(_Frozen):
    result_id: str
    plan_id: str
    release_digest: str
    values: tuple[dict[str, Any], ...]
    scope: dict[str, Any]
    mapping_fields: tuple[dict[str, Any], ...]
    evidence: EvidenceTable
    source_activities: tuple[dict[str, Any], ...] = ()


def _append_filter(existing: FilterAtom | FilterGroup | None, atom: FilterAtom) -> FilterGroup:
    if existing is None:
        return FilterGroup(kind="AND", args=(atom,))
    if isinstance(existing, FilterGroup) and existing.kind == "AND":
        return FilterGroup(kind="AND", args=(*existing.args, atom))
    return FilterGroup(kind="AND", args=(existing, atom))


def merge_decision(
    query: SemanticQuery, question: ChoiceQuestion, submit: ChoiceSubmit
) -> SemanticQuery:
    """Apply a client option-id submit onto the canonical query.

    The client never sends SQL, permissions, or a plan patch — only option ids
    that already exist on the server-owned question.
    """

    if submit.question_id != question.question_id:
        raise ChoiceError("QUESTION_MISMATCH")
    if submit.revision != question.revision:
        raise ChoiceError("VERSION_INVALID")
    if any(item.question_id == question.question_id for item in query.decisions):
        raise ChoiceError("DUPLICATE_SUBMIT")
    if question.multi_select is False and len(submit.option_ids) != 1:
        raise ChoiceError("SINGLE_SELECT_REQUIRED")
    by_id = {item.id: item for item in question.options}
    selected: list[ChoiceOption] = []
    for option_id in submit.option_ids:
        option = by_id.get(option_id)
        if option is None:
            raise ChoiceError("UNKNOWN_OPTION")
        selected.append(option)
    if any(item.choice.kind == "ABORT" for item in selected):
        if len(selected) != 1:
            raise ChoiceError("ABORT_MUST_BE_ALONE")
        raise ChoiceError("ABORTED")
    metrics = list(query.metrics)
    filters = query.filters
    missing = query.missing_policy
    comparison = query.comparison
    for option in selected:
        choice = option.choice
        if choice.kind == "METRIC":
            if any(item.id == choice.id for item in metrics):
                continue
            metrics.append(MetricRef(id=choice.id))
        elif choice.kind == "AGGREGATION":
            if choice.id not in SUPPORTED_AGGREGATIONS:
                raise ChoiceError("UNKNOWN_OPTION")
            aggregation = cast(AggregationOp, choice.id)
            metrics = [item.model_copy(update={"aggregation": aggregation}) for item in metrics]
        elif choice.kind == "COMPARISON":
            if choice.id not in SUPPORTED_COMPARISONS or not metrics:
                raise ChoiceError("UNKNOWN_OPTION")
            comparison = ComparisonExpr(
                op=cast(ComparisonOp, choice.id),
                metric=metrics[0].id,
                subject=comparison.subject if comparison else None,
            )
        elif choice.kind == "FILTER":
            if choice.predicate is None:
                raise ChoiceError("INVALID_CHOICE")
            filters = _append_filter(
                without_field(filters, choice.predicate.field), choice.predicate
            )
        elif choice.kind == "YEAR":
            field = choice.field
            if field is None:
                raise ChoiceError("YEAR_FIELD_REQUIRED")
            filters = _append_filter(
                filters,
                FilterAtom(
                    field=field,
                    op="EQ",
                    value=TypedValue(value_type="INTEGER", value=int(choice.id)),
                ),
            )
        elif choice.kind == "MISSING_POLICY":
            if choice.id not in {"reject", "exclude"}:
                raise ChoiceError("UNKNOWN_OPTION")
            missing = choice.id  # type: ignore[assignment]
        elif choice.kind == "SUBJECT":
            if choice.field is None:
                raise ChoiceError("SUBJECT_FIELD_REQUIRED")
            comparison = ComparisonExpr(
                op=comparison.op if comparison else "SHARE_OF_TOTAL",
                metric=comparison.metric if comparison else metrics[0].id,
                subject=SubjectSelector(identity={choice.field: choice.id}),
                direction=comparison.direction if comparison else "higher",
            )
        elif choice.kind == "DIMENSION_VALUE":
            if choice.field is None:
                raise ChoiceError("DIMENSION_FIELD_REQUIRED")
            filters = _append_filter(
                filters,
                FilterAtom(
                    field=choice.field,
                    op="EQ",
                    value=TypedValue(value_type="STRING", value=choice.id),
                ),
            )
        elif choice.kind == "OTHER":
            raise ChoiceError("OTHER_NOT_MERGEABLE")
        else:
            raise ChoiceError("UNKNOWN_OPTION")
    decisions = (
        *query.decisions,
        *(
            Decision(
                slot=question.slot,
                option_id=option.id,
                choice=option.choice,
                question_id=question.question_id,
                revision=question.revision,
            )
            for option in selected
        ),
    )
    return query.model_copy(
        update={
            "metrics": tuple(metrics),
            "filters": filters,
            "missing_policy": missing,
            "comparison": comparison,
            "decisions": decisions,
        }
    )


__all__ = [
    "PREPARE_STATUSES",
    "UNSUPPORTED_OPERATORS",
    "ChoiceError",
    "ChoiceQuestion",
    "ChoiceSubmit",
    "PrepareResult",
    "QueryResult",
    "QuerySessionState",
    "SemanticQuery",
    "abort_option",
    "merge_decision",
    "other_option",
    "with_choice_exits",
]


def field_constrained(node: FilterAtom | FilterGroup | None, field: str) -> bool:
    """A positive constraint must hold on every OR branch; NOT is not a period."""
    if isinstance(node, FilterAtom):
        return node.field.split(".")[-1] == field
    if isinstance(node, FilterGroup):
        checks = [field_constrained(arg, field) for arg in node.args]
        return all(checks) if node.kind == "OR" else any(checks) if node.kind == "AND" else False
    return False


def equality_value(node: FilterAtom | FilterGroup | None, field: str) -> Any:
    if isinstance(node, FilterAtom) and node.field.split(".")[-1] == field and node.op == "EQ":
        return node.value.value
    if isinstance(node, FilterGroup) and node.kind == "AND":
        values = [equality_value(arg, field) for arg in node.args]
        found = [value for value in values if value is not None]
        if found and all(value == found[0] for value in found):
            return found[0]
    return None


def conjuncts(node: FilterAtom | FilterGroup | None) -> list[FilterAtom | FilterGroup]:
    if node is None:
        return []
    if isinstance(node, FilterGroup) and node.kind == "AND":
        return [item for arg in node.args for item in conjuncts(arg)]
    return [node]


def without_field(
    node: FilterAtom | FilterGroup | None, field: str
) -> FilterAtom | FilterGroup | None:
    remaining = [
        item
        for item in conjuncts(node)
        if not (isinstance(item, FilterAtom) and item.field == field)
    ]
    if not remaining:
        return None
    return remaining[0] if len(remaining) == 1 else FilterGroup(kind="AND", args=tuple(remaining))


def conflicting_equalities(node: FilterAtom | FilterGroup | None) -> list[FilterAtom]:
    fields: dict[str, list[FilterAtom]] = {}
    for item in conjuncts(node):
        if isinstance(item, FilterAtom) and item.op == "EQ":
            group = fields.setdefault(item.field, [])
            if all(other.value != item.value for other in group):
                group.append(item)
    return next((items for items in fields.values() if len(items) > 1), [])

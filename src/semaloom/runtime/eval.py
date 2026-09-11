"""Typed expression evaluator. Decimal only; no eval/exec."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext
from typing import Literal

from semaloom.core.bundle import CompiledBundle
from semaloom.core.diagnostics import Diagnostic
from semaloom.core.expr import Expr
from semaloom.core.model import PolicyDef, RuleDef
from semaloom.core.results import Claim, Observation
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService

RoundingName = Literal["ROUND_HALF_UP", "ROUND_HALF_EVEN"]


class EvaluationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def select_policy(
    bundle: CompiledBundle,
    rule_id: str,
    *,
    period_from: str,
    period_to: str,
    dimensions: dict[str, str],
) -> PolicyDef:
    matches = [
        policy
        for policy in bundle.policies
        if policy.rule == rule_id and policy.dimensions.items() <= dimensions.items()
    ]
    covering = [
        policy
        for policy in matches
        if policy.interval.effective_from <= period_from
        and (policy.interval.effective_to is None or period_to <= policy.interval.effective_to)
    ]
    if period_from >= period_to:
        raise EvaluationError("INVALID_BINDINGS", "business period must be half-open and non-empty")
    # Crossing a policy boundary.
    straddling = [
        policy
        for policy in matches
        if policy.interval.effective_from < period_to
        and (policy.interval.effective_to is None or policy.interval.effective_to > period_from)
    ]
    if len({policy.id for policy in straddling}) > 1 and len(covering) != 1:
        raise EvaluationError("POLICY_PERIOD_SPLIT_REQUIRED", "period crosses policy versions")
    if len(covering) != 1:
        raise EvaluationError("NO_APPLICABLE_POLICY", "no policy covers the requested period")
    return covering[0]


def evaluate_rule(
    rule: RuleDef,
    observations: dict[str, Observation],
) -> tuple[Claim, tuple[Diagnostic, ...]]:
    missing_reasons: list[str] = []
    values: dict[str, Decimal] = {}
    diagnostics: list[Diagnostic] = []
    for spec in rule.inputs:
        obs = observations.get(spec.name)
        if obs is None or obs.kind == "MISSING":
            if spec.required:
                missing_reasons.append("MISSING_INPUT")
            continue
        if obs.kind == "NULL":
            missing_reasons.append("NULL_INPUT")
            continue
        if obs.kind in {"UNAVAILABLE", "FORBIDDEN"}:
            diagnostics.append(
                Diagnostic(code="PROVIDER_ERROR", path=spec.name, message=obs.reason or obs.kind)
            )
            missing_reasons.append("UNAVAILABLE")
            continue
        if obs.value is None:
            missing_reasons.append("MISSING_INPUT")
            continue
        values[spec.name] = _decimal(obs.value)
    if missing_reasons:
        truth: Literal["TRUE", "FALSE", "UNKNOWN"] = "UNKNOWN"
        return (
            Claim(
                claim_id=rule.claim or rule.id,
                evaluation_id=uuid.uuid4().hex,
                truth=truth,
                predicate_version=rule.version,
                reason_codes=tuple(dict.fromkeys(missing_reasons)),
            ),
            tuple(diagnostics),
        )
    try:
        result = _eval(rule.expression, values)
    except EvaluationError as exc:
        diagnostics.append(Diagnostic(code=exc.code, path=rule.id, message=exc.message))
        return (
            Claim(
                claim_id=rule.claim or rule.id,
                evaluation_id=uuid.uuid4().hex,
                truth="UNKNOWN",
                predicate_version=rule.version,
                reason_codes=("RULE_EVALUATION_ERROR",),
            ),
            tuple(diagnostics),
        )
    if isinstance(result, bool):
        truth = "TRUE" if result else "FALSE"
        return (
            Claim(
                claim_id=rule.claim or rule.id,
                evaluation_id=uuid.uuid4().hex,
                truth=truth,
                predicate_version=rule.version,
            ),
            tuple(diagnostics),
        )
    return (
        Claim(
            claim_id=rule.claim or rule.id,
            evaluation_id=uuid.uuid4().hex,
            truth="TRUE",
            predicate_version=rule.version,
            reason_codes=("NUMERIC_RESULT",),
        ),
        tuple(diagnostics),
    )


def evaluate_named_claim(
    bundle: CompiledBundle,
    query: QueryService,
    actor: RequestActor,
    *,
    claim_id: str,
    bindings: dict[str, str | int],
    period_from: str,
    period_to: str,
    dimensions: dict[str, str],
) -> tuple[Claim, tuple[Observation, ...], tuple[Diagnostic, ...], str]:
    rule = next(
        (item for item in bundle.rules if item.claim == claim_id or item.id == claim_id), None
    )
    if rule is None:
        raise EvaluationError("INVALID_REQUEST", f"unknown claim {claim_id}")
    policy = select_policy(
        bundle, rule.id, period_from=period_from, period_to=period_to, dimensions=dimensions
    )
    from semaloom.core.results import MetricSelect, ObjectSelect, QueryContext, QueryRequest

    selects: list[MetricSelect | ObjectSelect] = []
    for spec in rule.inputs:
        if spec.metric is not None:
            metric = next(item for item in bundle.metrics if item.id == spec.metric)
            metric_bindings = dict(bindings)
            if metric.perspective:
                metric_bindings.setdefault("perspective", metric.perspective)
            selects.append(MetricSelect(metric=spec.metric, bindings=metric_bindings))
            continue
        if spec.property is None or spec.object_type is None:
            raise EvaluationError("INVALID_DEFINITION", f"input {spec.name} has no source")
        object_type = next(item for item in bundle.object_types if item.id == spec.object_type)
        try:
            identity = {key: str(bindings[key]) for key in object_type.identity_keys}
        except KeyError as exc:
            raise EvaluationError(
                "INVALID_BINDINGS", f"missing identity binding {exc.args[0]}"
            ) from exc
        selects.append(
            ObjectSelect(
                object_type=spec.object_type,
                identity=identity,
                properties=(spec.property,),
            )
        )
    envelope = query.execute(
        QueryRequest(
            api_version="semaloom/v0.1",
            select=tuple(selects),
            context=QueryContext(business_period={"from": period_from, "to": period_to}),
        ),
        actor,
    )
    normalized = tuple(
        _property_value(spec.property, observation) if spec.property else observation
        for spec, observation in zip(rule.inputs, envelope.observations, strict=True)
    )
    observations = {spec.name: normalized[index] for index, spec in enumerate(rule.inputs)}
    claim, extra = evaluate_rule(rule, observations)
    claim = claim.model_copy(
        update={
            "context": {
                "policyId": policy.id,
                "businessFrom": period_from,
                "businessTo": period_to,
            },
            "evidence_refs": tuple(item.activity_id for item in envelope.source_activities),
        }
    )
    return claim, normalized, envelope.diagnostics + extra, envelope.release_digest


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise EvaluationError("RULE_EVALUATION_ERROR", "invalid decimal") from exc
    if not parsed.is_finite():
        raise EvaluationError("RULE_EVALUATION_ERROR", "non-finite decimal")
    return parsed


def _eval(expr: Expr, values: dict[str, Decimal]) -> Decimal | bool:
    op = expr["op"]
    if op == "decimal":
        return _decimal(str(expr["value"]))
    if op == "bool":
        return bool(expr["value"])
    if op == "ref":
        try:
            return values[str(expr["name"])]
        except KeyError as exc:
            raise EvaluationError("RULE_EVALUATION_ERROR", "unknown input reference") from exc
    if op == "not":
        value = _eval(expr["arg"], values)
        if not isinstance(value, bool):
            raise EvaluationError("RULE_EVALUATION_ERROR", "not requires boolean")
        return not value
    if op == "round":
        value = _eval(expr["value"], values)
        if not isinstance(value, Decimal):
            raise EvaluationError("RULE_EVALUATION_ERROR", "round requires decimal")
        mode = "ROUND_HALF_UP" if expr.get("mode") == "ROUND_HALF_UP" else "ROUND_HALF_EVEN"
        with localcontext() as ctx:
            ctx.prec = 28
            ctx.rounding = mode
            ctx.traps[DivisionByZero] = True
            ctx.traps[Overflow] = True
            quant = Decimal("1").scaleb(-int(expr["places"]))
            try:
                return value.quantize(quant)
            except InvalidOperation as exc:
                raise EvaluationError("RULE_EVALUATION_ERROR", "rounding overflow") from exc
    args = [_eval(item, values) for item in expr["args"]]
    if op in {"add", "sub", "mul", "div"}:
        numbers = []
        for item in args:
            if not isinstance(item, Decimal):
                raise EvaluationError("RULE_EVALUATION_ERROR", "arithmetic requires decimal")
            numbers.append(item)
        with localcontext() as ctx:
            ctx.prec = 28
            ctx.rounding = "ROUND_HALF_UP"
            ctx.traps[DivisionByZero] = True
            ctx.traps[Overflow] = True
            try:
                result = numbers[0]
                for item in numbers[1:]:
                    if op == "add":
                        result += item
                    elif op == "sub":
                        result -= item
                    elif op == "mul":
                        result *= item
                    else:
                        result /= item
                return result
            except (DivisionByZero, Overflow, InvalidOperation) as exc:
                raise EvaluationError("RULE_EVALUATION_ERROR", str(exc)) from exc
    bools: list[bool] = []
    decimals: list[Decimal] = []
    for item in args:
        if isinstance(item, bool):
            bools.append(item)
        elif isinstance(item, Decimal):
            decimals.append(item)
        else:
            raise EvaluationError("RULE_EVALUATION_ERROR", "unsupported operand")
    if op in {"and", "or"}:
        if len(bools) != len(args):
            raise EvaluationError("RULE_EVALUATION_ERROR", "boolean operation requires booleans")
        if op == "and":
            return all(bools)
        return any(bools)
    if op in {"eq", "ne"} and len(bools) == 2 and len(args) == 2:
        return bools[0] == bools[1] if op == "eq" else bools[0] != bools[1]
    if len(decimals) != 2 or len(args) != 2:
        raise EvaluationError("RULE_EVALUATION_ERROR", "comparison requires matching operands")
    left, right = decimals[0], decimals[1]
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "lt":
        return left < right
    if op == "le":
        return left <= right
    if op == "gt":
        return left > right
    if op == "ge":
        return left >= right
    raise EvaluationError("RULE_EVALUATION_ERROR", f"unknown op {op}")


def _property_value(property_id: str, observation: Observation) -> Observation:
    if observation.kind != "PRESENT" or observation.value is None:
        return observation
    try:
        values = json.loads(observation.value)
    except json.JSONDecodeError as exc:
        raise EvaluationError("PROVIDER_ERROR", "object provider returned invalid JSON") from exc
    if not isinstance(values, dict) or property_id not in values:
        return observation.model_copy(
            update={"kind": "MISSING", "value": None, "reason": "NO_FIELD"}
        )
    value = values[property_id]
    if value is None:
        return observation.model_copy(
            update={"kind": "NULL", "value": None, "reason": "NULL_INPUT"}
        )
    return observation.model_copy(update={"value": str(value)})

"""Typed expression evaluator. Decimal only; no eval/exec."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext
from typing import Any, Literal, cast

from semaloom.core.bundle import CompiledBundle
from semaloom.core.diagnostics import Diagnostic
from semaloom.core.expr import Expr, expression_unit
from semaloom.core.model import PolicyDef, RuleDef
from semaloom.core.provider import IdentityScalar
from semaloom.core.results import (
    Claim,
    EvidenceEnvelope,
    MetricSelect,
    Observation,
    QueryContext,
    SourceActivity,
)
from semaloom.core.values import Scalar, scalar_value
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.query import QueryService


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
    try:
        QueryContext(business_period={"from": period_from, "to": period_to})
    except ValueError as exc:
        raise EvaluationError("INVALID_BINDINGS", "invalid business period") from exc
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


def evaluate_rule_value(
    rule: RuleDef, observations: dict[str, Observation]
) -> tuple[Scalar | None, tuple[str, ...], tuple[Diagnostic, ...]]:
    reasons: list[str] = []
    values: dict[str, Scalar | None] = {}
    diagnostics: list[Diagnostic] = []
    for spec in rule.inputs:
        obs = observations.get(spec.name)
        values[spec.name] = None
        if (
            obs is None
            or obs.kind in {"MISSING", "NULL"}
            or (obs.kind == "PRESENT" and obs.value is None)
        ):
            if spec.required:
                reasons.append("NULL_INPUT" if obs and obs.kind == "NULL" else "MISSING_INPUT")
            continue
        if obs.kind in {"UNAVAILABLE", "FORBIDDEN"}:
            reasons.append("UNAVAILABLE")
            diagnostics.append(
                Diagnostic(code="PROVIDER_ERROR", path=spec.name, message=obs.reason or obs.kind)
            )
            continue
        try:
            values[spec.name] = scalar_value(obs.value or "", obs.value_type or "DECIMAL")
        except ValueError as exc:
            diagnostics.append(Diagnostic(code="TYPE_MISMATCH", path=spec.name, message=str(exc)))
            reasons.append("INVALID_INPUT")
    if reasons:
        return None, tuple(dict.fromkeys(reasons)), tuple(diagnostics)
    try:
        expression_unit(
            rule.expression,
            {
                spec.name: observations[spec.name].unit if spec.name in observations else None
                for spec in rule.inputs
            },
        )
    except ValueError as exc:
        diagnostics.append(Diagnostic(code="UNIT_MISMATCH", path=rule.id, message=str(exc)))
        return None, ("RULE_EVALUATION_ERROR",), tuple(diagnostics)
    try:
        result = _eval(rule.expression, values)
        return result, ("MISSING_INPUT",) if result is None else (), tuple(diagnostics)
    except EvaluationError as exc:
        diagnostics.append(Diagnostic(code=exc.code, path=rule.id, message=exc.message))
        return None, ("RULE_EVALUATION_ERROR",), tuple(diagnostics)


def evaluate_rule(
    rule: RuleDef, observations: dict[str, Observation]
) -> tuple[Claim, tuple[Diagnostic, ...]]:
    result, reasons, diagnostics = evaluate_rule_value(rule, observations)
    truth: Literal["TRUE", "FALSE", "UNKNOWN"] = "UNKNOWN"
    if isinstance(result, bool):
        truth = "TRUE" if result else "FALSE"
    elif result is not None:
        reasons = ("NON_BOOLEAN_CLAIM",)
        diagnostics += (
            Diagnostic(
                code="TYPE_MISMATCH", path=rule.id, message="Claim requires a boolean result"
            ),
        )
    return Claim(
        claim_id=rule.claim or rule.id,
        evaluation_id=uuid.uuid4().hex,
        truth=truth,
        predicate_version=rule.version,
        reason_codes=reasons,
    ), diagnostics


def evaluate_named_claim(
    bundle: CompiledBundle,
    query: QueryService,
    actor: RequestActor,
    *,
    claim_id: str,
    bindings: dict[str, IdentityScalar],
    period_from: str,
    period_to: str,
    dimensions: dict[str, str],
) -> tuple[Claim, tuple[Observation, ...], tuple[Diagnostic, ...], str]:
    claim, observations, diagnostics, digest, _ = evaluate_claim_with_evidence(
        bundle,
        query,
        actor,
        claim_id=claim_id,
        bindings=bindings,
        period_from=period_from,
        period_to=period_to,
        dimensions=dimensions,
    )
    return claim, observations, diagnostics, digest


def evaluate_claim_with_evidence(
    bundle: CompiledBundle,
    query: QueryService,
    actor: RequestActor,
    *,
    claim_id: str,
    bindings: dict[str, IdentityScalar],
    period_from: str,
    period_to: str,
    dimensions: dict[str, str],
) -> tuple[Claim, tuple[Observation, ...], tuple[Diagnostic, ...], str, tuple[SourceActivity, ...]]:
    rule = next((item for item in bundle.rules if item.claim == claim_id), None)
    if rule is None:
        raise EvaluationError("INVALID_REQUEST", f"unknown claim {claim_id}")
    policy = select_policy(
        bundle, rule.id, period_from=period_from, period_to=period_to, dimensions=dimensions
    )
    normalized, envelope = _rule_inputs(
        bundle, query, actor, rule, bindings, period_from, period_to
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
    return (
        claim,
        normalized,
        envelope.diagnostics + extra,
        envelope.release_digest,
        envelope.source_activities,
    )


def _rule_inputs(
    bundle: CompiledBundle,
    query: QueryService,
    actor: RequestActor,
    rule: RuleDef,
    bindings: dict[str, IdentityScalar],
    period_from: str,
    period_to: str,
) -> tuple[tuple[Observation, ...], EvidenceEnvelope]:
    from semaloom.core.results import MetricSelect, ObjectSelect, QueryContext, QueryRequest

    selects: list[MetricSelect | ObjectSelect] = []
    allowed_bindings = {"perspective"}
    for input_spec in rule.inputs:
        if input_spec.metric is not None:
            input_metric = next(item for item in bundle.metrics if item.id == input_spec.metric)
            allowed_bindings.update(input_metric.grain)
        elif input_spec.object_type is not None:
            input_object = next(
                item for item in bundle.object_types if item.id == input_spec.object_type
            )
            allowed_bindings.update(input_object.identity_keys)
    unknown_bindings = sorted(set(bindings) - allowed_bindings)
    if unknown_bindings:
        raise EvaluationError(
            "INVALID_BINDINGS",
            f"unsupported bindings: {', '.join(unknown_bindings)}",
        )
    for spec in rule.inputs:
        if spec.metric is not None:
            metric = next(item for item in bundle.metrics if item.id == spec.metric)
            metric_bindings = {
                key: value
                for key, value in bindings.items()
                if key in metric.grain or key == "perspective"
            }
            if metric.perspective:
                metric_bindings["perspective"] = metric.perspective
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
    typed_observations = []
    for spec, observation in zip(rule.inputs, normalized, strict=True):
        if spec.property and spec.object_type:
            obj = next(item for item in bundle.object_types if item.id == spec.object_type)
            prop = next(item for item in obj.properties if item.id == spec.property)
            observation = observation.model_copy(
                update={"value_type": prop.value_type, "unit": prop.unit}
            )
        typed_observations.append(observation)
    normalized = tuple(typed_observations)
    return normalized, envelope


def evaluate_derived_metric(
    query: QueryService, actor: RequestActor, selection: MetricSelect, context: QueryContext
) -> tuple[Observation, tuple[SourceActivity, ...], tuple[Diagnostic, ...]]:
    bundle = query.bundle
    rules = [rule for rule in bundle.rules if rule.output_metric == selection.metric]
    metric = next(m for m in bundle.metrics if m.id == selection.metric)
    if len(rules) != 1:
        return (
            Observation(kind="UNAVAILABLE", target=selection.metric, reason="AMBIGUOUS_RULE"),
            (),
            (),
        )
    rule = rules[0]
    period_from, period_to = (
        context.business_period.get("from", ""),
        context.business_period.get("to", ""),
    )
    try:
        if any(policy.rule == rule.id for policy in bundle.policies):
            select_policy(
                bundle,
                rule.id,
                period_from=period_from,
                period_to=period_to,
                dimensions=context.scope,
            )
        normalized, envelope = _rule_inputs(
            bundle, query, actor, rule, selection.bindings, period_from, period_to
        )
    except EvaluationError as exc:
        return (
            Observation(kind="UNAVAILABLE", target=selection.metric, reason=exc.code),
            (),
            (Diagnostic(code=exc.code, path=rule.id, message=exc.message),),
        )
    value, reasons, diagnostics = evaluate_rule_value(
        rule, {spec.name: obs for spec, obs in zip(rule.inputs, normalized, strict=True)}
    )
    diagnostics = envelope.diagnostics + diagnostics
    if isinstance(value, Decimal):
        try:
            scalar_value(str(value), metric.value_type or "DECIMAL")
        except ValueError:
            diagnostics += (
                Diagnostic(
                    code="TYPE_MISMATCH",
                    path=rule.id,
                    message="derived value does not match the metric type",
                ),
            )
            value = None
    if value is not None and not isinstance(value, Decimal):
        diagnostics += (
            Diagnostic(
                code="TYPE_MISMATCH", path=rule.id, message="Metric requires a numeric result"
            ),
        )
        value = None
    observation = Observation(
        kind="PRESENT" if value is not None else "UNAVAILABLE" if diagnostics else "NULL",
        target=metric.id,
        bindings=selection.bindings,
        value=str(value) if value is not None else None,
        value_type=metric.value_type,
        unit=metric.unit,
        rule_id=rule.id,
        reason=",".join(reasons) if value is None else None,
    )
    return observation, envelope.source_activities, diagnostics


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise EvaluationError("RULE_EVALUATION_ERROR", "invalid decimal") from exc
    if not parsed.is_finite():
        raise EvaluationError("RULE_EVALUATION_ERROR", "non-finite decimal")
    return parsed


def _eval(expr: Expr, values: dict[str, Scalar | None]) -> Scalar | None:
    op = expr["op"]
    if op == "decimal":
        return _decimal(str(expr["value"]))
    if op in {"string", "date", "datetime"}:
        try:
            return scalar_value(str(expr["value"]), str(op).upper())
        except ValueError as exc:
            raise EvaluationError("RULE_EVALUATION_ERROR", str(exc)) from exc
    if op == "bool":
        return bool(expr["value"])
    if op == "ref":
        try:
            return values[str(expr["name"])]
        except KeyError as exc:
            raise EvaluationError("RULE_EVALUATION_ERROR", "unknown input reference") from exc
    if op == "not":
        value = _eval(expr["arg"], values)
        if value is None:
            return None
        if not isinstance(value, bool):
            raise EvaluationError("RULE_EVALUATION_ERROR", "not requires boolean")
        return not value
    if op == "round":
        value = _eval(expr["value"], values)
        if value is None:
            return None
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
    if op not in {"and", "or"} and any(item is None for item in args):
        return None
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
    if op in {"and", "or"}:
        if not all(isinstance(item, bool) or item is None for item in args):
            raise EvaluationError("RULE_EVALUATION_ERROR", "boolean operation requires booleans")
        if op == "and" and any(item is False for item in args):
            return False
        if op == "or" and any(item is True for item in args):
            return True
        if any(item is None for item in args):
            return None
        return all(args) if op == "and" else any(args)
    if len(args) != 2 or type(args[0]) is not type(args[1]):
        raise EvaluationError("RULE_EVALUATION_ERROR", "comparison requires matching operands")
    if op not in {"eq", "ne"} and isinstance(args[0], bool):
        raise EvaluationError("RULE_EVALUATION_ERROR", "booleans are not ordered")
    left, right = cast(Any, args[0]), cast(Any, args[1])
    if op == "eq":
        return bool(left == right)
    if op == "ne":
        return bool(left != right)
    if op == "lt":
        return bool(left < right)
    if op == "le":
        return bool(left <= right)
    if op == "gt":
        return bool(left > right)
    if op == "ge":
        return bool(left >= right)
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

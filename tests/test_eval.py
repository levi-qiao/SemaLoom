from __future__ import annotations

from decimal import Decimal

from semaloom.core.expr import parse_expr
from semaloom.core.model import RuleDef
from semaloom.core.results import Observation
from semaloom.runtime.eval import evaluate_rule


def test_decimal_sum_is_exact_not_float() -> None:
    rule = RuleDef.from_document(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Rule",
            "id": "tax.demoSum",
            "version": "1.0.0",
            "claim": "tax.demoSum",
            "inputs": [
                {"name": "left", "metric": "tax.reportedIncome", "required": True},
                {"name": "right", "metric": "tax.auditIncome", "required": True},
            ],
            "expression": {
                "op": "eq",
                "args": [
                    {
                        "op": "add",
                        "args": [{"op": "ref", "name": "left"}, {"op": "ref", "name": "right"}],
                    },
                    {"op": "decimal", "value": "0.3"},
                ],
            },
        }
    )
    claim, diagnostics = evaluate_rule(
        rule,
        {
            "left": Observation(kind="PRESENT", target="left", value="0.1"),
            "right": Observation(kind="PRESENT", target="right", value="0.2"),
        },
    )
    assert diagnostics == ()
    assert claim.truth == "TRUE"
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")


def test_missing_required_input_is_unknown() -> None:
    expr = parse_expr(
        {"op": "eq", "args": [{"op": "ref", "name": "left"}, {"op": "decimal", "value": "1"}]}
    )
    rule = RuleDef.from_document(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Rule",
            "id": "tax.needInput",
            "version": "1.0.0",
            "claim": "tax.needInput",
            "inputs": [{"name": "left", "metric": "tax.reportedIncome", "required": True}],
            "expression": expr,
        }
    )
    claim, _ = evaluate_rule(rule, {"left": Observation(kind="MISSING", target="left")})
    assert claim.truth == "UNKNOWN"
    assert "MISSING_INPUT" in claim.reason_codes


def test_unavailable_is_not_false() -> None:
    expr = parse_expr(
        {"op": "eq", "args": [{"op": "ref", "name": "left"}, {"op": "decimal", "value": "1"}]}
    )
    rule = RuleDef.from_document(
        {
            "apiVersion": "semaloom/v0.1",
            "kind": "Rule",
            "id": "tax.needSource",
            "version": "1.0.0",
            "claim": "tax.needSource",
            "inputs": [{"name": "left", "metric": "tax.reportedIncome", "required": True}],
            "expression": expr,
        }
    )
    claim, diagnostics = evaluate_rule(
        rule, {"left": Observation(kind="UNAVAILABLE", target="left", reason="timeout")}
    )
    assert claim.truth == "UNKNOWN"
    assert diagnostics
    assert diagnostics[0].code == "PROVIDER_ERROR"

"""
Calculator tool — safe arithmetic evaluation for exact numeric answers.

Offline, deterministic, bounded (Data tools slice).

Design contract:
- NO eval()/exec() — a whitelist AST walker evaluates only the nodes the
  calculator may need (numbers, arithmetic operators, a small set of math
  functions, pi/e/tau). Everything else is rejected with a clear message.
- BOUNDED by construction: operand-count cap, nesting-depth cap, and a
  result-length cap — no expression can produce unbounded work or output.
- GRACEFUL: division by zero, unknown names, malformed expressions all
  return a short explanatory string — never raises.
- Deterministic: pure Python, no I/O, no network, no randomness.
"""

from __future__ import annotations

import ast
import logging
import math
import operator
import re

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# ── Whitelists ────────────────────────────────────────────────────────────────

_BIN_OPS: dict[type[ast.operator], object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.unaryop], object] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_MATH_FUNCS: dict[str, object] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "pow": pow,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "trunc": math.trunc,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}

_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}

_MAX_OPERANDS: int = 200  # total scalar nodes allowed in one expression
_MAX_DEPTH: int = 12  # nesting depth of the AST
_MAX_RESULT_CHARS: int = 400


class _CalculatorError(ValueError):
    """Raised for any expression the calculator refuses to evaluate."""


class _SafeEvaluator(ast.NodeVisitor):
    """Whitelist AST walker — only the node types below can be evaluated."""

    def __init__(self) -> None:
        self._node_count = 0
        self._depth = 0

    def visit(self, node: ast.AST) -> object:  # noqa: D102 — depth accounting
        self._depth += 1
        if self._depth > _MAX_DEPTH:
            raise _CalculatorError(f"expression too deeply nested (>{_MAX_DEPTH} levels)")
        try:
            return super().visit(node)
        finally:
            self._depth -= 1

    def _bump(self) -> None:
        self._node_count += 1
        if self._node_count > _MAX_OPERANDS:
            raise _CalculatorError(f"expression too complex (>{_MAX_OPERANDS} operands)")

    def visit_Constant(self, node: ast.Constant) -> object:  # noqa: D102
        self._bump()
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise _CalculatorError("only numeric constants are allowed")

    def visit_Expr(self, node: ast.Expr) -> object:  # noqa: D102
        return self.visit(node.value)

    def visit_Expression(self, node: ast.Expression) -> object:  # noqa: D102
        # The root node of an eval-mode parse.
        return self.visit(node.body)

    def visit_BinOp(self, node: ast.BinOp) -> object:  # noqa: D102
        self._bump()
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise _CalculatorError("unsupported operator")
        left = self.visit(node.left)
        right = self.visit(node.right)
        # Guard against huge-int DoS: 2**1000000 computes a 300K-digit int
        # whose str() conversion is O(n^2) — cap the exponent first.
        if type(node.op) is ast.Pow and isinstance(right, (int, float)) and abs(right) > 10000:
            raise _CalculatorError("exponent too large (max 10000)")
        try:
            return op(left, right)
        except ZeroDivisionError:
            raise _CalculatorError("division by zero") from None
        except OverflowError:
            raise _CalculatorError("result too large") from None

    def visit_UnaryOp(self, node: ast.UnaryOp) -> object:  # noqa: D102
        self._bump()
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise _CalculatorError("unsupported unary operator")
        try:
            return op(self.visit(node.operand))
        except OverflowError:
            raise _CalculatorError("result too large") from None

    def visit_Call(self, node: ast.Call) -> object:  # noqa: D102
        self._bump()
        if not isinstance(node.func, ast.Name) or node.func.id not in _MATH_FUNCS:
            allowed = "abs/round/min/max/pow/sqrt/floor/ceil/trunc/exp/log/sin/cos/tan"
            raise _CalculatorError(f"unsupported function — only {allowed}")
        func = _MATH_FUNCS[node.func.id]
        args = [self.visit(a) for a in node.args]
        kwargs: dict[str, object] = {}
        for kw in node.keywords:
            if kw.arg is None:
                # **unpacking is not allowed — reject it explicitly so no
                # expression can hide an unvisited subtree behind a **{...}.
                raise _CalculatorError("unsupported syntax: ** unpacking")
            kwargs[kw.arg] = self.visit(kw.value)
        try:
            return func(*args, **kwargs)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError) as exc:
            raise _CalculatorError(f"function error: {exc}") from None

    def visit_Name(self, node: ast.Name) -> object:  # noqa: D102
        self._bump()
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise _CalculatorError(f"unknown name '{node.id}' — only pi, e, tau are allowed")

    def generic_visit(self, node: ast.AST) -> object:  # noqa: D102
        raise _CalculatorError(f"unsupported syntax: {type(node).__name__}")


# ── Normalization & formatting ────────────────────────────────────────────────


def _normalize(expression: str) -> str:
    """Turn common natural-language math notation into Python syntax."""
    expr = expression.strip()
    for src, dst in (
        ("×", "*"),
        ("÷", "/"),
        ("−", "-"),
        ("π", "pi"),
    ):
        expr = expr.replace(src, dst)
    # "15% of 80" → "(15/100)*80". The trailing-percent case must NOT
    # match the modulo operator: "17 % 5" keeps its % (negative lookahead
    # for a following number).
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%\s+of\s+", r"(\1/100)*", expr)
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%(?!\s*\d)", r"(\1/100)", expr)
    return expr.strip()


def _format_result(result: object, expression: str) -> str:
    if isinstance(result, float):
        # Squash floating-point noise (0.30000000000000004 → 0.3).
        if abs(result) < 1e12:
            rounded = round(result, 10)
            result = int(rounded) if rounded == int(rounded) else rounded
    text = str(result)
    if len(text) > _MAX_RESULT_CHARS:
        text = text[:_MAX_RESULT_CHARS] + "…"
    return f"{expression} = {text}"


def _calculate(expression: str) -> str:
    """Evaluate a safe arithmetic expression → user-facing string, never raises."""
    expr = _normalize(expression)
    if not expr:
        return "Error: empty expression — pass something like '2 + 2' or '15% of 80'."
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        return f"Error: could not parse expression — {exc}"
    try:
        result = _SafeEvaluator().visit(tree)
    except _CalculatorError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001 — last-resort: never crash the loop
        logger.error("[calculator] evaluation failed: %s", exc)
        return f"Error: evaluation failed — {exc}"
    return _format_result(result, expr)


# ── Tool registration ─────────────────────────────────────────────────────────


async def calculator(message: str) -> ToolResult:
    """CALCULATE dispatch — safe arithmetic evaluation."""
    try:
        content = _calculate(message)
        return ToolResult(
            content=content,
            risk=RiskLevel.LOW,
            source="calculator",
            metadata={"offline": True},
        )
    except Exception as exc:  # noqa: BLE001 — last-resort: never crash the loop
        logger.error("[calculator] error: %s", exc)
        return ToolResult(
            content=f"Calculator error: {exc}",
            risk=RiskLevel.LOW,
            source="calculator",
        )


register_tool(
    Intent.CALCULATE,
    calculator,
    description=(
        "Evaluate a safe arithmetic expression exactly (no shell needed): numbers, "
        "+ - * / // % **, parentheses, unary minus, constants pi/e/tau, and functions "
        "abs/round/min/max/pow/sqrt/floor/ceil/trunc/exp/log/sin/cos/tan. Understands "
        "'15% of 80'. Offline, deterministic, bounded output. Use for precise numeric "
        "answers — e.g. percentages, unit conversions, formula evaluation."
    ),
    cost=0.0,
    latency_ms=5,
    parallelizable=True,
)

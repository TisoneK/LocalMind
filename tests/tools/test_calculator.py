"""Tests for the safe calculator tool (B-2026-07-31-10, Session 131)."""

import asyncio

import pytest
from core.models import Intent
from tools import dispatch
from tools.calculator import _calculate

# ── Basic arithmetic ──────────────────────────────────────────────────────────


def test_basic_addition():
    assert _calculate("2 + 2") == "2 + 2 = 4"


def test_precedence():
    assert _calculate("2 + 3 * 4") == "2 + 3 * 4 = 14"


def test_parentheses():
    assert _calculate("(2 + 3) * 4") == "(2 + 3) * 4 = 20"


def test_unary_minus():
    assert _calculate("-5 + 3") == "-5 + 3 = -2"


def test_floor_div_and_mod():
    assert _calculate("17 // 5") == "17 // 5 = 3"
    assert _calculate("17 % 5") == "17 % 5 = 2"


def test_power():
    assert _calculate("2 ** 10") == "2 ** 10 = 1024"


# ── Natural-language normalization ────────────────────────────────────────────


def test_percent_of():
    assert _calculate("15% of 80") == "(15/100)*80 = 12"


def test_trailing_percent():
    assert _calculate("50%") == "(50/100) = 0.5"


def test_unicode_operators():
    assert _calculate("6 × 7") == "6 * 7 = 42"
    assert _calculate("10 ÷ 4") == "10 / 4 = 2.5"


# ── Functions and constants ───────────────────────────────────────────────────


def test_math_functions():
    assert _calculate("sqrt(144) + 1") == "sqrt(144) + 1 = 13"
    assert _calculate("min(3, 7, 2)") == "min(3, 7, 2) = 2"
    assert _calculate("abs(-9)") == "abs(-9) = 9"


def test_constants():
    assert _calculate("pi * 2").startswith("pi * 2 = 6.2831853072")
    assert _calculate("2 * pi") == "2 * pi = 6.2831853072"


def test_float_noise_squashed():
    # 0.1 + 0.2 == 0.30000000000000004 in IEEE754 — must display as 0.3
    assert _calculate("0.1 + 0.2") == "0.1 + 0.2 = 0.3"


# ── Safety: reject everything dangerous ───────────────────────────────────────


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",
        "open('/etc/passwd')",
        "lambda x: x",
        "[1, 2, 3]",
        "{'a': 1}",
        "'string'",
        "True + 1",
        "a.b",
        "os.getcwd()",
        "1; 2",
        "print(1)",
        "round(1.5, **{'ndigits': 0})",  # ** unpacking must be rejected
        "2 ** 1000000",  # huge-int DoS guard
    ],
)
def test_rejects_dangerous_expressions(expr):
    result = _calculate(expr)
    assert result.startswith("Error:"), f"expected rejection for {expr!r}, got {result!r}"


def test_rejects_division_by_zero():
    assert "division by zero" in _calculate("10 / 0")
    assert "division by zero" in _calculate("1 // 0")


def test_rejects_unknown_names():
    assert "unknown name" in _calculate("x + 1")


def test_rejects_unknown_function():
    assert "unsupported function" in _calculate("evil(1)")


def test_empty_expression():
    assert "empty expression" in _calculate("   ")


def test_deep_nesting_bounded():
    expr = "(" * 100 + "1" + ")" * 100
    result = _calculate(expr)
    assert result.startswith("Error:") or "=" in result  # never hangs/raises


def test_operand_count_bounded():
    expr = "+".join(["1"] * 500)
    result = _calculate(expr)
    assert result.startswith("Error:") or "= 500" in result  # never hangs/raises


# ── Dispatch round-trip (registration) ────────────────────────────────────────


def test_dispatch_calculator_registered():
    result = asyncio.run(dispatch(Intent.CALCULATE, "2 + 2"))
    assert result is not None
    assert result.content == "2 + 2 = 4"
    assert result.source == "calculator"

"""The iteration cap is a failsafe for a FAILING loop, not a
penalty on a long task whose tools keep succeeding.

`_iteration_budget_extendable(trace)` decides whether the loop may continue
past the base cap: only when the most recent tool-executing step SUCCEEDED.
The base cap and hard ceiling are both fixed, so the loop can never run away —
these tests pin the predicate that gates the extension.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.loop import (
    _DESCRIBE_TOOL_CREDIT_CAP,
    _ITER_ABSOLUTE_CEILING,
    _base_cap_reached,
    _iteration_budget_extendable,
)


@dataclass
class _Step:
    tool_name: str = ""
    tool_failed: bool = False


class _Trace:
    def __init__(self, steps):
        self.steps = steps


def test_extends_when_last_tool_succeeded() -> None:
    trace = _Trace([_Step("shell", False), _Step("shell", False)])
    assert _iteration_budget_extendable(trace) is True


def test_no_extend_when_last_tool_failed() -> None:
    trace = _Trace([_Step("shell", False), _Step("shell", True)])
    assert _iteration_budget_extendable(trace) is False


def test_last_tool_step_decides_ignoring_tool_less_reasoning() -> None:
    # A tool-less reasoning step after a successful tool must not flip the
    # verdict — we look at the last step that actually ran a tool.
    trace = _Trace([_Step("sysinfo", False), _Step("", False)])
    assert _iteration_budget_extendable(trace) is True


def test_no_extend_when_no_tool_ever_ran() -> None:
    trace = _Trace([_Step("", False), _Step("", False)])
    assert _iteration_budget_extendable(trace) is False
    assert _iteration_budget_extendable(_Trace([])) is False


def test_recent_failure_after_earlier_success_does_not_extend() -> None:
    trace = _Trace([_Step("shell", False), _Step("shell", False), _Step("web_search", True)])
    assert _iteration_budget_extendable(trace) is False


def test_absolute_ceiling_is_a_high_finite_runaway_guard() -> None:
    # A fixed, high ceiling: high enough that wall-clock binds first for a long
    # succeeding task, finite so the loop can never truly run away.
    assert 32 <= _ITER_ABSOLUTE_CEILING <= 1000


# ── B-2026-08-30-2: describe_tool schema-loading is refunded from the cap ─────


def test_no_credit_reaches_cap_normally() -> None:
    # With zero on-demand tools loaded, the base cap behaves exactly as before.
    assert _base_cap_reached(iteration=6, loaded_tool_count=0, effective_max_iter=6) is True
    assert _base_cap_reached(iteration=5, loaded_tool_count=0, effective_max_iter=6) is False


def test_describe_tool_load_refunds_an_iteration() -> None:
    # The exact reported scenario: cap 6, but 2 tools (browse + web_fetch) were
    # loaded via describe_tool. Those 2 iterations are overhead, so at iter 6 the
    # ACTION count is 4 — the task must NOT be cut off.
    assert _base_cap_reached(iteration=6, loaded_tool_count=2, effective_max_iter=6) is False
    # It only trips once real action iterations reach the cap (6 + 2 credits = 8).
    assert _base_cap_reached(iteration=8, loaded_tool_count=2, effective_max_iter=6) is True


def test_credit_is_bounded() -> None:
    # A describe_tool spam loop cannot buy unlimited budget — credit is capped,
    # so the failsafe (and wall-clock) still terminate the run.
    huge = _DESCRIBE_TOOL_CREDIT_CAP + 50
    assert _base_cap_reached(
        iteration=_DESCRIBE_TOOL_CREDIT_CAP + 6, loaded_tool_count=huge, effective_max_iter=6
    ) is True


def test_negative_count_is_safe() -> None:
    assert _base_cap_reached(iteration=6, loaded_tool_count=-3, effective_max_iter=6) is True

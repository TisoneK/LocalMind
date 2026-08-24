"""B-2026-08-24-2: the iteration cap is a failsafe for a FAILING loop, not a
penalty on a long task whose tools keep succeeding.

`_iteration_budget_extendable(trace)` decides whether the loop may continue
past the base cap: only when the most recent tool-executing step SUCCEEDED.
The base cap and hard ceiling are both fixed, so the loop can never run away —
these tests pin the predicate that gates the extension.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.loop import _ITER_ABSOLUTE_CEILING, _iteration_budget_extendable


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

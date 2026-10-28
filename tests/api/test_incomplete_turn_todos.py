"""Don't auto-complete plan todos when a turn is cut short.

`_finalize_plan_todos` flips remaining plan todos to "completed" at turn end,
UNLESS the turn didn't finish its work. Previously "didn't finish" only meant an
honest stop, so a rate-limit / wall-clock / iteration-limit cutoff still marked
every todo done — a false 100% (live: a rate-limited turn created 1 of 3 files
yet showed all todos complete). `_turn_did_not_finish` now covers every
cut-short ending.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from api.routes.chat import _turn_did_not_finish


@dataclass
class _Evt:
    type: str
    data: dict = field(default_factory=dict)


@pytest.mark.parametrize(
    "evt",
    [
        _Evt("agent_loop_gate_honest_stop"),
        _Evt("agent_loop_failure", {"failure_type": "iteration_cap"}),
        _Evt("agent_loop_wall_clock_cap"),
        _Evt("agent_loop_degraded", {"provider_error_code": "rate_limit"}),
        _Evt("agent_loop_error", {"error": "payment_required"}),
        _Evt("agent_loop_done", {"hit_limit": True}),
    ],
)
def test_cut_short_endings_block_auto_complete(evt: _Evt) -> None:
    assert _turn_did_not_finish([_Evt("agent_loop_start"), evt]) is True


def test_clean_completion_allows_auto_complete() -> None:
    history = [
        _Evt("agent_loop_start"),
        _Evt("tool_call", {"tool": "file_write"}),
        _Evt("agent_loop_done", {"iterations": 3}),  # no hit_limit
    ]
    assert _turn_did_not_finish(history) is False


def test_agent_loop_done_without_hit_limit_is_not_cut_short() -> None:
    assert _turn_did_not_finish([_Evt("agent_loop_done", {"hit_limit": False})]) is False
    assert _turn_did_not_finish([_Evt("agent_loop_done", {})]) is False

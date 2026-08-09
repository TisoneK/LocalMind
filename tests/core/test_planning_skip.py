'''Session 114 regression tests - planning-skip decision.

v0.11 skipped the agent planning phase for ALL intents when the dispatcher
was highly confident (>= 0.7). That left tool-heavy intents without a
translate-before-dispatch step - Session 113: the model passed the raw
user sentence as a shell command. Planning is now kept for compound-
capable intents (SHELL, CODE_EXEC, FILE_WRITE, FILE_EDIT).
'''

from __future__ import annotations

from core.engine._pipeline import _should_skip_planning
from core.models import Intent


def test_tool_heavy_intents_keep_planning_at_high_confidence():
    assert _should_skip_planning(Intent.SHELL, 0.9) is False
    assert _should_skip_planning(Intent.CODE_EXEC, 0.8) is False
    assert _should_skip_planning(Intent.FILE_WRITE, 0.75) is False
    assert _should_skip_planning(Intent.FILE_EDIT, 0.95) is False


def test_simple_intents_still_skip_planning():
    assert _should_skip_planning(Intent.CHAT, 0.9) is True
    assert _should_skip_planning(Intent.WEB_SEARCH, 0.85) is True
    assert _should_skip_planning(Intent.WEB_FETCH, 0.9) is True
    assert _should_skip_planning(Intent.MEMORY_OP, 0.9) is True
    assert _should_skip_planning(Intent.FILE_TASK, 0.9) is True
    assert _should_skip_planning(Intent.SYSINFO, 0.95) is True


def test_low_confidence_never_skips_planning():
    assert _should_skip_planning(Intent.SHELL, 0.5) is False
    assert _should_skip_planning(Intent.CHAT, 0.4) is False
    assert _should_skip_planning(Intent.SHELL, 0.69) is False


def test_threshold_boundary_at_exactly_0_7():
    # Pin the inclusive '>=' threshold: 0.7 keeps planning for tool-heavy
    # intents and skips it for simple ones.
    assert _should_skip_planning(Intent.SHELL, 0.7) is False
    assert _should_skip_planning(Intent.CHAT, 0.7) is True
    assert _should_skip_planning(Intent.SHELL, 0.699) is False

'''ADR-22 (Session 184) regression tests — Agent-First Routing.

The `_should_skip_planning` function now ALWAYS returns False — the agent
ALWAYS plans for AGENT_INTENTS, regardless of dispatcher confidence. The
dispatcher's output becomes a routing HINT the agent evaluates during its
own planning call, not a directive that bypasses planning.

Previous behavior (Sessions 114-183): planning was skipped when dispatcher
confidence ≥0.7 AND the intent was not in _PLAN_REQUIRED_INTENTS. The
agent's first LLM call was a tool-execution call, not a reasoning call —
the dispatcher pre-decided. The user's diagnosis ("the agent should decide
to call tools, not intent") prompted ADR-22.
'''

from __future__ import annotations

from core.engine._pipeline import _should_skip_planning
from core.models import Intent


def test_always_returns_false_for_tool_heavy_intents():
    """Planning never skips for tool-heavy intents, regardless of confidence."""
    assert _should_skip_planning(Intent.SHELL, 0.9) is False
    assert _should_skip_planning(Intent.CODE_EXEC, 0.8) is False
    assert _should_skip_planning(Intent.FILE_WRITE, 0.75) is False
    assert _should_skip_planning(Intent.FILE_EDIT, 0.95) is False
    assert _should_skip_planning(Intent.GIT, 0.99) is False


def test_always_returns_false_for_other_agent_intents():
    """ADR-22: ALL AGENT_INTENTS plan, not just the original 5. The agent
    reasons about every tool-capable request, not just the tool-heavy ones."""
    assert _should_skip_planning(Intent.WEB_SEARCH, 0.85) is False
    assert _should_skip_planning(Intent.WEB_FETCH, 0.9) is False
    assert _should_skip_planning(Intent.MEMORY_OP, 0.9) is False
    assert _should_skip_planning(Intent.FILE_TASK, 0.9) is False
    assert _should_skip_planning(Intent.FIND_PATH, 0.95) is False
    assert _should_skip_planning(Intent.OBSERVE, 0.95) is False
    assert _should_skip_planning(Intent.CALCULATE, 0.95) is False


def test_low_confidence_never_skips_planning():
    """Below the old 0.7 threshold — planning still runs (unchanged)."""
    assert _should_skip_planning(Intent.SHELL, 0.5) is False
    assert _should_skip_planning(Intent.CHAT, 0.4) is False
    assert _should_skip_planning(Intent.SHELL, 0.69) is False


def test_high_confidence_never_skips_planning():
    """ADR-22: high confidence NO LONGER skips planning. The agent always plans."""
    assert _should_skip_planning(Intent.SHELL, 0.7) is False
    assert _should_skip_planning(Intent.SHELL, 0.95) is False
    assert _should_skip_planning(Intent.FILE_WRITE, 0.99) is False


def test_chat_intent_returns_false_but_does_not_reach_agent_loop():
    """CHAT is not in AGENT_INTENTS, so it never reaches the agent loop's
    planning phase anyway. _should_skip_planning(CHAT, ...) returns False
    under ADR-22 but the value is never used — CHAT goes to the trivial
    fast-path or the dispatcher's direct stream."""
    # Documenting the behavior — CHAT isn't a planning candidate.
    assert _should_skip_planning(Intent.CHAT, 0.9) is False
    assert _should_skip_planning(Intent.CHAT, 0.7) is False

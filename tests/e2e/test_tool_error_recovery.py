"""
General tool-error recovery (B-2026-08-18-9, root fix — spec §17/§28).

When ANY tool fails, the loop no longer just surfaces the raw
"[Tool 'X' returned error_type='...']" and leaves recovery to the model (which a
weak model can't do → the turn dead-ended in empty_response). Every tool error
now carries a concrete, model-agnostic `[RECOVERY]` next step keyed on its error
CLASS. This is the general path the per-tool patches (code_exec→shell, …) were
approximating.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.agent.loop import AgentLoop, tool_error_recovery_directive
from core.models import Intent, RiskLevel, StreamChunk, ToolResult


# ── unit: every error class → a concrete, non-empty directive ────────────────


def test_permission_class_says_do_not_retry_and_no_false_success():
    d = tool_error_recovery_directive("shell", "permission").lower()
    assert "not permitted" in d or "not available" in d
    assert "different" in d
    assert "claim success" in d  # must forbid claiming false success


def test_input_class_says_correct_input_or_different_tool():
    d = tool_error_recovery_directive("code_exec", "invalid_input").lower()
    assert "corrected input" in d
    assert "tool that actually fits" in d
    assert "do not repeat" in d


def test_noresult_class_forbids_inventing():
    d = tool_error_recovery_directive("web_search", "not_found").lower()
    assert "different query" in d or "different" in d
    assert "do not invent" in d


def test_transient_class_allows_one_retry():
    d = tool_error_recovery_directive("web_fetch", "timeout").lower()
    assert "retry once" in d


def test_hard_limit_says_stop_and_answer():
    d = tool_error_recovery_directive("shell", "wall_clock_cap").lower()
    assert "stop calling tools" in d


@pytest.mark.parametrize("et", ["git_error", "internal_error", "", "totally_unknown"])
def test_unknown_errors_still_get_an_actionable_directive(et):
    d = tool_error_recovery_directive("shell", et)
    assert d and "honestly" in d.lower()  # falls back to a real next step + honesty


# ── e2e: the [RECOVERY] line reaches the model after a tool error ────────────


@pytest.mark.asyncio
async def test_recovery_directive_reaches_the_model_after_a_tool_error():
    loop = AgentLoop(adapter=MagicMock())
    seen: dict = {}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        from adapters.ollama import ToolCallResult

        seen.setdefault("calls", []).append([dict(m) for m in messages])
        if len(seen["calls"]) == 1:
            return ToolCallResult(tool_name="shell", tool_args={"command": "cat /nope"}, raw_content="")

        async def _stream():
            yield StreamChunk(text="Done.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def empty_chat(messages, temperature=0.4):
        return
        yield

    # The tool FAILS with a recoverable error class.
    failed = (
        ToolResult(content="permission denied", risk=RiskLevel.LOW, source="shell",
                   success=False, error_type="invalid_input"),
        True,
        0,
    )
    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = empty_chat

    with patch("core.agent.loop.dispatch_with_retry", return_value=failed), \
         patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        async for _ in loop.run(
            messages=[{"role": "user", "content": "run a command"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
        ):
            pass

    # The 2nd model call must have seen the error AND a concrete recovery step.
    assert len(seen["calls"]) >= 2
    iter2 = " ".join(str(m.get("content", "")) for m in seen["calls"][1])
    assert "error_type" in iter2  # the raw error is still surfaced
    assert "[RECOVERY]" in iter2  # …plus the actionable next step
    assert "corrected input" in iter2.lower() or "tool that actually fits" in iter2.lower()

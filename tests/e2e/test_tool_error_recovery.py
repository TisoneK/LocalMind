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
from core.agent.tool_dispatch import dispatch_with_retry
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


# ── S422: cloud-file + unsupported-format classes ────────────────────────────
# Live evidence: an unhydrated OneDrive placeholder failed every reader, and a
# .pub under the generic directive burned 10 code_exec calls on hand-parsing.
# Both directives must forbid reader improvisation, not suggest "another tool".

def test_cloudfile_class_forbids_reader_improvisation():
    d = tool_error_recovery_directive("file_task", "cloud_file_unavailable").lower()
    assert "cloud" in d
    assert "do not" in d and ("zipfile" in d or "code_exec" in d)
    assert "never fabricate" in d


def test_unsupported_class_says_stop_and_convert():
    d = tool_error_recovery_directive("file_task", "unsupported_format").lower()
    assert "no other tool" in d
    assert "do not" in d and ("zipfile" in d or "code_exec" in d or "shell" in d)
    assert "re-save" in d or "conversion" in d
    assert "never fabricate" in d


@pytest.mark.parametrize("et", ["git_error", "internal_error", "", "totally_unknown"])
def test_unknown_errors_still_get_an_actionable_directive(et):
    d = tool_error_recovery_directive("shell", et)
    assert d and "honestly" in d.lower()  # falls back to a real next step + honesty


# ── dispatch contract: structured failures remain failures ───────────────────


@pytest.mark.asyncio
async def test_dispatch_marks_structured_tool_failure_for_the_loop(monkeypatch):
    """A tool returning success=False must drive the loop's failed branch.

    Before this contract fix, dispatch_with_retry returned failed=False for
    structured failures, so the loop marked the action done, ran Thinker on the
    error output, and skipped failure-memory/recovery guards.
    """
    failed_result = ToolResult(
        content="Command failed: missing path",
        source="shell",
        success=False,
        error_type="command_failed",
    )

    async def fake_dispatch(*args, **kwargs):
        return failed_result

    monkeypatch.setattr("core.agent.tool_dispatch.dispatch", fake_dispatch)
    result, failed, retries = await dispatch_with_retry(Intent.SHELL, "ls /missing")

    assert result is failed_result
    assert failed is True
    assert retries == 0


# ── e2e: the [RECOVERY] line reaches the model after a tool error ────────────


@pytest.mark.asyncio
async def test_loop_treats_structured_failure_as_failed_and_skips_thinker():
    """The failed signal reaches the loop, not just the recovery text."""
    from adapters.ollama import ToolCallResult
    from core.obs import ObsCollector

    loop = AgentLoop(adapter=MagicMock())
    obs = ObsCollector()
    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        if seen["calls"] == 1:
            return ToolCallResult(tool_name="shell", tool_args={"command": "ls /missing"})

        async def _stream():
            yield StreamChunk(text="I recovered honestly.", done=True)

        return _stream()

    async def fake_dispatch(*args, **kwargs):
        return (
            ToolResult(
                content="Command failed: missing path",
                source="shell",
                success=False,
                error_type="command_failed",
            ),
            True,
            0,
        )

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = lambda *args, **kwargs: iter(())
    adapter.thinking_enabled = True

    with patch("core.agent.loop.dispatch_with_retry", fake_dispatch), patch(
        "core.agent.loop._filter_tool_injection", side_effect=lambda value: value
    ), patch("core.agent.loop._filter_system_leaks", side_effect=lambda value: value):
        chunks = [
            chunk
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "recover from a failed command"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=adapter,
                obs=obs,
                skip_planning=True,
            )
        ]

    assert "I recovered honestly." in "".join(chunk.text for chunk in chunks)
    events = obs.history()
    tool_events = [event for event in events if event.type == "tool_call"]
    assert any(event.data.get("status") == "failed" for event in tool_events)
    # The Thinker now runs after tool failures too — it needs
    # to analyze the failure and tell the model what to do next (e.g. "try
    # the next URL"). The old behavior skipped the Thinker on failure, which
    # meant the model never got guidance on how to recover.
    # We no longer assert that agent_thinker_start is absent.
    # A recovered tool failure (model produced a real answer
    # after the failure) should NOT emit agent_loop_failure. The run is a
    # success — the user got their answer. The old behavior emitted
    # "tool_failure" even on recovery, which showed "Agent loop terminated"
    # to the user after they already had the answer.
    failure_events = [event for event in events if event.type == "agent_loop_failure"]
    assert not failure_events, (
        f"recovered tool failure must not emit agent_loop_failure — "
        f"the model produced a real answer. Got: {failure_events}"
    )


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

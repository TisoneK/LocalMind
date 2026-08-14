"""ADR-34 B-8: Parent evidence and final-synthesis boundary.

Validates that:
1. Tool output NEVER becomes the final assistant answer via a code shortcut.
   The authoritative sysinfo shortcut was removed — the parent model must
   synthesize its own response from the evidence.
2. The ``evidence_to_parent`` obs event fires when tool results are handed
   back to the parent model.
3. The synthesis directive instructs the model NOT to copy tool output
   verbatim.
4. Tool failure still flows through the parent (no shortcut).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator
from unittest.mock import MagicMock

import pytest

from core.agent.loop import AgentLoop
from core.models import StreamChunk, ToolResult


class _FakeAdapter:
    """Adapter that yields a tool call, then a synthesized final answer."""

    def __init__(self, tool_call_chunk: dict, final_chunks: list[str]):
        self._tool_call_chunk = tool_call_chunk
        self._final_chunks = final_chunks
        self._call_count = 0

    async def chat_with_tools(self, messages, tools=None, temperature=0.4, **kwargs):
        self._call_count += 1
        if self._call_count == 1:
            # First call: model requests a tool
            yield StreamChunk(
                text="",
                done=False,
                metadata={"tool_calls": [self._tool_call_chunk]},
            )
        else:
            # Subsequent calls: model synthesizes a final answer
            for text in self._final_chunks:
                yield StreamChunk(text=text, done=False)
            yield StreamChunk(text="", done=True)


def _make_loop() -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    return loop


def test_authoritative_sysinfo_shortcut_is_removed():
    """The _authoritative_sysinfo_answer shortcut must NOT be called in the
    active code path.  The source code must not contain the bypass that
    yielded raw tool output as the final answer."""
    import inspect

    from core.agent import loop as loop_mod

    source = inspect.getsource(loop_mod)
    # The shortcut pattern: yielding authoritative_answer directly as text
    # after a sysinfo tool call.  This must not appear in the active flow.
    assert "yield StreamChunk(text=authoritative_answer" not in source, (
        "B-8 violation: the authoritative sysinfo shortcut still yields raw "
        "tool output as the final assistant answer."
    )
    # The evidence_to_parent event must be emitted when tool results are
    # handed back to the parent model.
    assert "evidence_to_parent" in source, (
        "B-8: evidence_to_parent obs event is missing — the evidence "
        "boundary must be explicitly marked."
    )


def test_synthesis_directive_instructs_no_verbatim_copy():
    """The _force_final_answer directive must instruct the model NOT to copy
    tool output verbatim — it must synthesize a natural-language answer."""
    import inspect

    from core.agent.loop import AgentLoop

    source = inspect.getsource(AgentLoop._force_final_answer)
    assert "SYNTHESIS" in source, (
        "B-8: the synthesis directive is missing the SYNTHESIS instruction "
        "that prevents verbatim tool-output copying."
    )
    assert "Do NOT copy the tool output verbatim" in source, (
        "B-8: the directive must explicitly tell the model not to copy "
        "tool output verbatim."
    )


def test_visible_tool_output_hides_delegation_results():
    """The chat.py SSE boundary must hide delegation tool output from the
    chat channel — child agent results are parent evidence, not user-facing
    content."""
    from api.routes.chat import _visible_tool_output

    # Delegation tools must produce empty visible output
    assert _visible_tool_output("delegate", None, "child agent result") == ""
    assert _visible_tool_output("delegate_parallel", None, "parallel results") == ""
    assert _visible_tool_output("delegate_inline", None, "inline result") == ""

    # Child-agent-tagged tool calls must also produce empty visible output
    assert _visible_tool_output("shell", "research", "child shell output") == ""

    # Parent-owned tool output IS visible (e.g. sysinfo, shell run by parent)
    assert _visible_tool_output("sysinfo", None, "Current time: ...") == "Current time: ..."
    assert _visible_tool_output("shell", None, "ls output") == "ls output"


def test_evidence_to_parent_event_has_bounded_fields():
    """The evidence_to_parent obs event must carry bounded fields — never
    the full tool output content."""
    from core.obs import ObsCollector

    obs = ObsCollector()
    obs.emit(
        "evidence_to_parent",
        tool="sysinfo",
        iteration=1,
        evidence_chars=42,
        failed=False,
    )
    events = [e for e in obs.history() if e.type == "evidence_to_parent"]
    assert len(events) == 1
    evt = events[0]
    assert evt.data["tool"] == "sysinfo"
    assert evt.data["evidence_chars"] == 42
    assert evt.data["failed"] is False
    # The event must NOT contain the raw tool output text
    assert "content" not in evt.data
    assert "output" not in evt.data
    assert "observation" not in evt.data

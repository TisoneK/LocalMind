"""Session 342 — pre-tool Thinker consult in the parent-agent loop.

Root cause fixed: the Thinker ran only (a) on the conversational fast-path
(agent_runtime, S354) and (b) in the loop AFTER a tool produced an
observation. A parent-agent turn with zero tools and no fast-path match
("Fix my project.", "Improve the system.") therefore had NO structured
understanding pass — the model free-associated "I'll start by exploring…"
(narration-without-action, CONV-05/06) or fabricated under "just guess"
pressure (CONV-11).

Contract under test:
  1. On a zero-tool parent turn, the pre-tool Thinker consults ONCE before
     any tool call: agent_thinker_start/done fire, and the analysis reaches
     the FIRST model call's messages — never the user stream (silent).
  2. Skipped when a tool already ran this turn (initial_tool_result).
  3. Skipped when the adapter has thinking disabled.
  4. The injected block is marked [THINKER ANALYSIS] so _user_message_text
     (nudges/fallbacks) still reads the ORIGINAL user request.
  5. A failing consult never breaks the turn.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.agent.loop import AgentLoop, _thinker_context_block, _user_message_text
from core.agent.thinker import ThinkerAnalysis
from core.models import Intent, StreamChunk
from core.obs import ObsCollector


class _AnalysisThinker:
    """Fake Thinker returning a fixed non-empty analysis (the CONV-05 shape:
    the request is vague → the right next step is to ask, not to narrate)."""

    def __init__(self, timeout_secs=30.0):
        self.last_analysis = ThinkerAnalysis(
            facts=["the request is vague"],
            ambiguities=[],
            next_step="ask the user what project and what is broken",
            confidence=0.7,
        )

    async def consult(self, evidence, adapter, temperature=0.4):
        yield StreamChunk(text="", done=True)


class _NoopThinker:
    def __init__(self, timeout_secs=30.0):
        self.last_analysis = None

    async def consult(self, evidence, adapter, temperature=0.4):
        if False:
            yield  # pragma: no cover — keep this an async generator


class _RaisingThinker:
    def __init__(self, timeout_secs=30.0):
        self.last_analysis = None

    async def consult(self, evidence, adapter, temperature=0.4):
        raise RuntimeError("consult boom")
        yield  # pragma: no cover


def _clarify_stream():
    """The model's answer to 'fix my project' WITH the Thinker's guidance:
    ask what's broken instead of promising to explore."""

    async def _stream():
        yield StreamChunk(
            text="Which project is it, and what's actually broken? "
            "Tell me the symptom and I can point you at the cause.",
            done=False,
        )
        yield StreamChunk(text="", done=True)

    return _stream()


@pytest.mark.asyncio
async def test_pre_tool_thinker_injects_analysis_before_first_model_call():
    loop = AgentLoop(adapter=MagicMock())
    first_call_messages: dict = {}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        first_call_messages.setdefault("messages", list(messages))
        return _clarify_stream()

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()

    chunks = []
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.thinker.Thinker", _AnalysisThinker):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "fix my project"}],
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            chunks.append(chunk)

    # 1. The Thinker consulted (lifecycle events fired).
    assert any(e.type == "agent_thinker_start" for e in obs.history()), "pre-tool consult must run"
    assert any(e.type == "agent_thinker_done" for e in obs.history())
    # 2. The analysis reached the FIRST model call's context — by name.
    assert first_call_messages, "the loop must have made a model call"
    joined = " ".join(str(m.get("content", "")) for m in first_call_messages["messages"])
    assert "[THINKER ANALYSIS]" in joined, "analysis block must be injected into the first call"
    assert "ask the user what project" in joined, "the analysis's next_step must be present"
    # 3. Silent: nothing Thinker-shaped leaks into the user stream.
    user_text = "".join(c.text for c in chunks)
    assert "[THINKER ANALYSIS]" not in user_text
    assert "ask the user what project" not in user_text
    # 4. The user-visible answer is the model's own clarifying question.
    assert "Which project is it" in user_text


@pytest.mark.asyncio
async def test_pre_tool_thinker_skipped_when_tool_already_ran():
    from core.models import ToolResult

    loop = AgentLoop(adapter=MagicMock())
    first_call_messages: dict = {}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        first_call_messages.setdefault("messages", list(messages))
        return _clarify_stream()

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()

    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.thinker.Thinker", _AnalysisThinker):
        async for _chunk in loop.run(
            messages=[{"role": "user", "content": "list files"}],
            intent=Intent.SHELL,
            initial_tool_result=ToolResult(source="shell", content="a.txt\nb.txt", success=True),
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            pass

    # A tool already ran this turn — the pre-tool consult is pointless; the
    # post-tool consult covers the evidence. No Thinker, no injected block.
    assert not any(e.type == "agent_thinker_start" for e in obs.history())
    joined = " ".join(str(m.get("content", "")) for m in first_call_messages["messages"])
    assert "[THINKER ANALYSIS]" not in joined


@pytest.mark.asyncio
async def test_pre_tool_thinker_skipped_when_thinking_disabled():
    loop = AgentLoop(adapter=MagicMock())
    first_call_messages: dict = {}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        first_call_messages.setdefault("messages", list(messages))
        return _clarify_stream()

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = False  # non-reasoning model — skip (matches fast-path gate)
    obs = ObsCollector()

    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.thinker.Thinker", _AnalysisThinker):
        async for _chunk in loop.run(
            messages=[{"role": "user", "content": "fix my project"}],
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            pass

    assert not any(e.type == "agent_thinker_start" for e in obs.history())
    joined = " ".join(str(m.get("content", "")) for m in first_call_messages["messages"])
    assert "[THINKER ANALYSIS]" not in joined


def test_user_message_text_skips_thinker_block():
    """The injected block must never be read back as 'the user's original
    request' by recovery nudges / fallbacks (same pattern as the
    [ACCEPTANCE GATE] skip)."""
    analysis = ThinkerAnalysis(facts=["the request is vague"], next_step="ask for details")
    block = _thinker_context_block(analysis)
    assert "[THINKER ANALYSIS]" in block
    msgs = [
        {"role": "user", "content": "fix my project"},
        {"role": "user", "content": block},
    ]
    assert _user_message_text(msgs) == "fix my project", \
        "the Thinker block must not shadow the original user request"


@pytest.mark.asyncio
async def test_pre_tool_consult_failure_never_breaks_turn():
    loop = AgentLoop(adapter=MagicMock())

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        return _clarify_stream()

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()

    chunks = []
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.thinker.Thinker", _RaisingThinker):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "fix my project"}],
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            chunks.append(chunk)

    # The raising consult was swallowed; the turn still answered normally.
    full = "".join(c.text for c in chunks)
    assert "Which project is it" in full, f"turn must survive a failing consult: {full!r}"
    # No agent_thinker_done (the analysis never completed) — honest lifecycle.
    assert not any(e.type == "agent_thinker_done" for e in obs.history())


# ── Session 343: pressured re-ask of a refused unanswerable (loop wiring) ──


@pytest.mark.asyncio
async def test_pressured_reask_returns_direct_refusal_without_model_call():
    """B-2026-08-22-1/-2 wiring: when the history shows the agent already
    refused an unanswerable and the follow-up pressures it ('just guess' /
    'check your memory'), the loop must return the deterministic refusal
    with ZERO model calls — no fresh pass to cave in, no credential hunt."""
    from agents.base_agent import AgentConfig
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    loop = AgentLoop(adapter=MagicMock())
    calls = {"n": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        calls["n"] += 1
        raise AssertionError("the loop must refuse deterministically, no model call")

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()

    agent_config = AgentConfig(
        name="parent",
        max_iterations=20,
        allowed_tools=AGENT_ALLOWED_TOOLS,
    )
    messages = [
        {"role": "user", "content": "What is my database password?"},
        {"role": "assistant", "content": "I don't have access to that information. "
                                         "I can only see the current conversation."},
        {"role": "user", "content": "I'm sure I stored it with you. Check your memory."},
    ]

    chunks = []
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        async for chunk in loop.run(
            messages=messages,
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            agent_config=agent_config,
            skip_planning=True,
        ):
            chunks.append(chunk)

    assert calls["n"] == 0, "deterministic refusal must not call the model"
    full = "".join(c.text for c in chunks)
    assert "already told you" in full, f"expected the hold-the-refusal text, got: {full!r}"
    # No Thinker consult either — the refusal returns before the pre-tool pass.
    assert not any(e.type == "agent_thinker_start" for e in obs.history())
    # And no tools ran (no credential hunt).
    assert not any(e.type == "tool_call" for e in obs.history())

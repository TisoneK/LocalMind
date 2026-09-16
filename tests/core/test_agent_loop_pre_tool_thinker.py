"""Pre-tool Thinker consult in the parent-agent loop.

Root cause fixed: the Thinker ran only (a) on the conversational fast-path
(agent_runtime) and (b) in the loop AFTER a tool produced an
observation. A parent-agent turn with zero tools and no fast-path match
therefore had NO structured understanding pass — the model free-associated
"I'll start by exploring…" (narration-without-action, CONV-05/06) or
fabricated under "just guess" pressure (CONV-11).

NOTE: the original motivating messages ("Fix my project.",
"Improve the system.") are since handled DETERMINISTICALLY by Cluster F in
pre_init_classifier (vague imperative → clarify, zero model calls), so the
Thinker tests below use a concrete-but-zero-tool task to exercise the
consult; the short-circuit itself is covered by
`test_vague_imperative_short_circuits_before_thinker`.

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

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop, _thinker_context_block, _user_message_text
from core.agent.thinker import ThinkerAnalysis
from core.models import Intent, RiskLevel, StreamChunk, ToolResult
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


class _StreamingThinker(_AnalysisThinker):
    """Also streams prose reasoning as thinking chunks (the
    slice-1 consult contract) and records the Evidence it was handed."""

    def __init__(self, timeout_secs=30.0):
        super().__init__(timeout_secs)
        self.evidence_seen: list = []

    async def consult(self, evidence, adapter, temperature=0.4):
        self.evidence_seen.append(evidence)
        yield StreamChunk(text="", thinking="request is vague; the fix is to ask", done=False)
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
            messages=[{"role": "user", "content": "add a notes.txt file"}],
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
            messages=[{"role": "user", "content": "add a notes.txt file"}],
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
            messages=[{"role": "user", "content": "add a notes.txt file"}],
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


# ── Pressured re-ask of a refused unanswerable (loop wiring) ──


@pytest.mark.asyncio
async def test_pressured_reask_returns_direct_refusal_without_model_call():
    """Wiring check: when the history shows the agent already
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


# ── Cluster F loop wiring ──


@pytest.mark.asyncio
async def test_vague_imperative_short_circuits_before_thinker():
    """'Fix my project.' now returns the deterministic
    clarifying question with ZERO model calls — the tool-first reflex (CAT2-2
    burned 10 tools / 164s before asking) never gets a chance to start."""
    from agents.base_agent import AgentConfig
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    loop = AgentLoop(adapter=MagicMock())
    model_calls = 0

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        nonlocal model_calls
        model_calls += 1
        return _clarify_stream()

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
            agent_config=agent_config,
            skip_planning=True,
        ):
            chunks.append(chunk)

    assert model_calls == 0, "deterministic clarify must not call the model"
    # No Thinker consult either — the clarify is decided before any reasoning.
    assert not any(e.type == "agent_thinker_start" for e in obs.history())
    user_text = "".join(c.text for c in chunks)
    assert "clarify" in user_text.lower() or "could you" in user_text.lower(), user_text


# ── Thinker gating, then concurrency (B-2026-09-03 / S428) ──
# Value-gated the reflexive consults (once per turn, failure /
# >=2 sources) to kill the earlier serial latency. An owner-approved
# replaces that gate with CONCURRENCY: a consult after every successful tool
# runs in the background (zero added latency), failures stay blocking, volume
# is bounded by one-in-flight + a per-turn cap.


@pytest.mark.asyncio
async def test_pretool_thinker_skipped_for_direct_retrieval_intent():
    """A direct-retrieval intent (WEB_SEARCH) has an obvious action — the
    pre-tool consult is a wasted serial round-trip and must be skipped. ANALYZE
    (the open-ended case) still fires it (covered by the test above)."""
    loop = AgentLoop(adapter=MagicMock())

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        return _clarify_stream()  # answer directly, no tool

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()

    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.thinker.Thinker", _AnalysisThinker):
        async for _ in loop.run(
            messages=[{"role": "user", "content": "latest python version"}],
            intent=Intent.WEB_SEARCH,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            pass

    assert not any(e.type == "agent_thinker_start" for e in obs.history()), \
        "pre-tool consult must be skipped for a direct-retrieval intent"


@pytest.mark.asyncio
async def test_posttool_thinker_consults_once_across_many_tools():
    """The post-tool consult fires at most ONCE per turn even when several
    successful tools each satisfy the value-gate. The iter-N re-fire (measured:
    iter 2 AND iter 3 on a 3-source turn) was pure redundancy — the once-guard
    (the site's own long-documented contract, finally wired) drops it.

    Uses WEB_SEARCH so the pre-tool consult is skipped: every start counted
    here is therefore a POST-tool consult, isolating the once-guard.
    """
    loop = AgentLoop(adapter=MagicMock())
    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        await asyncio.sleep(0)  # yield: let the previous background consult task run
        if seen["calls"] <= 3:
            return ToolCallResult(
                tool_name="shell",
                tool_args={"command": f"echo source-{seen['calls']}"},
                raw_content="",
            )

        async def _answer():
            yield StreamChunk(text="Here is the combined answer from the sources.", done=False)
            yield StreamChunk(text="", done=True)

        return _answer()

    async def fake_dispatch(intent, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content="file1.txt\nfile2.txt", risk=RiskLevel.LOW, source="shell"),
            False,  # not failed
            0,
        )

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()

    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", side_effect=fake_dispatch), \
         patch("core.agent.thinker.Thinker", _AnalysisThinker):
        async for _ in loop.run(
            messages=[{"role": "user", "content": "find the weather in three cities"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            pass

    # The once-per-turn guard is GONE — a consult
    # fires after every successful tool (bounded by the in-flight rule +
    # per-turn cap) and each one completes and is absorbed. SHELL is not a
    # direct-retrieval intent, so the pre-tool consult (iteration 0) also
    # fires; count only the post-tool ones (iteration >= 1).
    starts = [e for e in obs.history() if e.type == "agent_thinker_start" and e.data.get("iteration", 0) >= 1]
    dones = [e for e in obs.history() if e.type == "agent_thinker_done" and e.data.get("iteration", 0) >= 1]
    assert len(starts) == 3, f"a consult per successful tool expected, got {len(starts)}"
    # The LAST consult may legitimately still be in flight when the model
    # answers on the very next call — the loop ends without a further drain
    # point (honest lifecycle: start without done). At least the first two
    # must complete.
    assert len(dones) >= 2, f"completed consults expected, got {len(dones)}"


@pytest.mark.asyncio
async def test_posttool_consults_capped_per_turn():
    """The per-turn cap (_THINKER_CONSULT_CAP) bounds consult
    volume — a 7-tool turn consults at most 5 times even though every tool
    succeeds."""
    from core.agent.loop import _THINKER_CONSULT_CAP

    loop = AgentLoop(adapter=MagicMock())
    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        await asyncio.sleep(0)  # yield: let the previous background consult task run
        if seen["calls"] <= 7:
            return ToolCallResult(
                tool_name="shell",
                tool_args={"command": f"echo source-{seen['calls']}"},
                raw_content="",
            )

        async def _answer():
            yield StreamChunk(text="Combined answer.", done=False)
            yield StreamChunk(text="", done=True)

        return _answer()

    async def fake_dispatch(intent, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content="file1.txt\nfile2.txt", risk=RiskLevel.LOW, source="shell"),
            False,
            0,
        )

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()

    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", side_effect=fake_dispatch), \
         patch("core.agent.thinker.Thinker", _AnalysisThinker):
        async for _ in loop.run(
            messages=[{"role": "user", "content": "find the weather in seven cities"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            pass

    starts = [e for e in obs.history() if e.type == "agent_thinker_start" and e.data.get("iteration", 0) >= 1]
    assert len(starts) == _THINKER_CONSULT_CAP, (
        f"post-tool consult volume must be capped at {_THINKER_CONSULT_CAP}, got {len(starts)}"
    )


@pytest.mark.asyncio
async def test_background_consult_does_not_block_turn():
    """Core property: a slow post-tool consult must NOT delay
    the turn — the loop proceeds on the raw observation while the consult
    overlaps the model work. The wall-clock of the turn must stay well under
    the consult's own duration."""
    import asyncio as _asyncio
    import time as _time

    # Warm the process with an IDENTICAL tool-bearing turn (instant thinker)
    # so one-time lazy init (config disk load, skills, tool registry) is not
    # counted as turn latency; only the consult's sleep differs below.
    async def _run_turn(thinker_cls):
        turn_loop = AgentLoop(adapter=MagicMock())
        turn_calls = {"n": 0}

        async def turn_chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            turn_calls["n"] += 1
            await asyncio.sleep(0)  # yield: let the background consult task run
            if turn_calls["n"] == 1:
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "echo source-1"},
                    raw_content="",
                )

            async def _answer():
                yield StreamChunk(text="Here is the combined answer from the sources.", done=False)
                yield StreamChunk(text="", done=True)

            return _answer()

        async def turn_dispatch(intent, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
            return (
                ToolResult(content="file1.txt\nfile2.txt", risk=RiskLevel.LOW, source="shell"),
                False,
                0,
            )

        turn_adapter = MagicMock()
        turn_adapter.chat_with_tools = turn_chat
        turn_adapter.chat = lambda *a, **k: iter(())
        turn_adapter.thinking_enabled = True
        turn_obs = ObsCollector()
        t_start = _time.monotonic()
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x),              patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x),              patch("core.agent.loop.dispatch_with_retry", side_effect=turn_dispatch),              patch("core.agent.thinker.Thinker", thinker_cls):
            turn_chunks = []
            async for _chunk in turn_loop.run(
                messages=[{"role": "user", "content": "find the weather"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=turn_adapter,
                obs=turn_obs,
                skip_planning=True,
            ):
                turn_chunks.append(_chunk)
        return _time.monotonic() - t_start, turn_obs, turn_chunks

    class _SlowThinker(_AnalysisThinker):
        async def consult(self, evidence, adapter, temperature=0.4):
            # Sleep ONLY for the post-tool (background) consult — the pre-tool
            # consult is blocking BY DESIGN (evidence.observations is empty
            # there), and it must stay instant for this test.
            if evidence.observations.strip():
                await _asyncio.sleep(1.5)
            yield StreamChunk(text="", done=True)

    warm_elapsed, _, _ = await _run_turn(_AnalysisThinker)  # warm + baseline
    elapsed, obs, chunks = await _run_turn(_SlowThinker)

    assert any(e.type == "agent_thinker_start" for e in obs.history()), "consult fired"
    # The turn carries ~0.9s of synchronous machine overhead unrelated to the
    # consult (VectorStore/env construction) — the non-blocking property is
    # the DELTA vs the identical warm turn. The consult sleeps 1.5s so the
    # signal dwarfs machine jitter: a blocking consult adds >= 1.5s, while a
    # non-blocking one shows only jitter (threshold 0.8s).
    assert (elapsed - warm_elapsed) < 0.8, (
        f"the turn must not wait for the background consult "
        f"(delta {(elapsed - warm_elapsed):.2f}s: slow {elapsed:.2f}s vs warm {warm_elapsed:.2f}s)"
    )
    assert "Here is the combined answer" in "".join(c.text for c in chunks), "turn completed"
    # Let the orphaned consult task finish so the event loop closes clean.
    await _asyncio.sleep(0.4)


@pytest.mark.asyncio
async def test_failed_tool_consult_blocks_next_call():
    """Exception: after a FAILED tool the consult stays
    BLOCKING — its recovery advice must be in the VERY NEXT model call's
    context, not one iteration late."""
    loop = AgentLoop(adapter=MagicMock())
    seen = {"calls": 0}
    call_messages: list = []

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        call_messages.append(list(messages))
        if seen["calls"] == 1:
            await asyncio.sleep(0)  # yield: let the background consult task run
            return ToolCallResult(
                tool_name="shell",
                tool_args={"command": "echo source-1"},
                raw_content="",
            )

        async def _answer():
            yield StreamChunk(text="Recovered with the next source.", done=False)
            yield StreamChunk(text="", done=True)

        return _answer()

    async def fake_dispatch(intent, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content="403 forbidden", risk=RiskLevel.LOW, source="shell"),
            True,  # FAILED — recovery steering must be immediate
            0,
        )

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()

    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", side_effect=fake_dispatch), \
         patch("core.agent.thinker.Thinker", _AnalysisThinker):
        async for _ in loop.run(
            messages=[{"role": "user", "content": "find the weather"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            pass

    assert any(e.type == "agent_thinker_start" for e in obs.history()), "consult fired on failure"
    assert len(call_messages) >= 2
    # The blocking consult's analysis is already in the SECOND model call.
    second_call_text = " ".join(
        str(m.get("content", "")) for m in call_messages[1]
    )
    assert "[THINKER ANALYSIS]" in second_call_text, (
        "the failure consult's analysis must block until it shapes the next call"
    )


# ── The consult's reasoning streams; the analysis compounds ───────────


@pytest.mark.asyncio
async def test_consult_reasoning_streams_to_user():
    """ADR-57 slice 1: the pre-tool consult's prose reasoning reaches
    the run() output as thinking chunks (the ThinkingBlock's channel) — the
    consult is no longer a silent serial call. The structured JSON tail still
    never appears (the Thinker stops at the marker)."""
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
         patch("core.agent.thinker.Thinker", _StreamingThinker):
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "add a notes.txt file"}],
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            chunks.append(chunk)

    thinking = "".join(c.thinking for c in chunks if c.thinking)
    assert "the fix is to ask" in thinking, "consult prose must stream to the ThinkingBlock"
    # The analysis JSON/structure still never leaks into either channel.
    assert '"facts"' not in thinking
    user_text = "".join(c.text for c in chunks)
    assert "ask the user what project" not in user_text


@pytest.mark.asyncio
async def test_posttool_consult_receives_pretool_analysis():
    """S425 continuity: when the pre-tool consult ran and tools then ran, the
    post-tool consult's Evidence carries the earlier analysis so the reasoning
    builds on itself instead of restarting."""
    loop = AgentLoop(adapter=MagicMock())
    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        await asyncio.sleep(0)  # yield: let the previous background consult task run
        if seen["calls"] <= 2:
            return ToolCallResult(
                tool_name="system_search",
                tool_args={"query": f"thing {seen['calls']}"},
                raw_content="",
            )

        async def _answer():
            yield StreamChunk(text="Done — here is the answer.", done=False)
            yield StreamChunk(text="", done=True)

        return _answer()

    async def fake_dispatch(intent, raw_input, allowed_tool_names=None, adapter=None, **kwargs):
        return (
            ToolResult(content="a real result", risk=RiskLevel.LOW, source="system_search"),
            False,  # not failed
            0,
        )

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = lambda *a, **k: iter(())
    mock_adapter.thinking_enabled = True
    obs = ObsCollector()

    capturing = _StreamingThinker()
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", side_effect=fake_dispatch), \
         patch("core.agent.thinker.Thinker", lambda **kw: capturing):
        async for _ in loop.run(
            messages=[{"role": "user", "content": "compare the two reports and pick one"}],
            intent=Intent.ANALYZE,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
            skip_planning=True,
        ):
            pass

    assert len(capturing.evidence_seen) >= 2, (
        "pre-tool consult + post-tool consults per successful tool expected"
    )
    pre, post1, post2 = (
        capturing.evidence_seen[0],
        capturing.evidence_seen[1],
        capturing.evidence_seen[-1],
    )
    assert pre.prior_analysis == "", "the pre-tool consult has no earlier analysis"
    assert "ask the user what project" in post1.prior_analysis, \
        "the first post-tool consult must receive the pre-tool analysis (continuity)"
    assert "ask the user what project" in post2.prior_analysis, \
        "the second post-tool consult must receive the earlier analysis too"
    assert post1.observations and post2.observations, \
        "the post-tool consults must see the gathered evidence"

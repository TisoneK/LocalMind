"""ADR-18 P2 failure-memory tests (Session 175) — the Remember stage.

Covers:
  1. classify_failure — deterministic what-failed-and-why from a trace
     (iteration_limit / criteria_unmet / tool_failure / success → none).
  2. build_failure_summary / format_recall_hint — human-readable shapes.
  3. DB round-trip — record_failure + recall_failures (token overlap,
     newest first, no-match → empty).
  4. Engine wiring — the loop's agent_loop_failure obs event is persisted
     to the store, and past failures are recalled into memory_facts on a
     similar turn.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.agent.models import AgentStep, AgentTrace
from core.failure_memory import (
    build_failure_summary,
    classify_failure,
    format_recall_hint,
)


def _trace(*, hit_limit=False, criteria=None, gate_passed=None, failed_tools=()):
    trace = AgentTrace(success_criteria=criteria or [])
    if hit_limit:
        trace.hit_limit = True
    if gate_passed is not None:
        trace.gate_passed = gate_passed
    trace.criteria_results = [
        (c, passed, "note") for c, passed in (criteria or [])
    ]
    for i, name in enumerate(failed_tools):
        trace.steps.append(
            AgentStep(
                iteration=i + 1,
                thought="",
                tool_name=name,
                tool_input="x",
                observation="boom",
                tool_failed=True,
            )
        )
    return trace


# ── 1. classify_failure ────────────────────────────────────────────────────


def test_classify_iteration_limit_wins_over_criteria():
    trace = _trace(hit_limit=True, criteria=[("pytest passes", False)], gate_passed=False)
    assert classify_failure(trace) == "iteration_limit"


def test_classify_criteria_unmet():
    trace = _trace(criteria=[("pytest passes", False)], gate_passed=False)
    assert classify_failure(trace) == "criteria_unmet"


def test_classify_tool_failure():
    trace = _trace(failed_tools=["shell"])
    assert classify_failure(trace) == "tool_failure"


def test_classify_success_returns_empty():
    # No cap, no criteria, no failed tools → not a failure → NOT remembered.
    assert classify_failure(_trace()) == ""
    # Criteria met → success → not a failure.
    assert classify_failure(_trace(criteria=[("pytest passes", True)], gate_passed=True)) == ""


# ── 2. Summaries ───────────────────────────────────────────────────────────


def test_build_failure_summary_iteration_limit():
    trace = _trace(hit_limit=True, criteria=[("pytest passes", False)], gate_passed=False)
    summary = build_failure_summary(trace)
    assert "iteration limit" in summary


def test_build_failure_summary_criteria_unmet_names_criterion():
    trace = _trace(criteria=[("tsc clean", False)], gate_passed=False)
    summary = build_failure_summary(trace)
    assert "tsc clean" in summary


def test_build_failure_summary_tool_failure_names_tool():
    trace = _trace(failed_tools=["shell"])
    summary = build_failure_summary(trace)
    assert "shell" in summary


def test_format_recall_hint_empty_and_populated():
    assert format_recall_hint([]) == ""
    hint = format_recall_hint(
        [
            {"failure_type": "tool_failure", "summary": "Tool failure(s): shell."},
            {"failure_type": "iteration_limit", "summary": "Hit the iteration limit after 8."},
        ],
        max_entries=1,
    )
    assert "Past similar failures to avoid" in hint
    assert "tool_failure" in hint
    assert "Hit the iteration limit" not in hint  # capped at max_entries


# ── 3. DB round-trip ───────────────────────────────────────────────────────


def _store(tmp_path):
    from storage.db import SessionStore

    store = SessionStore(str(tmp_path / "failure.db"))
    store._init_db()
    return store


def test_db_record_and_recall_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.record_failure("s1", "shell", "create hello world repo", "iteration_limit", "Hit cap after 8")
    store.record_failure("s2", "shell", "fix the build in frontend", "tool_failure", "Tool failure(s): shell")
    store.record_failure("s3", "chat", "unrelated chatter", "criteria_unmet", "unmet")

    # Token overlap match on the stored message (≥2 shared tokens).
    hits = store.recall_failures("create hello world repo in dev", intent="shell")
    assert hits, "expected a recall hit for the matching message"
    assert hits[0]["failure_type"] == "iteration_limit"

    # Unrelated message → no matches.
    assert store.recall_failures("how is the weather today") == []

    # Intent filter: a chat-intent failure is NOT recalled for shell.
    assert store.recall_failures("repo build", intent="shell") == []
    assert store.recall_failures("unrelated chatter", intent="chat") != []


def test_db_recall_empty_or_short_message_returns_empty(tmp_path):
    store = _store(tmp_path)
    store.record_failure("s1", "shell", "create hello world repo", "iteration_limit", "cap")
    assert store.recall_failures("") == []
    assert store.recall_failures("the and with that") == []  # all stopwords
    # One surviving token after stopword filtering → below the 2-token bar.
    assert store.recall_failures("hello") == []


def test_db_recall_prunes_stale_failures(tmp_path):
    """record_failure prunes rows older than the retention window, so
    old failures age out of recall."""
    store = _store(tmp_path)
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO failure_memory(session_id, intent, message, failure_type, summary, created_at) "
            "VALUES('old', 'shell', 'stale old failure pattern', 'iteration_limit', 'old', "
            "datetime('now', '-200 days'))"
        )
    # Write a fresh row → prune runs → the stale row is gone.
    store.record_failure("s1", "shell", "another fresh pattern", "iteration_limit", "new")
    # The stale row was pruned; only the fresh (different) row remains.
    assert store.recall_failures("stale old failure pattern", intent="shell") == []
    assert store.recall_failures("another fresh pattern", intent="shell") != []


# ── 4. Engine wiring ───────────────────────────────────────────────────────


class _FailLoopAdapter:
    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None, tool_choice=None):
        async def _stream():
            from core.models import StreamChunk

            yield StreamChunk(text="", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def chat(self, messages, temperature=0.4, intent=None):
        return
        yield  # pragma: no cover


async def _run_capped_loop(obs):
    """Drive a loop that ends on the empty-response honest fail (adapter keeps
    returning empty streams → the iter-0 nudge burns iteration 1, iteration 2
    hits the Session 115 fast-fail)."""
    from core.agent.loop import AgentLoop
    from core.models import Intent

    loop = AgentLoop(adapter=MagicMock())

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        async def _stream():
            from core.models import StreamChunk

            yield StreamChunk(text="", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = _FailLoopAdapter.chat

    with patch("core.agent.loop.MAX_ITERATIONS", 2), patch(
        "core.agent.loop.PLAN_ENABLED", False
    ), patch(
        "core.agent.loop._filter_tool_injection", side_effect=lambda x: x
    ), patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        async for _c in loop.run(
            messages=[{"role": "user", "content": "x"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            obs=obs,
        ):
            pass


@pytest.mark.asyncio
async def test_loop_emits_failure_event_on_empty_response():
    """A loop that ends with the model returning an empty response emits
    agent_loop_failure (type=empty_response) — the engine persists it.
    This is the Session 31 silent-stall failure mode; remembering it is
    exactly what ADR-18 P2 is for."""
    from core.obs import ObsCollector

    obs = ObsCollector()
    await _run_capped_loop(obs)

    events = [e.type for e in obs.history()]
    assert "agent_loop_failure" in events
    failure = next(e for e in obs.history() if e.type == "agent_loop_failure")
    assert failure.data["failure_type"] == "empty_response"
    assert "empty response" in failure.data["summary"]


@pytest.mark.asyncio
async def test_loop_emits_failure_event_on_hit_limit():
    """A genuinely capped loop (adapter keeps demanding tools, never
    finishing) emits agent_loop_failure with type=iteration_limit."""
    from core.agent.loop import AgentLoop
    from core.models import Intent, ToolResult
    from core.obs import ObsCollector
    from tools import available_tools

    loop = AgentLoop(adapter=MagicMock())
    obs = ObsCollector()

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        # Every call returns a tool call for shell → the loop burns
        # iterations without ever producing a final answer → cap hit.
        from adapters.ollama import ToolCallResult

        return ToolCallResult(tool_name="shell", tool_args={"command": "ls"})

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = _FailLoopAdapter.chat

    # A tool dispatch that returns a successful-but-empty result so the
    # loop keeps iterating (real tools are out of scope here).
    with patch("core.agent.loop.MAX_ITERATIONS", 2), patch(
        "core.agent.loop.PLAN_ENABLED", False
    ), patch(
        "core.agent.loop._filter_tool_injection", side_effect=lambda x: x
    ), patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), patch(
        "core.agent.loop.dispatch_with_retry",
        return_value=ToolResult(content="ok", source="shell", success=True),
    ):
        async for _c in loop.run(
            messages=[{"role": "user", "content": "x"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[t for t in available_tools() if t.get("intent") == "shell"],
            adapter=adapter,
            obs=obs,
        ):
            pass

    events = [e.type for e in obs.history()]
    assert "agent_loop_failure" in events
    failure = next(e for e in obs.history() if e.type == "agent_loop_failure")
    assert failure.data["failure_type"] == "iteration_limit"
    assert "iteration limit" in failure.data["summary"]


@pytest.mark.asyncio
async def test_loop_success_emits_no_failure_event():
    """A successful run emits NO agent_loop_failure (nothing to remember)."""
    from core.obs import ObsCollector

    obs = ObsCollector()

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        async def _stream():
            from core.models import StreamChunk

            yield StreamChunk(text="All done.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    from core.agent.loop import AgentLoop
    from core.models import Intent

    loop = AgentLoop(adapter=MagicMock())
    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = _FailLoopAdapter.chat

    with patch("core.agent.loop.PLAN_ENABLED", False), patch(
        "core.agent.loop._filter_tool_injection", side_effect=lambda x: x
    ), patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        async for _c in loop.run(
            messages=[{"role": "user", "content": "hi"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            obs=obs,
        ):
            pass

    events = [e.type for e in obs.history()]
    assert "agent_loop_failure" not in events


@pytest.mark.asyncio
async def test_engine_persists_failure_and_recalls_it(tmp_path, monkeypatch):
    """End-to-end: a failed run is persisted; a similar next turn recalls
    the hint into memory_facts (Remember→Continue)."""
    from core.engine import Engine
    from core.obs import ObsCollector

    # Point the engine at a scratch DB BEFORE constructing it, so the
    # SessionStore it creates uses the scratch path.
    monkeypatch.setattr("core.config.settings.localmind_db_path", str(tmp_path / "lm.db"))
    engine = Engine()

    # Turn 1: a capped agent-loop run → agent_loop_failure persisted.
    captured_failures = []
    _orig_record_failure = engine._store.record_failure

    def spy_record_failure(session_id, intent, message, failure_type, summary):
        captured_failures.append((failure_type, message))
        _orig_record_failure(session_id, intent, message, failure_type, summary)

    engine._store.record_failure = spy_record_failure

    mock_adapter = MagicMock()
    mock_adapter.effective_context_window = 8192

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        async def _stream():
            from core.models import StreamChunk

            yield StreamChunk(text="", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def chat(messages, temperature=0.4, intent=None):
        async def _stream():
            from core.models import StreamChunk

            yield StreamChunk(text="", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = chat

    with patch("core.engine.get_adapter", return_value=mock_adapter), patch(
            "core.agent.loop.MAX_ITERATIONS", 1
        ), patch("core.agent.loop.PLAN_ENABLED", False):
        # Force the loop to hit the cap (1 iteration, empty streams) so the
        # failure event fires even though the engine's fallback text exists.
        obs1 = ObsCollector()
        chunks = [
            c
            async for c in engine.process(
                "build the frontend app", "sess-failmem", obs=obs1
            )
        ]
        assert any(getattr(c, "done", False) for c in chunks)

    assert captured_failures, "engine must persist the loop failure event"

    # Turn 2: recall — the failure hint is appended to memory_facts.
    recalled = engine._store.recall_failures("build the frontend app", intent="analyze")
    assert recalled, "the persisted failure must be recallable"
    assert "frontend" in recalled[0]["message"] or "build" in recalled[0]["message"]

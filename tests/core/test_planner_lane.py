"""The Planner lane end to end (the 2026-11-02 export fixes).

The owner's live export (session-1793620218681) showed the production path
still rendering syn- tool-echo todos, a Thinker consult rehearsing its JSON
decision inside the visible thinking, and no honest close. These tests pin:

- the runtime-path plan seeding (plan_steps + plan_outcomes + plan_objective
  through AgentLoop.run with skip_planning=True — the production shape),
- the per-todo contract becoming the acceptance gate's criteria,
- adaptive plan revision via the gate's plan_revision_cb (retired status +
  todo_revised diff, one revision per turn),
- the objective-fidelity lane's verdicts and fail-opens,
- the Thinker's fence suppression (no JSON rehearsal in the visible
  reasoning),
- the finalize sweep leaving retired rows closed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from core.agent.loop import AgentLoop
from core.agent.thinker.thinker import _FenceSuppressor
from core.models import Intent, StreamChunk, ToolResult
from core.obs import ObsCollector

# ── Thinker fence suppression ────────────────────────────────────────────────


def test_fence_suppressor_strips_fenced_json_across_chunks():
    """The 2026-11-02 export: the consult's reasoning rehearsed the decision
    JSON inside a fenced block, streamed in pieces. The deliberation around
    it stays; the fence goes — including when the markers split across
    chunks."""
    s = _FenceSuppressor()
    out = (
        s.feed("The evidence names two files. ")
        + s.feed("Let me structure this as a JSON response: ```json")
        + s.feed(' {"facts": ["a"], ')
        + s.feed('"next_step": "read b"}')
        + s.feed("``` ")
        + s.feed("So the next step is reading b.")
        + s.flush()
    )
    assert "Let me structure this" in out
    assert "So the next step is reading b." in out
    assert '"facts"' not in out
    assert "```" not in out


def test_fence_suppressor_keeps_plain_reasoning():
    s = _FenceSuppressor()
    out = s.feed("Reasoning without any fences — keep every char.") + s.flush()
    assert out == "Reasoning without any fences — keep every char."


def test_fence_suppressor_unclosed_fence_suppresses_to_end():
    """An unclosed fence means the rest is block content; nothing after it
    shows (the decision itself was never on this channel)."""
    s = _FenceSuppressor()
    out = s.feed("Before. ```json {\"a\": 1}") + s.feed(" more json}") + s.flush()
    assert "Before." in out
    assert "\"a\"" not in out


def test_fence_suppressor_split_marker_across_chunks():
    s = _FenceSuppressor()
    a = s.feed("prose ``")
    b = s.feed("`hidden```")
    c = s.feed(" visible again")
    out = a + b + c + s.flush()
    assert "prose" in out
    assert "hidden" not in out
    assert "visible again" in out


# ── Loop: the runtime-path plan (the production shape) ──────────────────────


def _planned_run(plan_steps, plan_outcomes, plan_objective=""):
    """Drive AgentLoop.run exactly the way the runtime's warm-kernel path
    does (skip_planning=True + a caller-drawn plan) with a stub adapter:
    one web_search, then a final answer."""
    from adapters.ollama import ToolCallResult

    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        if seen["calls"] == 1:
            return ToolCallResult(
                tool_name="web_search", tool_args={"query": "weather Kitengela now"}
            )

        async def _stream():
            yield StreamChunk(
                text="Kitengela is 24°C and sunny today (AccuWeather).", done=False
            )
            yield StreamChunk(text="", done=True)

        return _stream()

    async def dispatch(*args, **kwargs):
        return (
            ToolResult(
                source="web", content="Kitengela weather: 24°C, sunny — AccuWeather, today."
            ),
            False,
            0,
        )

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = lambda *a, **k: _empty_agen()
    obs = ObsCollector()

    async def go():
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            return [
                c
                async for c in AgentLoop(adapter=MagicMock()).run(
                    messages=[{"role": "user", "content": "weather in Kitengela right now"}],
                    intent=Intent.WEB_SEARCH,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=adapter,
                    obs=obs,
                    skip_planning=True,
                    plan_steps=plan_steps,
                    plan_outcomes=plan_outcomes,
                    plan_objective=plan_objective,
                )
            ], obs

    return asyncio.run(go())


async def _empty_agen():
    if False:
        yield StreamChunk(text="", done=True)


def test_runtime_plan_seeds_todos_with_outcome_contract():
    """plan-{i} rows arrive cleared + pending + carrying the Planner's
    outcome — the panel shows the drawn plan, never a syn- tool echo."""
    _chunks, obs = _planned_run(
        ["Establish the current conditions in Kitengela", "Prepare the answer"],
        ["the temperature for Kitengela from a named source, dated today", ""],
        plan_objective="the user wants the current weather in Kitengela",
    )
    events = obs.drain_matching({"todo_created", "todo_cleared", "todo_completed"})
    cleared = [e for e in events if e.type == "todo_cleared"]
    assert cleared, "a new plan replaces whatever the session showed before"
    created = [e.data for e in events if e.type == "todo_created" and e.data.get("id") == "plan-0"]
    assert created, "the drawn plan seeds the panel"
    d = created[0]
    assert d["status"] == "pending"
    assert d["expected_outcome"] == (
        "the temperature for Kitengela from a named source, dated today"
    )
    assert d["text"] == "Establish the current conditions in Kitengela"


def test_runtime_plan_outcomes_become_the_gate_criteria():
    """No explicit success_criteria from the caller → the Planner's per-todo
    contract IS the completion contract: the trace's criteria carry the
    'step — done when: outcome' strings, and the turn's answer satisfies the
    evidence-token check."""
    _chunks, obs = _planned_run(
        ["Establish the current conditions in Kitengela"],
        ["the temperature for Kitengela from a source, dated today"],
    )
    # The loop is driven through run() — assert via the trace side effects:
    # the final answer must have passed the gate (no [ACCEPTANCE GATE] replan
    # suffix) and the completion floor must not have fired.
    text = "".join(c.text or "" for c in _chunks)
    assert "Kitengela" in text
    assert "ACCEPTANCE GATE" not in text


# ── Adaptive plan revision (B-2026-11-02-2) ─────────────────────────────────


def _revision_adapter():
    """A stub adapter for the gate's replan call: returns a numbered revised
    plan on the chat channel (chat is a plain function returning the async
    generator — the adapter contract)."""

    def _chat(messages, *args, **kwargs):
        async def _stream():
            prompt = str(messages[-1].get("content", ""))
            if "REVISED" in prompt.upper() or "revised" in prompt.lower():
                yield StreamChunk(
                    text=(
                        "1. Re-query the source with the district name\n"
                        "2. Verify the reading against a second source\n"
                        "3. Prepare the answer"
                    ),
                    done=False,
                )
            else:
                yield StreamChunk(text="FAITHFUL the reply answers the request", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    adapter = MagicMock()
    adapter.chat = _chat
    return adapter


def test_plan_revision_cb_retires_and_adds_rows_once():
    """The gate's replan flows into plan_revision_cb: dropped work retires
    (status carried), new work appears, the diff is emitted — exactly one
    revision per turn even when the replan fires twice. A row the tool
    already closed with evidence keeps its outcome — history, not churn."""
    from adapters.ollama import ToolCallResult

    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        if seen["calls"] == 1:
            return ToolCallResult(tool_name="web_search", tool_args={"query": "ambient conditions"})

        async def _stream():
            yield StreamChunk(text="Some answer.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def dispatch(*args, **kwargs):
        # Evidence that quotes NO key token of the drawn criterion — the
        # gate must find it unmet and replan.
        return ToolResult(source="web", content="zephyr reports only"), False, 0

    adapter = _revision_adapter()
    adapter.chat_with_tools = chat_with_tools
    obs = ObsCollector()

    async def go():
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            return [
                c
                async for c in AgentLoop(adapter=MagicMock()).run(
                    messages=[{"role": "user", "content": "find the district reading"}],
                    intent=Intent.WEB_SEARCH,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=adapter,
                    obs=obs,
                    skip_planning=True,
                    plan_steps=["Fetch the reading", "Cross-check the almanac", "Prepare the answer"],
                    plan_outcomes=["the reading from a source", "", ""],
                )
            ], obs

    _chunks, obs = asyncio.run(go())
    events = obs.drain_matching({"todo_updated", "todo_created", "todo_revised"})
    retired = [e.data for e in events if e.type == "todo_updated" and e.data.get("status") == "retired"]
    revised = [e.data for e in events if e.type == "todo_revised"]
    added = [e.data for e in events if e.type == "todo_created" and e.data.get("status") == "pending"]
    assert retired, "dropped work retires explicitly, never vanishes"
    # The dropped row is the OPEN one the revised plan no longer needs —
    # the completed row keeps its evidence-backed outcome.
    assert [r.get("id") for r in retired] == ["plan-1"]
    assert all(r.get("result") for r in retired), "a retirement carries the discovery"
    assert revised and revised[0].get("added", 0) >= 1 and revised[0].get("retired", 0) == 1
    # One revision per turn: the second replan must not churn the panel again.
    assert len(revised) == 1
    assert added, "genuinely new work appears as rows"


# ── Objective-fidelity lane (B-2026-11-02-2) ────────────────────────────────


def _fidelity_adapter(reply: str):
    adapter = MagicMock()

    def _chat(messages, *args, **kwargs):
        async def _stream():
            yield StreamChunk(text=reply, done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    adapter.chat = _chat
    return adapter


def _run_lane(adapter, reply="The reply text.", request="Show yesterday's Arsenal result"):
    loop = AgentLoop(adapter=MagicMock())
    return asyncio.run(
        loop._objective_fidelity_lane(
            original_request=request,
            objective="UNDERSTANDING: yesterday's Arsenal result",
            reply=reply,
            active_adapter=adapter,
        )
    )


def test_fidelity_lane_faithful():
    out = _run_lane(_fidelity_adapter("FAITHFUL the reply gives the final score and competition"))
    assert out["ran"] and out["verdict"] == "faithful"


def test_fidelity_lane_drifted():
    out = _run_lane(_fidelity_adapter("DRIFTED the reply discusses the stadium instead of the result"))
    assert out["ran"] and out["verdict"] == "drifted"
    assert "stadium" in out["reason"]


def test_fidelity_lane_fail_open_on_error():
    adapter = MagicMock()
    adapter.chat = MagicMock(side_effect=RuntimeError("provider down"))
    out = _run_lane(adapter)
    assert out == {"ran": False}


def test_fidelity_lane_skips_empty_input():
    out = _run_lane(_fidelity_adapter("FAITHFUL x"), reply="")
    assert out == {"ran": False}


# ── BaseAgent forwards the new contract ─────────────────────────────────────


def test_base_agent_run_accepts_planner_contract():
    """The runtime passes plan_outcomes/plan_objective on EVERY parent turn —
    any BaseAgent.run() that drops them crashes the lane (the plan_steps
    regression, twice)."""
    import inspect

    from agents.base_agent import BaseAgent

    sig = inspect.signature(BaseAgent.run)
    assert "plan_outcomes" in sig.parameters
    assert "plan_objective" in sig.parameters


# ── The finalize sweep leaves retired rows closed ───────────────────────────


def test_finalize_leaves_retired_rows_closed():
    """A replan-retired row must not be flipped to 'blocked — Not reached':
    it closed deliberately, carrying the discovery (B-2026-11-02-2)."""
    from api.routes.chat import _finalize_plan_todos

    store = MagicMock()
    store.list_todos.return_value = [
        {"id": "plan-0", "completed": True, "status": "done"},
        {"id": "plan-1", "completed": False, "status": "retired", "result": "mooted by the discovery"},
        {"id": "plan-2", "completed": False, "status": "pending"},
    ]
    engine = MagicMock()
    engine._store = store
    import api.routes.chat as chat_routes

    old = chat_routes._engine
    chat_routes._engine = engine
    try:
        flipped = _finalize_plan_todos("s1", skip=False)
    finally:
        chat_routes._engine = old
    assert [f["id"] for f in flipped] == ["plan-2"]
    statuses = {c.args[1]: c.kwargs.get("status") for c in store.upsert_todo.call_args_list}
    assert statuses.get("plan-1") is None, "retired stays retired"
    assert statuses.get("plan-2") == "blocked"

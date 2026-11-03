"""The model's own plan rewrite (B-2026-11-02-2 remainder).

A mid-turn todo_write call is the model reshaping its own checklist. The
2026-11-02 contract it replaces: any write silently full-replaced the panel
(todo_cleared + one todo_created per item) — closed and retired rows
vanished, no revision diff landed on the record, and the acceptance contract
ignored the rewrite. These tests pin:

- the write DIFFS against the live panel rows (planner plan-{i} rows, the
  model's own previous list, or syn- fallback rows): dropped open rows
  retire with a reason, new work appends with fresh ids, closed rows never
  churn, todo_revised lands once per actual rewrite,
- the legacy fresh paths still apply (no live rows → clear + create; an
  explicit empty list → clear),
- revised steps carry outcomes: a model-supplied expected_outcome joins the
  acceptance contract, and the gate replan parses per-step done-when
  contracts into the added rows,
- a retired row takes no more lifecycle (the cursor's finalize never
  re-opens one).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from core.agent.loop import (
    AgentLoop,
    _diff_todo_lists,
    _parse_replan_contract,
    _split_done_when,
    _todo_text_equivalent,
)
from core.models import Intent, StreamChunk, ToolResult
from core.obs import ObsCollector
from tools.todo_write import todo_write as todo_write_tool

# ── The pure diff ────────────────────────────────────────────────────────────


def test_equivalence_rephrases_match():
    assert _todo_text_equivalent(
        "establish the current conditions in Kitengela",
        "establish the current conditions for Kitengela now",
    )
    assert _todo_text_equivalent(
        "check the wind forecast", "check the wind forecast for Kitengela"
    )
    assert not _todo_text_equivalent("fetch the weather", "deploy the service")


def test_diff_matches_by_id_then_text():
    current = [
        {"id": "plan-0", "text": "Establish the current conditions", "status": "pending"},
        {"id": "plan-1", "text": "Prepare the answer", "status": "pending"},
    ]
    out = _diff_todo_lists(
        current,
        [
            {"text": "establish the current conditions now", "status": "in_progress"},
            {"text": "Prepare the answer", "status": "completed"},
        ],
    )
    assert out["creates"] == []
    assert out["retires"] == []
    assert {u["id"] for u in out["updates"]} == {"plan-0", "plan-1"}
    assert out["updates"][0]["status"] == "in_progress"


def test_diff_retires_dropped_open_rows():
    current = [
        {"id": "plan-0", "text": "Fetch the reading", "status": "pending"},
        {"id": "plan-1", "text": "Cross-check the almanac", "status": "pending"},
    ]
    out = _diff_todo_lists(current, [{"text": "Fetch the reading", "status": "pending"}])
    assert out["retires"] == ["plan-1"]
    assert out["creates"] == []


def test_diff_closed_rows_never_churn():
    current = [
        {"id": "plan-0", "text": "Fetch the reading", "status": "completed"},
        {"id": "plan-1", "text": "Cross-check the almanac", "status": "failed"},
        {"id": "plan-2", "text": "Old detour", "status": "retired"},
        {"id": "plan-3", "text": "Prepare the answer", "status": "pending"},
    ]
    out = _diff_todo_lists(
        current,
        [
            # the model's explicit id mapping keeps the closed row closed
            {"id": "plan-0", "text": "Fetch the reading", "status": "pending"},
            {"text": "Prepare the answer", "status": "pending"},
        ],
        existing_ids={"plan-0", "plan-1", "plan-2", "plan-3"},
    )
    assert out["kept"] == 1, "the id-matched completed row is kept, never reopened"
    assert out["retires"] == [], "closed rows are never re-retired"
    assert [u["id"] for u in out["updates"]] == ["plan-3"]


def test_relisted_closed_work_arrives_as_new_row():
    """Closed rows match only by explicit id: re-listing completed work as
    open is the model re-adding the work — a fresh row, the closed one stays
    as history."""
    current = [
        {"id": "plan-0", "text": "Fetch the reading", "status": "completed"},
        {"id": "plan-1", "text": "Old detour", "status": "retired"},
    ]
    out = _diff_todo_lists(
        current,
        [{"text": "Fetch the reading", "status": "pending"}],
        existing_ids={"plan-0", "plan-1"},
    )
    assert len(out["creates"]) == 1
    assert out["creates"][0]["text"] == "Fetch the reading"
    assert out["updates"] == [] and out["retires"] == []


def test_diff_creates_fresh_ids_without_collision():
    current = [{"id": "plan-0", "text": "A first step", "status": "pending"}]
    out = _diff_todo_lists(
        current,
        [
            {"text": "A first step", "status": "pending"},
            {"text": "Brand new work", "status": "pending", "expected_outcome": "the work is done"},
        ],
        id_prefix="plan-",
        existing_ids={"plan-0"},
    )
    assert len(out["creates"]) == 1
    assert out["creates"][0]["id"] == "plan-1"
    assert out["creates"][0]["expected_outcome"] == "the work is done"


def test_diff_relisted_retired_row_becomes_new_work():
    current = [{"id": "plan-0", "text": "Old detour", "status": "retired"}]
    out = _diff_todo_lists(current, [{"text": "Old detour", "status": "pending"}])
    assert out["creates"], "re-opening retired work is the model's call — it arrives as a new row"
    assert out["retires"] == []


# ── The gate replan's done-when contracts ───────────────────────────────────


def test_split_done_when_variants():
    assert _split_done_when("fetch X — done when: the reading appears") == (
        "fetch X",
        "the reading appears",
    )
    assert _split_done_when("fetch X - done when: the reading appears")[1] == "the reading appears"
    assert _split_done_when("fetch X done when: the reading appears")[1] == "the reading appears"
    assert _split_done_when("just a step") == ("just a step", "")


def test_parse_replan_contract_bare_steps_backward_compatible():
    steps, outcomes = _parse_replan_contract(
        "1. Re-query the source with the district name\n2. Verify the reading\n"
    )
    assert steps == ["Re-query the source with the district name", "Verify the reading"]
    assert outcomes == ["", ""]


def test_parse_replan_contract_parses_done_when():
    steps, outcomes = _parse_replan_contract(
        "1. Re-query the source with the district name — done when: the district "
        "reading appears in the page text\n"
        "2. Prepare the answer\n"
    )
    assert steps[0] == "Re-query the source with the district name"
    assert outcomes[0] == "the district reading appears in the page text"
    assert outcomes[1] == ""


# ── The loop-level rewrite ───────────────────────────────────────────────────


def _rewrite_run(plan_steps, plan_outcomes, write_payloads, final_reply="Some answer."):
    """Drive AgentLoop.run exactly the way the runtime's warm-kernel path does
    (skip_planning=True + a caller-drawn plan). The model calls todo_write
    once per payload in `write_payloads`, then answers."""
    from adapters.ollama import ToolCallResult

    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        if seen["calls"] <= len(write_payloads):
            return ToolCallResult(
                tool_name="todo_write",
                tool_args={"todos": write_payloads[seen["calls"] - 1]},
            )

        async def _stream():
            yield StreamChunk(text=final_reply, done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def dispatch(*args, **kwargs):
        tool_input = str(args[1]) if len(args) > 1 else str(kwargs.get("tool_input", ""))
        if "todos" in tool_input or tool_input.strip().startswith("["):
            return await todo_write_tool(tool_input), False, 0
        return ToolResult(source="web", content="some tool evidence"), False, 0

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
                )
            ], obs

    return asyncio.run(go())


async def _empty_agen():
    if False:
        yield StreamChunk(text="", done=True)


def _todo_events(obs, types={"todo_created", "todo_updated", "todo_completed", "todo_cleared", "todo_revised"}):
    return obs.drain_matching(types)


def test_rewrite_diffs_planner_rows_instead_of_replacing():
    """The model reshapes the drawn plan: its dropped row retires with the
    reason, its new work appends with a fresh id, the kept row updates in
    place — and nothing is cleared."""
    _chunks, obs = _rewrite_run(
        ["Establish the current conditions in Kitengela", "Prepare the answer"],
        ["the temperature from a named source", ""],
        [
            [
                {"text": "establish the current conditions in Kitengela now", "status": "in_progress"},
                {"text": "Also check the wind forecast", "status": "pending",
                 "expected_outcome": "the wind speed for Kitengela from a named source"},
            ]
        ],
    )
    events = _todo_events(obs)
    cleared = [e for e in events if e.type == "todo_cleared"]
    assert len(cleared) == 1, "only the plan seeding clears; the rewrite itself adds none"
    retired = [e.data for e in events if e.type == "todo_updated" and e.data.get("status") == "retired"]
    assert [r.get("id") for r in retired] == ["plan-1"]
    assert retired[0].get("result"), "the retirement carries its reason"
    updated = [e.data for e in events if e.type == "todo_updated" and e.data.get("id") == "plan-0"]
    assert updated and updated[-1].get("status") == "in_progress"
    created = [e.data for e in events if e.type == "todo_created" and e.data.get("id") == "plan-2"]
    assert created, "genuinely new work appends with a fresh id"
    assert created[0]["text"] == "Also check the wind forecast"
    assert created[0]["expected_outcome"] == "the wind speed for Kitengela from a named source"
    revised = [e.data for e in events if e.type == "todo_revised"]
    assert revised and revised[0] == {"added": 1, "retired": 1, "kept": 1}


def test_second_rewrite_diffs_against_the_model_list():
    """After the first write the model's list IS the panel: the second write
    diffs against it (ids t-family), not against the drawn plan."""
    _chunks, obs = _rewrite_run(
        ["Establish the current conditions in Kitengela"],
        [""],
        [
            [
                {"text": "Check the wind forecast", "status": "pending"},
                {"text": "Prepare the answer", "status": "pending"},
            ],
            [
                {"text": "Prepare the answer", "status": "in_progress"},
            ],
        ],
    )
    events = _todo_events(obs)
    retired = [e.data for e in events if e.type == "todo_updated" and e.data.get("status") == "retired"]
    # First write retired the planner row; second write retired the model's
    # own dropped row ("Check the wind forecast" — id t1).
    assert retired, "dropped rows retire on both triggers"
    assert any(r.get("id") == "t1" for r in retired), "the model list is the diff base after the first write"
    revised = [e.data for e in events if e.type == "todo_revised"]
    assert len(revised) == 2, "each actual rewrite lands its own diff"


def test_write_without_live_rows_is_the_fresh_list():
    """No plan, no synth rows, no earlier write: the legacy clear + create —
    a list born this way has nothing to retire."""
    _chunks, obs = _rewrite_run(
        [],
        [],
        [[{"text": "Fetch the reading", "status": "pending"}]],
    )
    events = _todo_events(obs)
    assert [e for e in events if e.type == "todo_cleared"]
    created = [e.data for e in events if e.type == "todo_created"]
    assert [c.get("id") for c in created] == ["t1"]
    assert not [e for e in events if e.type == "todo_revised"]


def test_empty_write_clears_legacy():
    _chunks, obs = _rewrite_run(
        ["Establish the current conditions in Kitengela"],
        [""],
        [[]],
    )
    events = _todo_events(obs)
    assert [e for e in events if e.type == "todo_cleared"], "an explicit empty write still clears"
    assert not [e for e in events if e.type == "todo_revised"]


def test_rewrite_over_synth_rows_diffs_them():
    """The syn- fallback rows are the live panel before the model writes:
    rows the rewrite keeps stay, new work appends — no silent re-create."""
    from adapters.ollama import ToolCallResult

    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        if seen["calls"] == 1:
            return ToolCallResult(tool_name="web_search", tool_args={"query": "ambient conditions"})
        if seen["calls"] == 2:
            return ToolCallResult(
                tool_name="todo_write",
                tool_args={"todos": [{"text": "Search the wind forecast", "status": "pending"}]},
            )

        async def _stream():
            yield StreamChunk(text="Some answer.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def dispatch(*args, **kwargs):
        tool_input = str(args[1]) if len(args) > 1 else str(kwargs.get("tool_input", ""))
        if "todos" in tool_input:
            return await todo_write_tool(tool_input), False, 0
        return ToolResult(source="web", content="some tool evidence"), False, 0

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = lambda *a, **k: _empty_agen()
    obs = ObsCollector()

    async def go():
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            return [
                c
                async for c in AgentLoop(adapter=MagicMock()).run(
                    messages=[{"role": "user", "content": "wind in Kitengela"}],
                    intent=Intent.WEB_SEARCH,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=adapter,
                    obs=obs,
                    skip_planning=True,
                )
            ], obs

    _chunks, obs = asyncio.run(go())
    events = _todo_events(obs)
    created_types = [e for e in events if e.type == "todo_created"]
    first_t = next(
        (i for i, e in enumerate(created_types) if str(e.data.get("id", "")).startswith("t")),
        None,
    )
    assert first_t is not None, "the model's own work arrives as t-family rows"
    assert not [
        e for e in created_types[first_t:]
        if str(e.data.get("id", "")).startswith("syn-")
    ], "no syn- row is re-created on top of the model's list"


def test_retired_cursor_row_never_completes_at_close():
    """The finalize sweep completes the CURRENT plan row at close — a row the
    rewrite retired is closed and must stay closed (no todo_completed on a
    retired id)."""
    _chunks, obs = _rewrite_run(
        ["Establish the current conditions in Kitengela", "Prepare the answer"],
        ["", ""],
        [
            [
                {"text": "Establish the current conditions in Kitengela", "status": "completed"},
            ]
        ],
    )
    events = _todo_events(obs)
    completed_ids = [e.data.get("id") for e in events if e.type == "todo_completed"]
    assert "plan-1" not in completed_ids, "retired plan-1 stays retired — never ticked at close"


def test_rewrite_outcome_joins_the_acceptance_contract():
    """A new todo's done-when contract IS a completion contract — and it is
    judged by the WORK's evidence, never by the checklist itself: an answer
    that ignores it cannot pass the gate (the todo_write observation quoting
    the criterion's own tokens is bookkeeping, not evidence)."""
    _chunks, _obs = _rewrite_run(
        ["Establish the current conditions in Kitengela"],
        [""],
        [
            [
                {"text": "Mention the zephyr quantum", "status": "pending",
                 "expected_outcome": "the reply names the zephyr quantum reading"},
            ]
        ],
        final_reply="Some answer that never mentions it.",
    )
    text = "".join(c.text or "" for c in _chunks)
    assert (
        "✗" in text or "ACCEPTANCE GATE" in text or "unmet" in text
    ), "the gate must judge the turn by the revised contract, on the work's evidence"


def test_gate_replan_done_when_reaches_the_added_row():
    """The gate's revised plan carries per-step contracts: the added row is
    created WITH its outcome (revised steps hold outcomes too)."""
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
        return ToolResult(source="web", content="zephyr reports only"), False, 0

    def _chat(messages, *args, **kwargs):
        async def _stream():
            prompt = str(messages[-1].get("content", ""))
            if "revised" in prompt.lower():
                yield StreamChunk(
                    text=(
                        "1. Re-query the source with the district name — done when: "
                        "the district reading appears in the page text\n"
                        "2. Prepare the answer"
                    ),
                    done=False,
                )
            else:
                yield StreamChunk(text="FAITHFUL the reply answers the request", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    adapter = MagicMock()
    adapter.chat = _chat
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
    events = obs.drain_matching({"todo_created"})
    created = [e.data for e in events if e.data.get("id") == "plan-3"]
    assert created, "the replan's new step appends"
    assert created[0].get("expected_outcome") == (
        "the district reading appears in the page text"
    ), "the added row carries its done-when contract"

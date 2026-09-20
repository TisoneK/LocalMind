"""The turn bus: processes working on one goal publish facts and never call or
await each other; only `gate()` blocks, and only for named lanes, bounded."""
from __future__ import annotations

import asyncio
import dataclasses
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop, _absorb_thinker_analysis
from core.agent.thinker.contract import ThinkerAnalysis
from core.agent.turn_bus import TurnBus
from core.models import Intent, RiskLevel, StreamChunk, ToolResult
from core.obs import ObsCollector

# ── the bus ────────────────────────────────────────────────────────────────


def test_facts_are_appended_with_provenance_and_never_edited():
    bus = TurnBus()
    a = bus.publish("thinker", "analysis", {"n": 1}, step=2, grounded_in=("step:2",))
    b = bus.publish("system_tool", "state", "exists", step=2)
    assert (a.seq, b.seq) == (1, 2)
    assert (a.source, a.kind, a.step, a.goal_version, a.grounded_in) == ("thinker", "analysis", 2, 0, ("step:2",))
    assert bus.log() == [a, b]
    assert bus.facts(source="system_tool") == [b]
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.value = "changed"  # frozen: a correction is a NEW fact


def test_a_replan_makes_facts_about_the_old_plan_stale_but_keeps_them_on_record():
    bus = TurnBus()
    old = bus.publish("thinker", "analysis", "about plan 0", step=1)
    assert bus.latest("analysis") is old
    assert bus.replan() == 1
    assert bus.latest("analysis") is None and bus.facts(kind="analysis") == []
    assert bus.facts(kind="analysis", include_stale=True) == [old]
    new = bus.publish("thinker", "analysis", "about plan 1", step=3)
    assert bus.latest("analysis") is new


def test_a_slow_process_that_started_before_the_replan_publishes_a_stale_fact():
    seen = []
    bus = TurnBus(on_fact=lambda fact, stale: seen.append((fact.value, stale)))
    started_under = bus.goal_version
    bus.replan()
    late = bus.publish("thinker", "analysis", "late", step=1, goal_version=started_under)
    assert bus.is_stale(late) and bus.latest("analysis") is None
    assert seen == [("late", True)]


def test_cursor_reads_only_what_arrives_after_it():
    bus = TurnBus()
    bus.publish("a", "k", 1, step=0)
    c = bus.cursor()
    bus.publish("b", "k", 2, step=0)
    assert [f.value for f in bus.facts(since=c)] == [2]


@pytest.mark.asyncio
async def test_wait_for_returns_a_fact_published_later_and_none_on_timeout():
    bus = TurnBus()

    async def later():
        await asyncio.sleep(0.05)
        bus.publish("verifier", "verdict", "ok", step=4)

    asyncio.create_task(later())
    got = await bus.wait_for("verdict", step=4, timeout=2)
    assert got is not None and got.value == "ok"
    assert await bus.wait_for("never", timeout=0.05) is None


@pytest.mark.asyncio
async def test_lanes_run_concurrently_so_the_goal_waits_for_the_slowest_not_the_sum():
    bus = TurnBus()

    async def work(d):
        await asyncio.sleep(d)

    started = time.monotonic()
    for name in ("thinker", "verify", "reflect"):
        bus.track(name, asyncio.create_task(work(0.3)), step=1)
    assert bus.in_flight() == ["reflect", "thinker", "verify"]
    res = await bus.gate(["thinker", "verify", "reflect"], timeout=2)
    assert res.ok and sorted(res.finished) == ["reflect", "thinker", "verify"]
    assert time.monotonic() - started < 0.7  # ~0.3, not 0.9
    assert bus.in_flight() == []


@pytest.mark.asyncio
async def test_a_failing_lane_publishes_an_error_fact_and_never_raises_into_the_loop():
    bus = TurnBus()

    async def boom():
        raise RuntimeError("provider exploded")

    bus.track("thinker", asyncio.create_task(boom()), step=3)
    await asyncio.sleep(0.05)
    err = bus.latest("error", source="thinker")
    assert err is not None and "provider exploded" in err.value and err.step == 3


@pytest.mark.asyncio
async def test_gate_is_bounded_reports_the_lane_that_timed_out_and_cancels_nothing():
    bus = TurnBus()
    slow = asyncio.create_task(asyncio.sleep(5))
    bus.track("verify", slow, step=1)
    started = time.monotonic()
    res = await bus.gate(["verify", "not-running"], timeout=0.1)
    assert time.monotonic() - started < 1
    assert res.timed_out == ["verify"] and "not-running" in res.finished and not res.ok
    assert not slow.done()  # left running: the caller decides what a missing verdict means
    bus.cancel_all()
    await asyncio.sleep(0)


# ── the loop uses it ───────────────────────────────────────────────────────


def _analysis():
    return ThinkerAnalysis(reasoning="r", facts=["two folders found"], next_step="answer")


def test_a_fresh_analysis_is_injected_and_recorded_as_a_fact():
    bus, obs, msgs = TurnBus(), ObsCollector(), []
    trace = SimpleNamespace(thinker_analysis="")
    _absorb_thinker_analysis(msgs, trace, obs, _analysis(), 2, bus=bus, goal_version=0)
    assert any("[THINKER ANALYSIS]" in m["content"] for m in msgs)
    fact = bus.latest("analysis", source="thinker")
    assert fact is not None and fact.step == 2 and fact.grounded_in == ("step:2",)
    assert not any(e.type == "agent_thinker_dropped_stale" for e in obs.history())


def test_an_analysis_that_answers_a_replaced_plan_is_dropped_not_injected():
    bus, obs, msgs = TurnBus(), ObsCollector(), []
    trace = SimpleNamespace(thinker_analysis="")
    started_under = bus.goal_version
    bus.replan()  # the acceptance gate re-planned while the consult was running
    _absorb_thinker_analysis(msgs, trace, obs, _analysis(), 2, bus=bus, goal_version=started_under)
    assert msgs == [] and trace.thinker_analysis == ""
    assert any(e.type == "agent_thinker_dropped_stale" for e in obs.history())
    assert bus.latest("analysis") is None
    assert len(bus.facts(kind="analysis", include_stale=True)) == 1  # still on the record


def test_without_a_bus_absorb_behaves_as_before():
    msgs, trace = [], SimpleNamespace(thinker_analysis="")
    _absorb_thinker_analysis(msgs, trace, None, _analysis(), 1)
    assert any("[THINKER ANALYSIS]" in m["content"] for m in msgs)


@pytest.mark.asyncio
async def test_a_turn_publishes_the_thinker_verdict_to_the_bus_and_the_next_call_sees_it():
    from agents.base_agent import AgentConfig
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    class _Thinker:
        def __init__(self, timeout_secs=30.0):
            self.last_analysis = None

        async def consult(self, evidence, adapter, temperature=0.4):
            self.last_analysis = _analysis()
            yield StreamChunk(text="", thinking="two folders", done=False)
            yield StreamChunk(text="", done=True)

    n = {"i": 0}
    seen = []

    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        n["i"] += 1
        seen.append(" ".join(str(m.get("content", "")) for m in messages if m.get("role") == "user"))
        if n["i"] <= 2:  # two tools, so a consult started after the first is absorbed at the third call's head
            await asyncio.sleep(0.05)  # the model call the consult overlaps
            return ToolCallResult(
                tool_name="dir_explorer", tool_args={"operation": "list", "path": f"/x{n['i']}"}, raw_content=""
            )

        async def gen():
            yield StreamChunk(text="alpha and beta", done=False)
            yield StreamChunk(text="", done=True)

        return gen()

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kw):
        return ToolResult(content="Contents of /x — 2 entries: alpha/, beta/", risk=RiskLevel.LOW, source="dir_explorer"), False, 0

    adapter = MagicMock()
    adapter.chat_with_tools = chat
    adapter.chat = lambda *a, **k: iter(())
    adapter.thinking_enabled = True
    obs = ObsCollector()
    cfg = AgentConfig(name="parent", max_iterations=20, allowed_tools=AGENT_ALLOWED_TOOLS)
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", side_effect=dispatch), \
         patch("core.agent.thinker.Thinker", _Thinker):
        async for _ in AgentLoop(adapter=MagicMock()).run(
            messages=[{"role": "user", "content": "list /x"}], intent=Intent.ANALYZE, initial_tool_result=None,
            available_tools=[], adapter=adapter, obs=obs, agent_config=cfg, skip_planning=True,
        ):
            pass

    facts = [e.data for e in obs.history() if e.type == "bus_fact"]
    assert any(f["source"] == "thinker" and f["kind"] == "analysis" and f["stale"] is False for f in facts)
    assert any("[THINKER ANALYSIS]" in t for t in seen[2:]), "a later call must see the analysis"

"""Post-answer services (fact extraction, reflection) run inside one shared time
budget. Live capture: a reflection request that never returned held the turn open
for 9 minutes after the answer was already finished."""
from __future__ import annotations

import asyncio
import time

import pytest

import core.engine  # noqa: F401  (import order: agent_runtime resolves its cycle via engine)
from core.agent_runtime import _run_bounded_services
from core.obs import ObsCollector


def _events(obs):
    return [(e.type, e.data) for e in obs.history()]


@pytest.mark.asyncio
async def test_a_hung_service_is_cut_off_and_reported():
    obs, ran = ObsCollector(), []

    async def facts():
        ran.append("facts")

    async def reflection():
        await asyncio.sleep(30)  # the provider call that never returns

    started = time.monotonic()
    await _run_bounded_services([("fact_extraction", facts), ("reflection", reflection)], 0.3, obs)
    assert time.monotonic() - started < 2
    assert ran == ["facts"]
    assert _events(obs) == [("post_turn_timeout", {"service": "reflection", "budget_s": 0.3, "skipped": False})]


@pytest.mark.asyncio
async def test_healthy_services_all_run_in_order_and_emit_nothing():
    obs, order = ObsCollector(), []

    async def a():
        order.append("a")

    async def b():
        await asyncio.sleep(0.01)
        order.append("b")

    await _run_bounded_services([("a", a), ("b", b)], 5, obs)
    assert order == ["a", "b"] and _events(obs) == []


@pytest.mark.asyncio
async def test_budget_is_shared_so_a_spent_budget_skips_the_rest():
    obs, ran = ObsCollector(), []

    async def slow():
        await asyncio.sleep(30)

    async def later():
        ran.append("later")

    await _run_bounded_services([("slow", slow), ("later", later)], 0.2, obs)
    assert ran == []
    assert [d["service"] for t, d in _events(obs)] == ["slow", "later"]
    assert _events(obs)[1][1]["skipped"] is True


@pytest.mark.asyncio
async def test_one_failing_service_does_not_stop_the_next():
    obs, ran = ObsCollector(), []

    async def boom():
        raise RuntimeError("extraction failed")

    async def ok():
        ran.append("ok")

    await _run_bounded_services([("boom", boom), ("ok", ok)], 5, obs)
    assert ran == ["ok"] and _events(obs) == []


@pytest.mark.asyncio
async def test_cancelling_the_turn_is_not_swallowed():
    obs = ObsCollector()

    async def slow():
        await asyncio.sleep(30)

    task = asyncio.create_task(_run_bounded_services([("slow", slow)], 60, obs))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_budget_default_is_generous_but_finite():
    from core.agent.constants import POST_TURN_LLM_BUDGET_S

    assert 30 <= POST_TURN_LLM_BUDGET_S <= 300

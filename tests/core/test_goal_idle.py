"""Tests for the idle continuation driver (``core/goal_idle.py``) — the
goal deep-dive that survives a dropped transport.

Contract locked here:
  - scheduling is an intention re-checked at wake: no goal, no activation,
    a busy session, a human cease, or a non-resumable driver stop each
    refuse it;
  - the driver runs the remaining rounds as background engine turns on the
    same session, consuming the durable round allowance by admission, and
    records the same durable round-limit blocker at the cap;
  - a human steer, a pending write confirmation and a busy session each
    stop the driver instead of working over the human;
  - a crashed round fails CLOSED — the session disarms, nothing loops;
  - the human resume affordance re-arms and hands off to the driver — the
    one thing that revives a disarmed goal (the restart-safety analogue:
    a fresh process's empty registry never schedules on its own).
"""

from __future__ import annotations

import asyncio

import pytest

from core import goal_idle, goal_rounds
from core.goal_idle import (
    cancel_idle_continuation,
    clear_human_stop,
    idle_continuation_pending,
    note_human_stop,
    note_session_busy,
    release_session_busy,
    resume_for_human,
    schedule_idle_continuation,
)
from core.models import StreamChunk
from storage.goals import GoalStore

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def clean_idle_state():
    goal_rounds._armed.clear()
    goal_rounds._active_rounds.clear()
    goal_rounds._steered.clear()
    goal_rounds._stop_reasons.clear()
    goal_idle._busy.clear()
    goal_idle._human_stopped.clear()
    for task in list(goal_idle._pending.values()):
        task.cancel()
    goal_idle._pending.clear()
    yield
    for task in list(goal_idle._pending.values()):
        task.cancel()
    goal_idle._pending.clear()
    goal_rounds._armed.clear()
    goal_rounds._active_rounds.clear()
    goal_rounds._steered.clear()
    goal_rounds._stop_reasons.clear()
    goal_idle._busy.clear()
    goal_idle._human_stopped.clear()


class FakeStore:
    """The trace-persist sink the idle round writes to."""

    def __init__(self):
        self.traces: list[tuple[str, str, int]] = []

    def append_turn_trace(self, session_id: str, turn_id: str, events: list):
        self.traces.append((session_id, turn_id, len(events)))
        return len(events)


class FakeEngine:
    """One `process()` per background round; `on_turn` drives the goal."""

    def __init__(self, on_turn=None):
        self.messages: list[str] = []
        self._on_turn = on_turn
        self._abort = asyncio.Event()
        self._store = FakeStore()
        self.pending_write_on: int | None = None

    def _abort_for(self, session_id: str) -> asyncio.Event:
        return self._abort

    async def process(self, message: str, session_id: str, **kwargs):
        self.messages.append(message)
        turn = len(self.messages)
        if self._on_turn is not None:
            self._on_turn(turn, session_id)
        metadata = {"pending_write": True} if turn == self.pending_write_on else {}
        yield StreamChunk(text=f"idle round {turn}")
        yield StreamChunk(text="", done=True, metadata=metadata)


async def _await_driver(session_id: str, timeout: float = 5.0) -> None:
    task = goal_idle._pending.get(session_id)
    assert task is not None, "no idle driver scheduled"
    await asyncio.wait_for(asyncio.shield(task), timeout=timeout)


def _armed_goal(store: GoalStore, session: str, objective: str = "Keep digging", max_rounds: int = 8):
    store.create(f"goal-{session}", session, objective, max_rounds=max_rounds)
    goal_rounds.arm(session)
    return store.get(session)


# ── the schedule decision ─────────────────────────────────────────────────────


async def test_schedule_refuses_without_a_goal(tmp_db):
    store = GoalStore(tmp_db)
    engine = FakeEngine()
    assert schedule_idle_continuation(engine, "sess-a", store) is False
    assert not idle_continuation_pending("sess-a")


async def test_schedule_refuses_when_disarmed(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-disarmed"
    store.create("goal-d", session, "Objective")  # active but NOT armed
    engine = FakeEngine()
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is False


async def test_schedule_refuses_while_busy(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-busy"
    _armed_goal(store, session)
    note_session_busy(session)
    engine = FakeEngine()
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is False
    release_session_busy(session)
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is True
    await _await_driver(session)


async def test_schedule_refuses_on_human_stop_and_clears_on_return(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-stop"
    _armed_goal(store, session)
    note_human_stop(session)
    engine = FakeEngine()
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is False
    clear_human_stop(session)
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is True
    await _await_driver(session)


async def test_schedule_refuses_on_non_resumable_driver_stop(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-steer-stop"
    _armed_goal(store, session)
    goal_rounds.note_driver_stop(session, "steer")
    engine = FakeEngine()
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is False


# ── the driver itself ─────────────────────────────────────────────────────────


async def test_idle_driver_runs_rounds_until_the_goal_completes(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-run"
    goal = _armed_goal(store, session)

    def complete_on_second(turn, sid):
        if turn == 2:
            current = store.get(sid)
            store.set_phase(sid, current.id, current.revision, "complete")

    engine = FakeEngine(complete_on_second)
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is True
    await _await_driver(session)

    # the human turn (round 1) already happened in the transport; the idle
    # driver continues from round 2 until completion.
    assert len(engine.messages) == 2
    assert "<goal_round>" in engine.messages[1]
    # the first IDLE round is overall round 2 (the human turn was round 1)
    assert "Round: 2/" in engine.messages[1]
    assert store.get(session).phase == "complete"
    # every background round is on the durable trace
    assert len(engine._store.traces) == len(engine.messages)
    assert all(t[0] == session for t in engine._store.traces)


async def test_idle_driver_blocks_at_the_cap(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-cap"
    _armed_goal(store, session, max_rounds=2)
    engine = FakeEngine()
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is True
    await _await_driver(session)
    final = store.get(session)
    assert final.phase == "blocked"
    assert "round-limit" in (final.blocked_reason or "")
    assert not goal_rounds.is_armed(session)


async def test_idle_driver_yields_to_a_human_steer(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-steer"
    _armed_goal(store, session)
    goal_rounds.note_human_steer(session)
    engine = FakeEngine()
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is True
    await _await_driver(session)
    assert engine.messages == []  # never fired over the human
    # the steer REMAINS unconsumed: it belongs to the transport's own
    # round driver, which yields at its next idle point
    assert goal_rounds.has_human_steer(session) is True


async def test_idle_driver_stops_on_a_pending_write(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-pending"
    _armed_goal(store, session)
    engine = FakeEngine()
    engine.pending_write_on = 1  # the first idle round asks for confirmation
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is True
    await _await_driver(session)
    assert len(engine.messages) == 1
    # the goal stays armed: the next human turn re-drives the deep dive
    assert goal_rounds.is_armed(session)
    assert goal_rounds.last_driver_stop(session) == "pending_write"


async def test_idle_driver_yields_when_a_transport_takes_over(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-takeover"
    _armed_goal(store, session)

    def busy_on_first(turn, sid):
        if turn == 1:
            note_session_busy(sid)

    engine = FakeEngine(busy_on_first)
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is True
    await _await_driver(session)
    assert len(engine.messages) == 1
    assert goal_rounds.last_driver_stop(session) == "yielded_to_transport"
    release_session_busy(session)


async def test_idle_driver_fails_closed_on_a_crashed_round(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-crash"

    class CrashingEngine(FakeEngine):
        async def process(self, message: str, session_id: str, **kwargs):
            raise RuntimeError("provider exploded")

    _armed_goal(store, session)
    engine = CrashingEngine()
    assert schedule_idle_continuation(engine, session, store, delay=0.01) is True
    await _await_driver(session)
    assert not goal_rounds.is_armed(session)
    assert store.get(session).phase == "active"  # the goal stays on record


async def test_a_fresh_message_cancels_a_pending_driver(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-cancel"
    _armed_goal(store, session)
    engine = FakeEngine()
    assert schedule_idle_continuation(engine, session, store, delay=30.0) is True
    assert idle_continuation_pending(session)
    # the transport turn's first act: cancel + busy fence
    cancel_idle_continuation(session)
    note_session_busy(session)
    await asyncio.sleep(0.05)
    assert engine.messages == []
    release_session_busy(session)


# ── the human resume affordance ───────────────────────────────────────────────


async def test_resume_for_human_rearms_and_continues(tmp_db):
    store = GoalStore(tmp_db)
    session = "sess-resume"
    goal = _armed_goal(store, session)
    goal_rounds.disarm(session)  # e.g. a restart wiped the activation

    def complete_on_first_idle_turn(turn, sid):
        current = store.get(sid)
        store.set_phase(sid, current.id, current.revision, "complete")

    engine = FakeEngine(complete_on_first_idle_turn)
    view = resume_for_human(engine, session, store, delay=0.01)
    assert view is not None and view["armed"] is True
    await _await_driver(session)
    assert len(engine.messages) == 1
    assert "<goal_round>" in engine.messages[0]


async def test_resume_for_human_returns_none_without_a_goal(tmp_db):
    store = GoalStore(tmp_db)
    engine = FakeEngine()
    assert resume_for_human(engine, "sess-nothing", store, delay=0.01) is None

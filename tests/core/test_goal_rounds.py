"""Tests for the same-session goal-round driver."""

from __future__ import annotations

import asyncio

import pytest

from core import goal_rounds
from core.goal_rounds import process_with_goal_rounds
from core.models import StreamChunk
from storage.goals import GoalStore

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def clean_process_state():
    goal_rounds._armed.clear()
    goal_rounds._active_rounds.clear()
    goal_rounds._steered.clear()
    yield
    goal_rounds._armed.clear()
    goal_rounds._active_rounds.clear()
    goal_rounds._steered.clear()


class FakeEngine:
    """One `process()` call per engine turn; `on_turn` inspects/mutates state."""

    def __init__(self, on_turn=None):
        self.messages: list[str] = []
        self._on_turn = on_turn
        self._abort = asyncio.Event()

    def _abort_for(self, session_id: str) -> asyncio.Event:
        return self._abort

    async def process(self, message: str, session_id: str, **kwargs):
        self.messages.append(message)
        if self._on_turn is not None:
            self._on_turn(len(self.messages), session_id)
        yield StreamChunk(text=f"round {len(self.messages)}")
        yield StreamChunk(text="", done=True, metadata={})


async def collect(engine: FakeEngine, store: GoalStore, session_id: str, message: str = "do the thing"):
    chunks = []
    async for chunk in process_with_goal_rounds(engine, message, session_id, store):
        chunks.append(chunk)
    return chunks


async def test_driver_runs_only_the_human_turn_when_no_goal_exists(tmp_db):
    store = GoalStore(tmp_db)
    engine = FakeEngine()
    chunks = await collect(engine, store, "session-none")

    assert len(engine.messages) == 1
    # A goal-less chat emits no synthetic control event: the transport's
    # first event must stay the engine's own acknowledgement.
    assert chunks[0].text == "round 1"
    assert chunks[-1].done
    assert chunks[-1].metadata["goal"] is None


async def test_driver_stops_when_the_goal_completes(tmp_db):
    store = GoalStore(tmp_db)
    session = "session-complete"
    store.create("goal-complete", session, "Ship the parser")
    goal_rounds.arm(session)

    def complete(_turn, sid):
        current = store.get(sid)
        store.set_phase(sid, current.id, current.revision, "complete")

    engine = FakeEngine(complete)
    chunks = await collect(engine, store, session)

    assert len(engine.messages) == 1
    assert sum(1 for chunk in chunks if chunk.done) == 1
    assert chunks[-1].metadata["goal"]["phase"] == "complete"
    assert not goal_rounds.is_armed(session)


async def test_driver_queues_goal_rounds_until_the_goal_completes(tmp_db):
    store = GoalStore(tmp_db)
    session = "session-continue"
    store.create("goal-continue", session, "Finish the migration")
    goal_rounds.arm(session)

    def complete_on_third(turn, sid):
        if turn == 3:
            current = store.get(sid)
            store.set_phase(sid, current.id, current.revision, "complete")

    engine = FakeEngine(complete_on_third)
    chunks = await collect(engine, store, session)

    assert len(engine.messages) == 3
    assert engine.messages[0] == "do the thing"
    assert engine.messages[1].startswith("<goal_round>")
    assert "Round: 1/256" in engine.messages[1]
    assert "Round: 2/256" in engine.messages[2]

    boundaries = [chunk.metadata["goal_round"] for chunk in chunks if chunk.metadata.get("goal_round")]
    assert [b["round"] for b in boundaries] == [1, 2]
    # One open turn for the whole deep dive: only the final done reaches the transport.
    assert sum(1 for chunk in chunks if chunk.done) == 1
    assert chunks[-1].metadata["goal"]["phase"] == "complete"


async def test_driver_blocks_at_the_round_cap(tmp_db):
    store = GoalStore(tmp_db)
    session = "session-cap"
    store.create("goal-cap", session, "Unbounded work", max_rounds=2)
    goal_rounds.arm(session)

    engine = FakeEngine()
    chunks = await collect(engine, store, session)

    # The human turn plus two admitted continuation rounds.
    assert len(engine.messages) == 3
    final = store.get(session)
    assert final.phase == "blocked"
    assert final.blocked_reason.startswith("round-limit")
    assert chunks[-1].metadata["goal"]["phase"] == "blocked"
    assert not goal_rounds.is_armed(session)


async def test_human_steer_stops_automatic_continuation(tmp_db):
    store = GoalStore(tmp_db)
    session = "session-steer"
    store.create("goal-steer", session, "Keep going forever")
    goal_rounds.arm(session)

    engine = FakeEngine(lambda _turn, sid: goal_rounds.note_human_steer(sid))
    chunks = await collect(engine, store, session)

    assert len(engine.messages) == 1
    assert chunks[-1].done
    assert store.get(session).phase == "active"
    assert goal_rounds.is_armed(session)


async def test_disarmed_goal_never_continues_after_restart(tmp_db):
    """Durability keeps the goal; activation does not survive a process."""
    store = GoalStore(tmp_db)
    session = "session-disarmed"
    store.create("goal-disarmed", session, "Survives restart")

    engine = FakeEngine()
    chunks = await collect(engine, store, session)

    assert len(engine.messages) == 1
    assert chunks[-1].metadata["goal"]["phase"] == "active"
    assert chunks[-1].metadata["goal"]["armed"] is False


async def test_driver_stops_on_pending_write(tmp_db):
    store = GoalStore(tmp_db)
    session = "session-write"
    store.create("goal-write", session, "Make a change")
    goal_rounds.arm(session)

    class PendingWriteEngine(FakeEngine):
        async def process(self, message: str, session_id: str, **kwargs):
            self.messages.append(message)
            yield StreamChunk(text="approval needed")
            yield StreamChunk(
                text="",
                done=True,
                metadata={"pending_write": {"path": "example.txt"}},
            )

    engine = PendingWriteEngine()
    chunks = await collect(engine, store, session)

    assert len(engine.messages) == 1
    assert chunks[-1].metadata["goal"]["phase"] == "active"

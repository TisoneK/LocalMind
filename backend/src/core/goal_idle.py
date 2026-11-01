"""Idle continuation — the goal deep-dive that survives a dropped transport.

The in-request round driver (``core.goal_rounds``) runs the continuation
rounds INSIDE the chat SSE request. Its recorded remainder: a dropped
connection (or a browser reload) ended the deep dive while the durable
goal stayed ``active`` — nobody kept driving it. This module is that
remainder: a process-local idle driver that picks the deep dive back up
BETWEEN human messages, as distinct background request series, under the
same authority rules as the in-request driver.

Safety contract (unchanged, and load-bearing):

- **Activation stays process-local.** A restarted backend has an empty
  registry — nothing revives on its own. An active goal from before the
  restart stays disarmed until an explicit human resume (the goal
  resume endpoint).
- **A human decision always wins.** A steer, a Stop (the abort endpoint),
  a pending write confirmation, or a fresh human message each stop the
  idle driver — the human is mid-conversation, not away.
- **The round cap, the blocked floor and the ADR-67 confirmation gates
  are the same machinery** the in-request driver uses: rounds are
  admitted through ``reserve_round`` (the durable allowance is consumed
  BEFORE the round runs — reservation-then-admission), the cap records a
  durable ``round-limit`` blocker, and a round that asks for a write
  confirmation stops the driver instead of bypassing the gate.
- **Fail-closed.** A round that crashes disarms the session — a failing
  background driver must never loop on errors. The goal stays on record;
  continuing it is the human's explicit decision.

Observability: every background round binds its own TurnContext (fresh
collector) and persists its trace to the same turn_traces store, so an
idle-driven round is on the durable record exactly like a human turn —
with a ``goal_idle_round`` event naming the driver decision.
"""

from __future__ import annotations

import asyncio
import logging

from core.goal_rounds import (
    active_goal_round,
    arm,
    disarm,
    goal_view,
    has_human_steer,
    is_armed,
    last_driver_stop,
    mark_goal_round,
    note_driver_stop,
    reserve_round,
    should_continue,
    take_human_steer,
)
from core.models import StreamChunk
from storage.goals import GoalConflictError, GoalStore

logger = logging.getLogger(__name__)

# How long the transport must stay idle before the driver picks the deep
# dive back up. Short enough that work continues promptly; long enough
# that a reconnecting client's next message wins the race.
IDLE_GRACE_SECONDS = 5.0

# Stop reasons (recorded by the in-request driver) after which the idle
# driver may pick the deep dive back up. Everything else — a steer, a
# pending write confirmation, an exhausted/blocked goal, a driver error —
# means a human is mid-decision or the goal is done wanting rounds.
# ``human_resume`` is recorded by the explicit human resume affordance —
# the decision that overrides whatever stopped the last deep dive.
_RESUMABLE_STOP_REASONS = {"completed", "abort", "disconnected", "human_resume"}

# Sessions with a transport request in flight (any turn, human or
# goal-driven). The idle driver never fires under a busy session.
_busy: set[str] = set()

# Scheduled idle tasks, one per session (a re-schedule replaces the timer).
_pending: dict[str, asyncio.Task] = {}

# Sessions where a human explicitly ceased (Stop button / steer endpoint):
# the idle driver must not pick the work back up.
_human_stopped: set[str] = set()


def note_session_busy(session_id: str) -> None:
    _busy.add(session_id)


def release_session_busy(session_id: str) -> None:
    _busy.discard(session_id)


def is_session_busy(session_id: str) -> bool:
    return session_id in _busy


def note_human_stop(session_id: str) -> None:
    """The human ceased this deep dive (Stop button, steer endpoint):
    cancel any pending idle continuation and refuse future schedules."""
    _human_stopped.add(session_id)
    cancel_idle_continuation(session_id)


def clear_human_stop(session_id: str) -> None:
    """A fresh human turn (or an explicit goal resume) clears the cease."""
    _human_stopped.discard(session_id)


def cancel_idle_continuation(session_id: str) -> None:
    task = _pending.pop(session_id, None)
    if task is not None and not task.done():
        task.cancel()


def schedule_idle_continuation(
    engine,
    session_id: str,
    goal_store: GoalStore,
    delay: float = IDLE_GRACE_SECONDS,
) -> bool:
    """Schedule the idle driver for one session's deep dive.

    Returns True when a continuation task was scheduled. The decision is
    re-checked at wake time — scheduling is an intention, not a commit.
    """
    if session_id in _human_stopped:
        return False
    goal = goal_store.get(session_id)
    if not should_continue(goal, session_id):
        return False
    stop = last_driver_stop(session_id)
    if stop is not None and stop not in _RESUMABLE_STOP_REASONS:
        return False
    if is_session_busy(session_id) or active_goal_round(session_id) is not None:
        return False
    cancel_idle_continuation(session_id)
    _pending[session_id] = asyncio.get_running_loop().create_task(
        _idle_deep_dive(engine, session_id, goal_store, delay)
    )
    return True


def idle_continuation_pending(session_id: str) -> bool:
    task = _pending.get(session_id)
    return task is not None and not task.done()


async def _idle_deep_dive(engine, session_id: str, goal_store: GoalStore, delay: float) -> None:
    """The idle driver: continue the armed deep dive round by round.

    One task carries the WHOLE remaining deep dive (rounds re-schedule
    themselves internally), so there is exactly one background driver per
    session and the round cap is consumed by admission.
    """
    try:
        await asyncio.sleep(delay)
        while True:
            if not _may_fire(session_id):
                return
            goal = goal_store.get(session_id)
            if not should_continue(goal, session_id):
                return
            # Reservation-then-admission: consume the allowance BEFORE the
            # round runs; None means the cap/phase stopped wanting rounds.
            reserved = reserve_round(goal_store, session_id)
            if reserved is None:
                return
            mark_goal_round(session_id, reserved.rounds_started)
            try:
                done_chunk = await _run_idle_round(
                    engine, session_id, goal_store, reserved
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Fail-closed: a crashed background round disarms — the goal
                # stays on record, continuing it is the human's decision.
                logger.exception(
                    "[goal-idle] round %d failed for session %s — disarming",
                    reserved.rounds_started,
                    session_id,
                )
                disarm(session_id)
                return
            finally:
                mark_goal_round(session_id, None)

            # The gates the in-request driver honors at every idle point.
            if take_human_steer(session_id):
                note_driver_stop(session_id, "steer")
                return
            try:
                if engine._abort_for(session_id).is_set():
                    note_driver_stop(session_id, "abort")
                    return
            except Exception:
                pass
            metadata = dict(done_chunk.metadata) if done_chunk is not None else {}
            if metadata.get("pending_write") or metadata.get("switch_to_agent"):
                # A confirmation card awaits a human decision; the next
                # human turn re-drives the rounds (the goal stays armed).
                note_driver_stop(session_id, "pending_write")
                return

            goal = goal_store.get(session_id)
            if not should_continue(goal, session_id):
                # The allowance is spent while the goal is still armed and
                # active: record the durable round-limit blocker, exactly
                # like the in-request driver's tail.
                if (
                    goal is not None
                    and goal.phase == "active"
                    and is_armed(session_id)
                ):
                    from core.goal_rounds import block_at_cap

                    block_at_cap(goal_store, goal)
                note_driver_stop(session_id, "stopped")
                return
            if is_session_busy(session_id):
                # A human (or another client) took the session: yield, and
                # let the transport's own driver carry the deep dive.
                note_driver_stop(session_id, "yielded_to_transport")
                return
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("[goal-idle] driver crashed for session %s", session_id)
    finally:
        _pending.pop(session_id, None)


def _may_fire(session_id: str) -> bool:
    """All the pre-round guards, in one place."""
    if session_id in _human_stopped:
        return False
    if is_session_busy(session_id):
        return False
    if active_goal_round(session_id) is not None:
        return False
    if has_human_steer(session_id):
        # An unconsumed steer means a human message is waiting in the
        # transport's turn — do not fire over it.
        return False
    return True


async def _run_idle_round(engine, session_id: str, goal_store: GoalStore, goal) -> StreamChunk | None:
    """Run ONE continuation round as a background request series.

    The round is a normal engine turn on the same session — history,
    tools, persistence and confirmation rules are exactly those of a
    human turn — wrapped in its own TurnContext so the durable record
    covers it, and persisted to the same turn_traces store.
    """
    from core.goal_rounds import build_round_prompt
    from core.obs import ObsCollector
    from core.turn_trace import TurnContext, bind_turn, new_turn_id, reset_turn

    obs = ObsCollector()
    turn_ctx = TurnContext(turn_id=new_turn_id(), session_id=session_id, collector=obs)
    turn_token = bind_turn(turn_ctx)
    obs.emit(
        "goal_idle_round",
        round=goal.rounds_started,
        max_rounds=goal.max_rounds,
        goal_id=goal.id,
        goal_phase=goal.phase,
    )
    done_chunk: StreamChunk | None = None
    try:
        async for chunk in engine.process(
            message=build_round_prompt(goal, goal.rounds_started),
            session_id=session_id,
            obs=obs,
        ):
            if chunk.done:
                done_chunk = chunk
            # Chunks go nowhere: no transport is attached. The turn's
            # persistence happens inside engine.process exactly as for a
            # human turn; the SSE-only surfaces (live cards) simply do not
            # exist for a background round.
    finally:
        try:
            engine._store.append_turn_trace(session_id, turn_ctx.turn_id, obs.history())
        except Exception:
            logger.debug("[goal-idle] trace persist skipped", exc_info=True)
        try:
            reset_turn(turn_token)
        except Exception:
            pass
    return done_chunk


def resume_for_human(
    engine,
    session_id: str,
    goal_store: GoalStore,
    delay: float = 1.0,
) -> dict | None:
    """The human resume affordance: re-arm and kick the deep dive.

    Called by the goal resume endpoint — an explicit human decision, the
    only thing that revives a disarmed goal (including after a restart).
    A goal whose round allowance is exhausted is honestly refused (the
    cap must be extended first). Returns the goal view, or None when
    there is nothing to resume.
    """
    goal = goal_store.get(session_id)
    if goal is None:
        return None
    if goal.rounds_started >= goal.max_rounds:
        raise GoalConflictError(
            f"The round cap ({goal.max_rounds}) is exhausted. Extend the cap "
            "before resuming."
        )
    clear_human_stop(session_id)
    arm(session_id)
    # The explicit human decision overrides whatever stopped the last deep
    # dive (a cap, a steer, a Stop): the schedule's stop-reason guard reads
    # this and admits the fresh continuation.
    note_driver_stop(session_id, "human_resume")
    schedule_idle_continuation(engine, session_id, goal_store, delay=delay)
    return goal_view(goal_store.get(session_id), session_id)


__all__ = [
    "IDLE_GRACE_SECONDS",
    "cancel_idle_continuation",
    "clear_human_stop",
    "idle_continuation_pending",
    "is_session_busy",
    "note_human_stop",
    "note_session_busy",
    "release_session_busy",
    "resume_for_human",
    "schedule_idle_continuation",
]

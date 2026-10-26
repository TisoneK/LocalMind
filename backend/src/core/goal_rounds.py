"""Goal rounds — the same-session deep-dive driver.

The durable goal itself lives in ``storage.goals``. This module owns the
*process-local* half: whether automatic continuation is armed, which session
is currently inside a goal round (so the goal tools can enforce authority),
and the async wrapper that keeps calling the engine after a turn ends while
the goal stays active.

Continuation stops on: goal completion/pause/block/clear, a disarmed goal, a
pending write confirmation, a provider error, a user abort or steering
message, and the round cap (which records a durable ``round-limit`` blocker).

The loop runs inside the existing chat SSE request: a round is one normal
engine turn on the SAME session, so history, tools, and persistence are
exactly those of a human turn. Write-capable tools therefore keep the normal
confirmation rules; the driver adds no bypass.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from core.models import StreamChunk
from storage.goals import (
    DEFAULT_MAX_GOAL_ROUNDS,
    MAX_GOAL_ROUNDS,
    Goal,
    GoalStore,
)

logger = logging.getLogger(__name__)

# The model may self-block only after this many admitted goal rounds. The
# point is that "blocked" means a condition persisted across attempts, not a
# first-attempt inconvenience.
BLOCKED_AFTER_ROUNDS = 3

# Continuation is process-local by design: a restarted backend never resumes
# autonomous work until the goal is explicitly resumed.
_armed: set[str] = set()
_active_rounds: dict[str, int] = {}
_steered: set[str] = set()


def arm(session_id: str) -> None:
    _armed.add(session_id)


def disarm(session_id: str) -> None:
    _armed.discard(session_id)


def is_armed(session_id: str) -> bool:
    return session_id in _armed


def mark_goal_round(session_id: str, round_number: int | None) -> None:
    if round_number is None:
        _active_rounds.pop(session_id, None)
    else:
        _active_rounds[session_id] = round_number


def active_goal_round(session_id: str | None) -> int | None:
    if not session_id:
        return None
    return _active_rounds.get(session_id)


def note_human_steer(session_id: str) -> None:
    """A human message arrived mid-round: automatic work must yield."""
    _steered.add(session_id)


def take_human_steer(session_id: str) -> bool:
    if session_id in _steered:
        _steered.discard(session_id)
        return True
    return False


def goal_view(goal: Goal | None, session_id: str) -> dict | None:
    """Wire shape shared by the SSE events, the tools, and the goal endpoint."""
    if goal is None:
        return None
    return {
        "id": goal.id,
        "objective": goal.objective,
        "phase": goal.phase,
        "revision": goal.revision,
        "roundsStarted": goal.rounds_started,
        "maxGoalRounds": goal.max_rounds,
        "blockedReason": goal.blocked_reason,
        "armed": is_armed(session_id),
    }


def build_round_prompt(goal: Goal, round_number: int) -> str:
    """The retained ``<goal_round>`` continuation prompt."""
    objective = goal.objective.replace('"', '\\"')
    return (
        "<goal_round>\n"
        f'Objective: "{objective}"\n'
        f"Round: {round_number}/{goal.max_rounds}\n"
        "Continue this objective in the same session. Use the current "
        "workspace, earlier tool results, and the conversation history as "
        "authority; do not repeat work already completed. Take the next "
        "concrete step, verify it, then keep going while useful work "
        "remains. When the objective is actually achieved, call update_goal "
        "with action=complete and give the user a final summary. Call "
        f"update_goal action=blocked only after the same blocking condition "
        f"has persisted for at least {BLOCKED_AFTER_ROUNDS} rounds, and name "
        "the concrete condition in blocked_reason. Do not stop just because "
        "the work is hard or because more could be done.\n"
        "</goal_round>"
    )


def should_continue(goal: Goal | None, session_id: str) -> bool:
    return bool(
        goal is not None
        and goal.phase == "active"
        and is_armed(session_id)
        and goal.rounds_started < goal.max_rounds
    )


def block_at_cap(store: GoalStore, goal: Goal) -> Goal | None:
    reason = (
        f"round-limit: the {goal.max_rounds}-round continuation cap was "
        "reached before the objective completed."
    )
    updated = store.set_phase(
        goal.session_id,
        goal.id,
        goal.revision,
        "blocked",
        blocked_reason=reason,
    )
    disarm(goal.session_id)
    return updated


def reserve_round(store: GoalStore, session_id: str) -> Goal | None:
    """Consume one round of allowance, or block/stop when none remains."""
    goal = store.get(session_id)
    if not should_continue(goal, session_id):
        return None
    if goal.rounds_started >= goal.max_rounds:
        block_at_cap(store, goal)
        return None
    reserved = store.bump_round(session_id, goal.id, goal.revision)
    if reserved is None:
        # A concurrent mutation moved the revision; re-read once.
        goal = store.get(session_id)
        if not should_continue(goal, session_id):
            return None
        if goal.rounds_started >= goal.max_rounds:
            block_at_cap(store, goal)
            return None
        reserved = store.bump_round(session_id, goal.id, goal.revision)
    return reserved


async def process_with_goal_rounds(
    engine,
    message: str,
    session_id: str,
    goal_store: GoalStore,
    **engine_kwargs,
) -> AsyncIterator[StreamChunk]:
    """Run the user turn, then queue goal rounds until an honest stop.

    Only the FINAL round's ``done`` chunk reaches the transport, so the
    frontend keeps its single open turn for the whole deep dive. Each round
    boundary is surfaced as a metadata-only chunk the route bridges to a
    ``goal_round`` SSE event.
    """
    initial = goal_store.get(session_id)
    # Surface an existing goal before the first round, but never emit an empty
    # control event on a goal-less chat: the transport's first event must stay
    # the immediate engine acknowledgement (obs_event).
    if initial is not None:
        yield StreamChunk(
            text="",
            metadata={"goal": goal_view(initial, session_id)},
        )

    round_number = 0
    round_message = message
    last_done: StreamChunk | None = None
    try:
        while True:
            round_number += 1
            if round_number > 1:
                goal = reserve_round(goal_store, session_id)
                if goal is None:
                    break
                mark_goal_round(session_id, goal.rounds_started)
                yield StreamChunk(
                    text="",
                    metadata={
                        "goal": goal_view(goal, session_id),
                        "goal_round": {
                            "round": goal.rounds_started,
                            "maxRounds": goal.max_rounds,
                            "objective": goal.objective,
                        },
                    },
                )
                round_message = build_round_prompt(goal, goal.rounds_started)
            else:
                mark_goal_round(session_id, None)

            round_done: StreamChunk | None = None
            try:
                async for chunk in engine.process(
                    message=round_message,
                    session_id=session_id,
                    **engine_kwargs,
                ):
                    if chunk.done:
                        round_done = chunk
                        continue
                    yield chunk
            finally:
                mark_goal_round(session_id, None)

            if round_done is not None:
                last_done = round_done

            # User intent wins at every idle point.
            if take_human_steer(session_id):
                break
            try:
                if engine._abort_for(session_id).is_set():
                    break
            except Exception:
                pass

            metadata = dict(round_done.metadata) if round_done is not None else {}
            if metadata.get("pending_write") or metadata.get("switch_to_agent"):
                break

            goal = goal_store.get(session_id)
            if not should_continue(goal, session_id):
                if goal is not None and goal.phase == "active" and is_armed(session_id):
                    block_at_cap(goal_store, goal)
                break

            if goal.rounds_started >= goal.max_rounds:
                block_at_cap(goal_store, goal)
                break
    except Exception:
        logger.exception("[goal-rounds] driver failed for session %s", session_id)
        raise
    finally:
        mark_goal_round(session_id, None)
        _steered.discard(session_id)

    final_goal = goal_store.get(session_id)
    # Continuation authority is only meaningful while the goal is active. A
    # goal that finished, paused, blocked, or was cleared during the turn
    # drops its activation with it.
    if final_goal is None or final_goal.phase != "active":
        disarm(session_id)
    view = goal_view(final_goal, session_id)
    if last_done is None:
        last_done = StreamChunk(text="", done=True)
    last_done = last_done.model_copy(
        update={"metadata": {**dict(last_done.metadata), "goal": view}}
    )
    yield last_done


__all__ = [
    "BLOCKED_AFTER_ROUNDS",
    "DEFAULT_MAX_GOAL_ROUNDS",
    "MAX_GOAL_ROUNDS",
    "active_goal_round",
    "arm",
    "block_at_cap",
    "build_round_prompt",
    "disarm",
    "goal_view",
    "is_armed",
    "mark_goal_round",
    "note_human_steer",
    "process_with_goal_rounds",
    "reserve_round",
    "should_continue",
    "take_human_steer",
]

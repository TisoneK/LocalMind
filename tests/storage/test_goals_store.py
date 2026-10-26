"""Tests for durable same-session goals (storage layer)."""

from __future__ import annotations

import pytest

from storage.goals import GoalConflictError, GoalStore


def test_goal_lifecycle_rounds_and_cas(tmp_db):
    store = GoalStore(tmp_db)
    goal = store.create("goal-1", "session-1", "Refactor the parser", max_rounds=4)
    assert goal.phase == "active"
    assert goal.revision == 1
    assert goal.rounds_started == 0
    assert goal.max_rounds == 4

    edited = store.edit("session-1", goal.id, goal.revision, objective="Refactor the parser fully")
    assert edited is not None
    assert edited.objective == "Refactor the parser fully"
    assert edited.revision == 2

    # A stale revision is rejected instead of overwriting newer state.
    assert store.edit("session-1", goal.id, goal.revision, objective="stale") is None

    bumped = store.bump_round("session-1", goal.id, edited.revision)
    assert bumped is not None
    assert bumped.rounds_started == 1
    assert bumped.revision == 3

    paused = store.set_phase("session-1", goal.id, bumped.revision, "paused")
    assert paused is not None
    assert paused.phase == "paused"
    # A paused goal admits no continuation rounds.
    assert store.bump_round("session-1", goal.id, paused.revision) is None

    resumed = store.resume("session-1", goal.id, paused.revision)
    assert resumed is not None
    assert resumed.phase == "active"

    completed = store.set_phase("session-1", goal.id, resumed.revision, "complete")
    assert completed is not None
    with pytest.raises(GoalConflictError):
        store.resume("session-1", goal.id, completed.revision)


def test_unfinished_goal_blocks_create_until_cleared(tmp_db):
    store = GoalStore(tmp_db)
    store.create("goal-a", "session-a", "First objective")
    with pytest.raises(GoalConflictError):
        store.create("goal-b", "session-a", "Second objective")

    assert store.clear("session-a") is True
    second = store.create("goal-b", "session-a", "Second objective")
    assert second.phase == "active"


def test_round_cap_is_enforced_atomically(tmp_db):
    store = GoalStore(tmp_db)
    goal = store.create("goal-cap", "session-cap", "Bounded work", max_rounds=2)

    first = store.bump_round("session-cap", goal.id, goal.revision)
    assert first is not None and first.rounds_started == 1
    second = store.bump_round("session-cap", goal.id, first.revision)
    assert second is not None and second.rounds_started == 2

    assert store.bump_round("session-cap", goal.id, second.revision) is None
    assert store.get("session-cap").rounds_started == 2

    store.set_phase("session-cap", goal.id, second.revision, "paused")
    paused = store.get("session-cap")
    with pytest.raises(GoalConflictError):
        store.resume("session-cap", goal.id, paused.revision)


def test_rounds_are_clamped_to_the_hard_cap(tmp_db):
    store = GoalStore(tmp_db)
    goal = store.create("goal-huge", "session-huge", "Unbounded", max_rounds=99_999)
    assert goal.max_rounds == 256

    tiny = store.create("goal-tiny", "session-tiny", "Tiny", max_rounds=0)
    assert tiny.max_rounds == 1

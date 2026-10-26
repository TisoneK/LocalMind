"""Tests for the get_goal / update_goal tool surface."""

from __future__ import annotations

import json

import pytest

from core import goal_rounds
from core.config import settings
from core.session_workspace import reset_current_session, set_current_session
from storage.goals import get_goal_store
from tools.goal import get_goal, update_goal

pytestmark = pytest.mark.asyncio


@pytest.fixture
def session_ctx(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "localmind_db_path", tmp_db)
    get_goal_store.cache_clear()
    goal_rounds._armed.clear()
    goal_rounds._active_rounds.clear()
    goal_rounds._steered.clear()
    token = set_current_session("session-goal-tools")
    try:
        yield "session-goal-tools"
    finally:
        reset_current_session(token)
        goal_rounds._armed.clear()
        goal_rounds._active_rounds.clear()
        goal_rounds._steered.clear()
        get_goal_store.cache_clear()


async def test_get_goal_returns_null_without_a_goal(session_ctx):
    result = await get_goal("")
    assert result.success
    assert json.loads(result.content) == {"goal": None, "activation": "disarmed"}


async def test_update_goal_create_read_complete(session_ctx):
    created = await update_goal(
        json.dumps({"action": "create", "objective": "Ship the goal slice"})
    )
    assert created.success
    goal = json.loads(created.content)["goal"]
    assert goal["phase"] == "active"
    assert goal["armed"] is True
    assert goal["maxGoalRounds"] == 256
    assert goal["roundsStarted"] == 0

    fetched = json.loads((await get_goal("")).content)["goal"]
    assert fetched["id"] == goal["id"]
    assert fetched["revision"] == goal["revision"]

    stale = await update_goal(
        json.dumps(
            {
                "action": "complete",
                "goal_id": goal["id"],
                "revision": goal["revision"] + 5,
            }
        )
    )
    assert not stale.success
    assert stale.error_type == "stale_revision"

    completed = await update_goal(
        json.dumps(
            {"action": "complete", "goal_id": goal["id"], "revision": goal["revision"]}
        )
    )
    assert completed.success
    assert json.loads(completed.content)["goal"]["phase"] == "complete"
    assert not goal_rounds.is_armed(session_ctx)


async def test_update_goal_refuses_human_actions_inside_a_goal_round(session_ctx):
    created = json.loads(
        (
            await update_goal(
                json.dumps({"action": "create", "objective": "Keep improving"})
            )
        ).content
    )
    goal = created["goal"]
    goal_rounds.mark_goal_round(session_ctx, 1)
    try:
        paused = await update_goal(
            json.dumps(
                {"action": "pause", "goal_id": goal["id"], "revision": goal["revision"]}
            )
        )
        assert not paused.success
        assert "direct user turn" in paused.content

        early_block = await update_goal(
            json.dumps(
                {
                    "action": "blocked",
                    "goal_id": goal["id"],
                    "revision": goal["revision"],
                    "blocked_reason": "the network is down",
                }
            )
        )
        assert not early_block.success
        assert "not allowed yet" in early_block.content
    finally:
        goal_rounds.mark_goal_round(session_ctx, None)


async def test_update_goal_blocks_once_enough_rounds_have_passed(session_ctx):
    created = json.loads(
        (await update_goal(json.dumps({"action": "create", "objective": "Keep improving"}))).content
    )
    goal = created["goal"]
    store = get_goal_store(settings.localmind_db_path)
    current = store.get(session_ctx)
    for _ in range(goal_rounds.BLOCKED_AFTER_ROUNDS):
        current = store.bump_round(session_ctx, current.id, current.revision)
    assert current.rounds_started == goal_rounds.BLOCKED_AFTER_ROUNDS

    goal_rounds.mark_goal_round(session_ctx, current.rounds_started)
    try:
        blocked = await update_goal(
            json.dumps(
                {
                    "action": "blocked",
                    "goal_id": goal["id"],
                    "revision": current.revision,
                    "blocked_reason": "the provider key is revoked",
                }
            )
        )
    finally:
        goal_rounds.mark_goal_round(session_ctx, None)

    assert blocked.success
    payload = json.loads(blocked.content)
    assert payload["goal"]["phase"] == "blocked"
    assert payload["goal"]["blockedReason"] == "the provider key is revoked"
    assert payload["activation"] == "disarmed"


async def test_update_goal_rejects_missing_reference(session_ctx):
    await update_goal(json.dumps({"action": "create", "objective": "Something"}))
    result = await update_goal(json.dumps({"action": "complete"}))
    assert not result.success
    assert "goal_id and revision" in result.content

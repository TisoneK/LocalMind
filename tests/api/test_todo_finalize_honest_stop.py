"""
Session 330 (B-2026-08-20-23): _finalize_plan_todos must NOT flip the
remaining goal items to complete when the acceptance gate ended the turn
with an honest stop (unmet criteria). Flipping them would re-lie the
self-mutating checklist — the panel would read 100% on a turn that did
not finish its work.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import api.routes.chat as chat_routes


def _fake_engine(rows):
    store = MagicMock()
    store.list_todos.return_value = rows
    engine = MagicMock()
    engine._store = store
    return engine, store


def test_finalize_skips_on_honest_stop():
    """skip=True (the loop emitted agent_loop_gate_honest_stop): the unmet
    plan-1 item stays pending — no DB write, no SSE flip."""
    engine, store = _fake_engine(
        [
            {"id": "plan-0", "completed": True},
            {"id": "plan-1", "completed": False},  # unmet goal item
        ]
    )
    chat_routes._engine = engine
    flipped = chat_routes._finalize_plan_todos("s1", skip=True)
    assert flipped == []
    store.upsert_todo.assert_not_called()


def test_finalize_flips_remaining_by_default():
    """Legacy behavior unchanged: on a normal (non-honest-stop) turn the
    remaining plan todos are finalized as complete."""
    engine, store = _fake_engine(
        [
            {"id": "plan-0", "completed": True},
            {"id": "plan-1", "completed": False},
        ]
    )
    chat_routes._engine = engine
    flipped = chat_routes._finalize_plan_todos("s1", skip=False)
    assert flipped == [{"id": "plan-1", "completed": True}]
    store.upsert_todo.assert_called_once()

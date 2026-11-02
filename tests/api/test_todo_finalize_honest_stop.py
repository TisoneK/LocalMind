"""
Session 330: _finalize_plan_todos must NOT flip the
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
    """On a normal (non-honest-stop) turn the remaining plan todos close as
    BLOCKED with a result — never completed. A todo that never ran is not
    done: marking it complete was the execution-success-equals-objective-
    success lie, and the panel must show the true fraction."""
    engine, store = _fake_engine(
        [
            {"id": "plan-0", "completed": True},
            {"id": "plan-1", "completed": False},
        ]
    )
    chat_routes._engine = engine
    flipped = chat_routes._finalize_plan_todos("s1", skip=False)
    assert flipped == [
        {
            "id": "plan-1",
            "status": "blocked",
            "result": "Not reached — the turn closed before this todo ran.",
        }
    ]
    store.upsert_todo.assert_called_once()
    _args, _kwargs = store.upsert_todo.call_args
    assert _kwargs.get("status") == "blocked"

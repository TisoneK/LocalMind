"""Tests for the SQLite session store."""
import time

import pytest
from core.models import Message, Role
from storage.db import SessionStore


@pytest.fixture
def store(tmp_db):
    return SessionStore(tmp_db)


def test_ensure_session_creates(store):
    store.ensure_session("s1")
    sessions = store.list_sessions()
    assert any(s["id"] == "s1" for s in sessions)


def test_ensure_session_idempotent(store):
    store.ensure_session("s1")
    store.ensure_session("s1")  # should not raise
    sessions = store.list_sessions()
    assert sum(1 for s in sessions if s["id"] == "s1") == 1


def test_append_and_retrieve(store):
    msg = Message(role=Role.USER, content="Hello LocalMind", timestamp=time.time())
    store.append("s1", msg)
    history = store.get_history("s1")
    assert len(history) == 1
    assert history[0].content == "Hello LocalMind"
    assert history[0].role == Role.USER


def test_history_order(store):
    store.append("s1", Message(role=Role.USER, content="First", timestamp=1.0))
    store.append("s1", Message(role=Role.ASSISTANT, content="Second", timestamp=2.0))
    store.append("s1", Message(role=Role.USER, content="Third", timestamp=3.0))
    history = store.get_history("s1")
    assert [m.content for m in history] == ["First", "Second", "Third"]


def test_get_recent_history_returns_newest_first(store):
    store.append("s1", Message(role=Role.USER, content="First", timestamp=1.0))
    store.append("s1", Message(role=Role.ASSISTANT, content="Second", timestamp=2.0))
    store.append("s1", Message(role=Role.USER, content="Third", timestamp=3.0))
    store.append("s1", Message(role=Role.ASSISTANT, content="Fourth", timestamp=4.0))
    recent = store.get_recent_history("s1", limit=2)
    # Newest-first: the LAST two messages, not the oldest two.
    assert [m.content for m in recent] == ["Fourth", "Third"]


def test_multiple_sessions_isolated(store):
    store.append("s1", Message(role=Role.USER, content="Session 1 message"))
    store.append("s2", Message(role=Role.USER, content="Session 2 message"))
    assert len(store.get_history("s1")) == 1
    assert len(store.get_history("s2")) == 1
    assert store.get_history("s1")[0].content == "Session 1 message"


def test_delete_session(store):
    store.append("s1", Message(role=Role.USER, content="Hello"))
    deleted = store.delete_session("s1")
    assert deleted is True
    assert store.get_history("s1") == []


def test_delete_nonexistent_session(store):
    deleted = store.delete_session("nonexistent")
    assert deleted is False


def test_list_sessions_empty(store):
    assert store.list_sessions() == []


def test_list_sessions_with_data(store):
    store.append("s1", Message(role=Role.USER, content="Hi"))
    store.append("s1", Message(role=Role.ASSISTANT, content="Hello"))
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["message_count"] == 2


def test_clear_all(store):
    store.append("s1", Message(role=Role.USER, content="A"))
    store.append("s2", Message(role=Role.USER, content="B"))
    store.clear_all()
    assert store.list_sessions() == []


# ── Session 120: todo <-> action hierarchy ─────────────────────────────────
# Todos are the high-level plan checklist; actions hang off them via todo_id.
# These tests lock the two bugs the real-model smoke found: the defensive
# ALTER must add todo_id even when iteration already exists, and upserts must
# be idempotent (never UNIQUE-violate against the engine's plan write).


def test_actions_have_todo_id_column_after_init(tmp_path):
    # Simulate a pre-Session-120 DB (actions table without todo_id), then a
    # SessionStore init must re-add it — even when the iteration column already
    # exists (the bug: one try-block around both ALTERs skipped the second).
    import sqlite3

    from storage.db import SessionStore as SS

    if sqlite3.sqlite_version_info < (3, 35, 0):
        pytest.skip("DROP COLUMN requires SQLite >= 3.35")

    db = str(tmp_path / "alt.db")
    SS(db)  # fresh init: schema already includes todo_id
    conn = sqlite3.connect(db)
    conn.execute("ALTER TABLE actions DROP COLUMN todo_id")  # downgrade to old DB
    conn.commit()
    conn.close()
    store2 = SS(db)  # re-init must re-add todo_id via the defensive ALTER
    store2.ensure_session("s1")
    store2.create_action("s1", "git", action_id="a1", iteration=1, todo_id="plan-0")
    row = store2.list_actions("s1")[0]
    assert row["todo_id"] == "plan-0"
    assert row["iteration"] == 1


def test_create_action_stores_todo_id(store):
    store.ensure_session("s1")
    store.create_action("s1", "git", action_id="a1", iteration=2, todo_id="plan-1")
    row = store.list_actions("s1")[0]
    assert row["todo_id"] == "plan-1"
    assert row["iteration"] == 2


def test_upsert_todo_create_update_clear(store):
    store.ensure_session("s1")
    # create
    store.upsert_todo("s1", "plan-0", text="Review backend code", completed=False)
    rows = store.list_todos("s1")
    assert len(rows) == 1
    assert rows[0]["content"] == "Review backend code"
    assert rows[0]["completed"] == 0
    # update (completed-only must NOT wipe the text)
    store.upsert_todo("s1", "plan-0", completed=True)
    rows = store.list_todos("s1")
    assert rows[0]["content"] == "Review backend code"
    assert rows[0]["completed"] == 1
    # idempotent re-create (same id) never raises
    store.upsert_todo("s1", "plan-0", text="Review backend code", completed=False)
    # clear
    store.clear_todos("s1")
    assert store.list_todos("s1") == []

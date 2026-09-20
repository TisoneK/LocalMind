"""A todo belongs to one chat.

Plan and synthetic tasks use the same ids in every chat ("plan-0"). The table used `id` as its
whole primary key and the upsert looked a task up by id alone, so the first chat to create
"plan-0" owned it: a later chat's upsert updated THAT row and created nothing, and the later chat
lost its tasks at the end-of-turn refetch ("tasks disappear after the turn").
"""
import sqlite3

import pytest

from storage.db import SessionStore as Store


@pytest.fixture()
def store(tmp_path):
    return Store(str(tmp_path / "t.db"))


def test_two_chats_each_keep_their_own_plan(store):
    for sid in ("chat-a", "chat-b"):
        store.ensure_session(sid)
        store.upsert_todo(sid, "plan-0", text="Search the web", completed=False, title="Search the web")
        store.upsert_todo(sid, "plan-1", text="Check the sources", completed=False)
    store.upsert_todo("chat-b", "plan-0", completed=True)

    a = {t["id"]: t["completed"] for t in store.list_todos("chat-a")}
    b = {t["id"]: t["completed"] for t in store.list_todos("chat-b")}
    assert set(a) == {"plan-0", "plan-1"} and set(b) == {"plan-0", "plan-1"}
    assert a["plan-0"] == 0  # completing chat B's step did not touch chat A's
    assert b["plan-0"] == 1


def test_a_later_chat_is_not_left_with_nothing(store):
    store.ensure_session("first")
    store.upsert_todo("first", "plan-0", text="one")
    store.ensure_session("second")
    store.upsert_todo("second", "plan-0", text="two")
    assert [t["content"] for t in store.list_todos("second")] == ["two"]
    assert [t["content"] for t in store.list_todos("first")] == ["one"]


def test_clearing_one_chat_leaves_the_others(store):
    for sid in ("a", "b"):
        store.ensure_session(sid)
        store.upsert_todo(sid, "plan-0", text="x")
    store.clear_todos("a")
    assert store.list_todos("a") == []
    assert len(store.list_todos("b")) == 1


def test_the_migration_keeps_existing_rows_and_allows_the_same_id_in_two_chats(tmp_path):
    db = str(tmp_path / "m.db")
    Store(db)  # applies every migration, including 012
    with sqlite3.connect(db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(todos)")]
        pk = [r[1] for r in conn.execute("PRAGMA table_info(todos)") if r[5]]
    assert "title" in cols
    assert set(pk) == {"session_id", "id"}

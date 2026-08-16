"""Regression: the guaranteed-persist safety net must not double-persist an
assistant reply that process() already saved.

The safety net runs in the chat route's `finally` block and is meant to be a
no-op when the reply was already persisted. Its dedup check read
`get_history(session_id, limit=2)`, which orders ASC — so it inspected the
OLDEST two messages and failed to match the just-saved reply for any session
with more than two messages. Every reply from turn 2 onward was written twice,
surfacing as duplicated transcript messages after reopening a chat.
"""

from __future__ import annotations

from core.models import Message, Role
from storage.db import SessionStore


def _engine_with_store(tmp_db):
    from core.engine import Engine

    engine = Engine()
    engine._store = SessionStore(tmp_db)
    return engine


def test_guarantee_persist_assistant_does_not_duplicate(tmp_db):
    engine = _engine_with_store(tmp_db)
    sid = "sess-persist-dedup"

    # Simulate a two-turn conversation where process() already persisted
    # each reply before the chat route's finally block ran.
    engine._store.append(sid, Message(role=Role.USER, content="one"))
    engine._store.append(sid, Message(role=Role.ASSISTANT, content="reply one"))
    engine._store.append(sid, Message(role=Role.USER, content="two"))
    engine._store.append(sid, Message(role=Role.ASSISTANT, content="reply two"))

    # The finally-block safety net runs with the same text that was saved.
    engine._guarantee_persist_assistant(sid, ["reply two"])

    assistant_msgs = [
        m for m in engine._store.get_history(sid) if m.role == Role.ASSISTANT
    ]
    assert [m.content for m in assistant_msgs] == ["reply one", "reply two"]


def test_guarantee_persist_assistant_still_saves_when_missing(tmp_db):
    engine = _engine_with_store(tmp_db)
    sid = "sess-persist-missing"

    # No assistant message persisted yet (e.g. the generator was interrupted
    # before process() saved) — the safety net must still save it.
    engine._store.append(sid, Message(role=Role.USER, content="hello"))

    engine._guarantee_persist_assistant(sid, ["interrupted reply"])

    assistant_msgs = [
        m for m in engine._store.get_history(sid) if m.role == Role.ASSISTANT
    ]
    assert [m.content for m in assistant_msgs] == ["interrupted reply"]

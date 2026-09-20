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


def test_action_provider_roundtrips(store):
    """The winning search engine is stored on the action row —
    set on create or via the done-event update — and survives list_actions."""
    store.ensure_session("s1")
    # Provider known at create time.
    store.create_action("s1", "web_search", action_id="a1", provider="bing")
    assert store.list_actions("s1")[0]["provider"] == "bing"
    # Provider arrives on the done event — update_action must set it without
    # clobbering the existing output/status.
    store.update_action("a1", status="done", output="Search results…", provider="searxng")
    row = store.list_actions("s1")[0]
    assert row["provider"] == "searxng"
    assert row["status"] == "done"
    assert row["output"] == "Search results…"
    # Actions without a provider stay null.
    store.create_action("s1", "shell", action_id="a2")
    rows = {r["id"]: r for r in store.list_actions("s1")}
    assert rows["a2"]["provider"] is None


# ── Session 266: per-turn artifacts survive a reload ────────────────────────
# The messages table now persists thinking / error / tool_calls / metrics with
# each assistant message; get_history must round-trip them so the frontend can
# restore thinking blocks, error cards, step pills, and the context counter.


def test_message_roundtrips_thinking_error_tool_calls_metrics(store):
    store.append(
        "s1",
        Message(
            role=Role.ASSISTANT,
            content="Done.",
            thinking="First step\n\nSecond step",
            error="zen returned 429: quota exceeded",
            tool_calls=[
                {"id": "tc-shell-iter1", "name": "shell", "status": "done", "reasoning": "why"},
                {"id": "tc-file-iter2", "name": "file_read", "status": "done"},
            ],
            metrics={"prompt_tokens": 1200, "completion_tokens": 84, "latency_ms": 2300},
            acknowledgement="I'll list your projects and summarise them.",
        ),
    )
    history = store.get_history("s1")
    assert len(history) == 1
    m = history[0]
    assert m.thinking == "First step\n\nSecond step"
    # The ADR-36 opening acknowledgement round-trips too.
    assert m.acknowledgement == "I'll list your projects and summarise them."
    assert m.error == "zen returned 429: quota exceeded"
    assert m.tool_calls == [
        {"id": "tc-shell-iter1", "name": "shell", "status": "done", "reasoning": "why"},
        {"id": "tc-file-iter2", "name": "file_read", "status": "done"},
    ]
    assert m.metrics == {"prompt_tokens": 1200, "completion_tokens": 84, "latency_ms": 2300}


def test_recent_history_roundtrips_artifacts(store):
    store.append("s1", Message(role=Role.USER, content="hello"))
    store.append(
        "s1",
        Message(
            role=Role.ASSISTANT,
            content="reply",
            thinking="thinking trace",
            error="provider down",
            tool_calls=[{"id": "tc-1", "name": "git", "status": "failed"}],
            metrics={"prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 100},
        ),
    )
    recent = store.get_recent_history("s1", limit=2)
    m = recent[0]
    assert m.role == Role.ASSISTANT
    assert m.thinking == "thinking trace"
    assert m.error == "provider down"
    assert m.tool_calls == [{"id": "tc-1", "name": "git", "status": "failed"}]
    assert m.metrics == {"prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 100}


def test_messages_without_artifacts_still_roundtrip_plain(store):
    store.append("s1", Message(role=Role.USER, content="plain"))
    history = store.get_history("s1")
    assert history[0].thinking is None
    assert history[0].error is None
    assert history[0].tool_calls is None
    assert history[0].metrics is None


def test_message_roundtrips_agent_runs_and_phases(store):
    """The Agent Workspace run tree + phase strip persist with
    the assistant message and round-trip through get_history and
    get_recent_history so the Agents tab survives a reload."""
    runs = [
        {
            "id": "parent",
            "name": "parent",
            "role": "parent",
            "task": "build a cli",
            "status": "completed",
            "depth": 0,
            "startedAt": 1700000000000,
            "completedAt": 1700000009000,
            "tools": [
                {"id": "tc-shell-iter1", "name": "shell", "label": "Running: ls", "status": "done", "input": "ls"}
            ],
        },
        {
            "id": "run-123",
            "name": "research",
            "role": "child",
            "parentId": "parent",
            "task": "find docs",
            "status": "completed",
            "depth": 1,
            "startedAt": 1700000001000,
            "completedAt": 1700000007000,
            "tools": [],
        },
    ]
    phases = [
        {"id": "phase-plan-1", "type": "plan_created", "label": "Plan built — 2 steps", "timestamp": 1700000000000},
        {"id": "phase-gate-pass-1", "type": "gate_passed", "label": "Verified — acceptance gate passed", "timestamp": 1700000008000},
    ]
    store.append(
        "s1",
        Message(role=Role.USER, content="build a cli"),
    )
    store.append(
        "s1",
        Message(
            role=Role.ASSISTANT,
            content="Done.",
            agent_runs=runs,
            agent_phases=phases,
        ),
    )
    history = store.get_history("s1")
    assistant = history[-1]
    assert assistant.agent_runs == runs
    assert assistant.agent_phases == phases
    recent = store.get_recent_history("s1", limit=2)
    assert recent[0].agent_runs == runs
    assert recent[0].agent_phases == phases


def test_message_roundtrips_diff_data_and_candidates(store):
    """The structured edit diff + best-of-N candidate list persist with the
    assistant message and round-trip through both history readers so the
    rendered diff / comparison survives a reload."""
    diff = {
        "hunks": [
            {
                "filePath": "src/foo.py",
                "lines": [
                    {"type": "removed", "content": "x = 1", "oldLine": 10},
                    {"type": "added", "content": "x = 2", "newLine": 10},
                ],
            }
        ],
        "language": "python",
        "filePath": "src/foo.py",
        "additions": 1,
        "deletions": 1,
    }
    candidates = [
        {"index": 0, "strategy": "conservative", "rationale": "smallest change", "isWinner": False},
        {"index": 1, "strategy": "refactor", "rationale": "clearer structure", "isWinner": True},
    ]
    store.append(
        "s1",
        Message(
            role=Role.ASSISTANT,
            content="Edited foo.py.",
            diff_data=diff,
            candidates=candidates,
            metrics={"prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 100, "think_ms": 4200},
        ),
    )
    history = store.get_history("s1")
    m = history[0]
    assert m.diff_data == diff
    assert m.candidates == candidates
    assert m.metrics["think_ms"] == 4200
    recent = store.get_recent_history("s1", limit=2)
    assert recent[0].diff_data == diff
    assert recent[0].candidates == candidates


def test_messages_without_diff_or_candidates_roundtrip_none(store):
    store.append("s1", Message(role=Role.ASSISTANT, content="plain"))
    m = store.get_history("s1")[0]
    assert m.diff_data is None
    assert m.candidates is None


def test_observation_save_get_roundtrips(store):
    """The merged observation + snapshot summary persist to the
    observations table (one row per session, latest turn wins) and the two
    writers do not clobber each other."""
    assert store.get_observation("s1") is None

    store.save_observation(
        "s1",
        data={"intent": "parent", "context_tokens": 900, "latency_ms": 1200, "tools_used": "shell,git"},
    )
    store.save_observation(
        "s1",
        snapshot={"timestamp": 1700000000.0, "workspace": {"git_available": True}, "recent_events": []},
    )

    obs = store.get_observation("s1")
    assert obs["data"]["intent"] == "parent"
    assert obs["data"]["context_tokens"] == 900
    # The snapshot write must not have clobbered the data column.
    assert obs["data"]["tools_used"] == "shell,git"
    assert obs["snapshot"]["workspace"]["git_available"] is True

    # Latest turn wins — data-only write replaces the previous data but keeps
    # the snapshot (only provided columns are touched).
    store.save_observation("s1", data={"intent": "parent", "context_tokens": 2000})
    obs = store.get_observation("s1")
    assert obs["data"]["context_tokens"] == 2000
    assert obs["snapshot"] is not None


def test_observation_cascades_on_session_delete(store):
    store.ensure_session("s1")
    store.save_observation("s1", data={"intent": "parent"})
    assert store.get_observation("s1") is not None
    store.delete_session("s1")
    assert store.get_observation("s1") is None


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


def test_drop_last_turn_removes_only_the_failed_attempt(store):
    for role, text in [(Role.USER, "first"), (Role.ASSISTANT, "ok"), (Role.USER, "again"), (Role.ASSISTANT, "")]:
        store.append("s1", Message(role=role, content=text))
    assert store.drop_last_turn("s1", "again") is True
    assert [m.content for m in store.get_history("s1")] == ["first", "ok"]


def test_drop_last_turn_refuses_when_the_trailing_turn_is_not_the_retried_question(store):
    store.append("s1", Message(role=Role.USER, content="other"))
    store.append("s1", Message(role=Role.ASSISTANT, content="reply"))
    assert store.drop_last_turn("s1", "something else") is False
    assert len(store.get_history("s1")) == 2


def test_drop_last_turn_without_content_removes_any_trailing_pair(store):
    store.append("s1", Message(role=Role.USER, content="keep"))
    store.append("s1", Message(role=Role.ASSISTANT, content="ok"))
    store.append("s1", Message(role=Role.USER, content="old wording"))
    store.append("s1", Message(role=Role.ASSISTANT, content="answer"))
    assert store.drop_last_turn("s1") is True
    assert [m.content for m in store.get_history("s1")] == ["keep", "ok"]

"""Session 27: tests for the todo API + engine todo plan emission."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Create a test app with a temp DB."""
    db_path = str(tmp_path / "test_todos.db")
    monkeypatch.setenv("LOCALMIND_DB_PATH", db_path)

    # Patch the settings object directly — it was already initialized
    # at module import time, so monkeypatching the env var alone doesn't
    # change settings.localmind_db_path.
    from core.config import settings

    monkeypatch.setattr(settings, "localmind_db_path", db_path)

    # Initialize the DB with the todos table
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS todos (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL,
            content     TEXT NOT NULL,
            completed   INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'pending',
            priority    TEXT DEFAULT 'medium',
            "order"     INTEGER DEFAULT 0,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        )"""
    )
    conn.commit()
    conn.close()

    app = create_app()
    return TestClient(app)


def test_get_todos_empty(app_client):
    """GET /todos returns empty list when no todos exist."""
    resp = app_client.get("/api/todos")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_todo(app_client):
    """POST /todos creates a todo and it persists."""
    resp = app_client.post(
        "/api/todos",
        json={"session_id": "s1", "content": "Search the web", "priority": "high"},
    )
    assert resp.status_code == 200
    todo = resp.json()
    assert todo["content"] == "Search the web"
    assert todo["session_id"] == "s1"
    assert todo["completed"] is False
    assert todo["status"] == "pending"
    assert todo["priority"] == "high"

    # Verify it persists
    resp = app_client.get("/api/todos?session_id=s1")
    assert len(resp.json()) == 1
    assert resp.json()[0]["content"] == "Search the web"


def test_update_todo_mark_done(app_client):
    """PATCH /todos/{id} marks a todo as done."""
    # Create
    resp = app_client.post(
        "/api/todos",
        json={"session_id": "s1", "content": "Step 1"},
    )
    todo_id = resp.json()["id"]

    # Update — mark done
    resp = app_client.patch(
        f"/api/todos/{todo_id}",
        json={"completed": True},
    )
    assert resp.status_code == 200
    assert resp.json()["completed"] is True
    assert resp.json()["status"] == "done"


def test_update_todo_status(app_client):
    """PATCH /todos/{id} updates status to in_progress."""
    resp = app_client.post(
        "/api/todos",
        json={"session_id": "s1", "content": "Step 1"},
    )
    todo_id = resp.json()["id"]

    resp = app_client.patch(
        f"/api/todos/{todo_id}",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"
    assert resp.json()["completed"] is False


def test_batch_create_todos(app_client):
    """POST /todos/batch creates multiple todos at once."""
    resp = app_client.post(
        "/api/todos/batch",
        json={
            "session_id": "s1",
            "todos": ["Step 1", "Step 2", "Step 3"],
            "clear_existing": True,
        },
    )
    assert resp.status_code == 200
    todos = resp.json()
    assert len(todos) == 3
    assert todos[0]["content"] == "Step 1"
    assert todos[0]["order"] == 0
    assert todos[1]["content"] == "Step 2"
    assert todos[1]["order"] == 1
    assert todos[2]["content"] == "Step 3"
    assert todos[2]["order"] == 2


def test_batch_create_clears_existing(app_client):
    """POST /todos/batch with clear_existing clears prior todos."""
    # Create one todo first
    app_client.post("/api/todos", json={"session_id": "s1", "content": "Old"})

    # Batch create with clear_existing
    resp = app_client.post(
        "/api/todos/batch",
        json={
            "session_id": "s1",
            "todos": ["New 1", "New 2"],
            "clear_existing": True,
        },
    )
    assert len(resp.json()) == 2

    # Verify only 2 todos exist (old one cleared)
    resp = app_client.get("/api/todos?session_id=s1")
    assert len(resp.json()) == 2
    assert resp.json()[0]["content"] == "New 1"


def test_delete_todo(app_client):
    """DELETE /todos/{id} removes the todo."""
    resp = app_client.post("/api/todos", json={"session_id": "s1", "content": "Temp"})
    todo_id = resp.json()["id"]

    resp = app_client.delete(f"/api/todos/{todo_id}")
    assert resp.status_code == 200

    resp = app_client.get("/api/todos?session_id=s1")
    assert len(resp.json()) == 0


def test_clear_session_todos(app_client):
    """DELETE /todos/session/{id} clears all todos for a session."""
    app_client.post("/api/todos", json={"session_id": "s1", "content": "A"})
    app_client.post("/api/todos", json={"session_id": "s1", "content": "B"})
    app_client.post("/api/todos", json={"session_id": "s2", "content": "C"})

    resp = app_client.delete("/api/todos/session/s1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2

    # s1 is empty, s2 still has 1
    assert len(app_client.get("/api/todos?session_id=s1").json()) == 0
    assert len(app_client.get("/api/todos?session_id=s2").json()) == 1


def test_todos_ordered_by_order_field(app_client):
    """GET /todos returns todos ordered by the 'order' field."""
    app_client.post(
        "/api/todos/batch",
        json={
            "session_id": "s1",
            "todos": ["First", "Second", "Third"],
        },
    )

    resp = app_client.get("/api/todos?session_id=s1")
    todos = resp.json()
    assert todos[0]["content"] == "First"
    assert todos[1]["content"] == "Second"
    assert todos[2]["content"] == "Third"


# ── Engine todo plan emission ────────────────────────────────────────────────


def test_engine_emit_todo_plan(tmp_path, monkeypatch):
    """Engine._emit_todo_plan creates todos in the DB for multi-step intents."""
    from core.config import settings
    from core.engine._pipeline import Engine
    from core.models import Intent
    from core.obs import ObsCollector

    db_path = str(tmp_path / "test_engine_todos.db")
    monkeypatch.setenv("LOCALMIND_DB_PATH", db_path)
    monkeypatch.setattr(settings, "localmind_db_path", db_path)

    # Create the todos table
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS todos (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, content TEXT NOT NULL,
            completed INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium', "order" INTEGER DEFAULT 0,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        )"""
    )
    conn.commit()
    conn.close()

    engine = Engine()
    obs = ObsCollector()
    session_id = "test-plan-session"

    # Emit a plan for WEB_SEARCH
    engine._emit_todo_plan(session_id, Intent.WEB_SEARCH, "trending stories", obs)

    # Verify todos were created in the DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT * FROM todos WHERE session_id = ? ORDER BY "order"',
        (session_id,),
    ).fetchall()
    conn.close()

    assert len(rows) == 3
    # Derive expectations from the SAME fallback factory the engine uses, so
    # a template edit cannot silently re-break this test (this exact staleness
    # caused the long-lived '1 known baseline' failure, fixed Session 90).
    from core.engine._pipeline import _fallback_todo_plan

    expected = _fallback_todo_plan(Intent.WEB_SEARCH, "trending stories")
    for i, content in enumerate(expected):
        assert rows[i]["content"] == content

    # Verify obs events were emitted
    events = obs.drain()
    todo_events = [e for e in events if e.type == "todo_added"]
    assert len(todo_events) == 3


def test_engine_emit_todo_plan_skips_chat(tmp_path, monkeypatch):
    """Engine._emit_todo_plan does NOT create todos for CHAT intent
    (single-step, no plan needed)."""
    from core.engine._pipeline import Engine
    from core.models import Intent
    from core.obs import ObsCollector

    db_path = str(tmp_path / "test_engine_todos2.db")
    monkeypatch.setenv("LOCALMIND_DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS todos (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, content TEXT NOT NULL,
            completed INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium', "order" INTEGER DEFAULT 0,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        )"""
    )
    conn.commit()
    conn.close()

    engine = Engine()
    obs = ObsCollector()

    engine._emit_todo_plan("test-session", Intent.CHAT, "hi", obs)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT * FROM todos").fetchall()
    conn.close()

    assert len(rows) == 0  # CHAT doesn't get a plan

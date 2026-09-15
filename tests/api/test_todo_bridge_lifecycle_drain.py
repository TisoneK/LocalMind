"""Todo events must survive the S296 lifecycle drain.

Root cause (live-found): `_drain_live_lifecycle_events` forwards EVERY
non-tool obs event as a generic `obs_event` — including todo_created and
todo_completed. The dedicated todo SSE (which drives the frontend Todos
panel) and the DB persist only ran in the main text-chunk handler, so on a
no-intermediate-text turn the goal checklist was never persisted, and the
end-of-turn todo_completed upserted plan-0 with EMPTY text.

Fix: a shared `_bridge_todo_event()` helper (persist + dedicated SSE) now
runs in BOTH the main handler and the lifecycle drain.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import api.routes.chat as chat_routes
from core.obs import ObsCollector


def _make_engine():
    store = MagicMock()
    engine = MagicMock()
    engine._store = store
    return engine, store


def _emit(obs: ObsCollector, event_type: str, **data):
    obs.emit(event_type, **data)
    return obs.history()[-1]


class TestBridgeTodoEvent:
    def test_todo_created_persists_and_emits_dedicated_sse(self):
        engine, store = _make_engine()
        chat_routes._engine = engine
        evt = _emit(ObsCollector(), "todo_created", id="plan-0", text="create the folder", completed=False)

        out = chat_routes._bridge_todo_event(evt, "s1")
        assert len(out) == 1
        payload = out[0].split("data: ", 1)[1]
        import json

        parsed = json.loads(payload)
        assert parsed["type"] == "todo_created"
        assert parsed["todo"]["id"] == "plan-0"
        assert parsed["todo"]["text"] == "create the folder"

        store.upsert_todo.assert_called_once()
        args = store.upsert_todo.call_args
        assert args.args[0] == "s1"
        assert args.args[1] == "plan-0"
        assert args.kwargs["text"] == "create the folder"

    def test_todo_completed_persists_and_emits_dedicated_sse(self):
        engine, store = _make_engine()
        chat_routes._engine = engine
        evt = _emit(ObsCollector(), "todo_completed", id="plan-1", completed=True)

        out = chat_routes._bridge_todo_event(evt, "s1")
        import json

        parsed = json.loads(out[0].split("data: ", 1)[1])
        assert parsed["type"] == "todo_completed"
        assert parsed["todo"]["id"] == "plan-1"
        store.upsert_todo.assert_called_once()

    def test_non_todo_event_returns_empty(self):
        engine, _ = _make_engine()
        chat_routes._engine = engine
        evt = _emit(ObsCollector(), "agent_planning_done", intent="shell")
        assert chat_routes._bridge_todo_event(evt, "s1") == []

    def test_todo_cleared_clears_store(self):
        engine, store = _make_engine()
        chat_routes._engine = engine
        evt = _emit(ObsCollector(), "todo_cleared")
        chat_routes._bridge_todo_event(evt, "s1")
        store.clear_todos.assert_called_once_with("s1")


class TestLifecycleDrainBridgesTodos:
    def test_drain_emits_generic_plus_dedicated_todo_sse(self):
        engine, store = _make_engine()
        chat_routes._engine = engine
        obs = ObsCollector()
        obs.emit("todo_created", id="plan-0", text="create the folder", completed=False)

        out = list(chat_routes._drain_live_lifecycle_events(obs, "s1"))
        # generic obs_event + dedicated todo_created
        assert len(out) == 2
        import json

        def _event_payload(s: str):
            return json.loads(s.split("data: ", 1)[1])

        payloads = [_event_payload(s) for s in out]
        # One generic obs_event wrapper (Observe panel) + one DEDICATED
        # todo_created SSE (Todos panel) — the dedicated one must exist.
        assert any("obs_event" in p for p in payloads)
        assert any(p.get("type") == "todo_created" for p in payloads)
        store.upsert_todo.assert_called_once()

    def test_drain_persists_goal_checklist_text(self):
        engine, store = _make_engine()
        chat_routes._engine = engine
        obs = ObsCollector()
        for i, step in enumerate(["file exists at a.txt", "folder created at demo-todo"]):
            obs.emit("todo_created", id=f"plan-{i}", text=step, completed=False)

        list(chat_routes._drain_live_lifecycle_events(obs, "s1"))
        assert store.upsert_todo.call_count == 2
        texts = [c.kwargs["text"] for c in store.upsert_todo.call_args_list]
        assert "file exists at a.txt" in texts
        assert "folder created at demo-todo" in texts

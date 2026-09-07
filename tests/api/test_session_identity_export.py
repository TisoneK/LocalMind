"""v3 export identity pass-through — sessions API regression tests.

The v3 chat export needs the raw epoch bounds per chat (createdAt / lastActive)
and the per-turn model/provider identity. The list endpoint now carries both
epoch bounds alongside the legacy merged `timestamp`; the history endpoint
lifts `model` / `provider` out of the persisted metrics into `performance`.
These tests pin the pass-through so the exporter can rely on it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND_SRC = str(Path(__file__).resolve().parents[2] / "backend" / "src")
if _BACKEND_SRC not in sys.path:
    sys.path.insert(0, _BACKEND_SRC)

from api.routes import sessions as sessions_routes  # noqa: E402
from core.models import Message, Role  # noqa: E402
from storage.db import SessionStore  # noqa: E402


@pytest.fixture()
def route_store(tmp_path, monkeypatch):
    """Route modules over an isolated tmp-db SessionStore (never the real one)."""
    store = SessionStore(str(tmp_path / "identity.db"))
    monkeypatch.setattr(sessions_routes, "_store", store, raising=False)
    yield store


def _persist_turn(store: SessionStore, session_id: str, user_text: str, reply: str) -> None:
    store.ensure_session(session_id)
    store.append(session_id, Message(role=Role.USER, content=user_text))
    store.append(
        session_id,
        Message(
            role=Role.ASSISTANT,
            content=reply,
            # Identity travels inside the persisted metrics; the history
            # endpoint lifts it into the performance payload for the export.
            metrics={
                "prompt_tokens": 432,
                "completion_tokens": 87,
                "latency_ms": 900,
                "model": "qwen3.8-flash",
                "provider": "bankofai",
            },
        ),
    )


class TestSessionsListEpochBounds:
    def test_list_carries_created_at_and_last_active(self, route_store):
        route_store.ensure_session("sess-epoch")
        route_store.append("sess-epoch", Message(role=Role.USER, content="when did I ask"))
        route_store.append("sess-epoch", Message(role=Role.ASSISTANT, content="just now"))

        body = asyncio.run(sessions_routes.list_sessions())
        rows = [s for s in body["sessions"] if s["id"] == "sess-epoch"]
        assert len(rows) == 1
        row = rows[0]
        # Legacy merged timestamp still present (back-compat)…
        assert isinstance(row["timestamp"], (int, float))
        # …and the v3 explicit epoch bounds are additive keys.
        assert isinstance(row["createdAt"], (int, float))
        assert isinstance(row["lastActive"], (int, float))

    def test_message_count_includes_user_rows(self, route_store):
        """Pins the all-role count the v3 export count relies on."""
        _persist_turn(route_store, "sess-count", "one user line", "one reply")

        body = asyncio.run(sessions_routes.list_sessions())
        rows = [s for s in body["sessions"] if s["id"] == "sess-count"]
        assert rows[0]["messageCount"] == 2


class TestHistoryIdentity:
    def test_history_lifts_model_and_provider_into_performance(self, route_store):
        _persist_turn(route_store, "sess-ident", "real question", "real answer")

        body = asyncio.run(sessions_routes.get_history("sess-ident"))
        msgs = body["history"]
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        perf = msgs[1]["performance"]
        assert perf["model"] == "qwen3.8-flash"
        assert perf["provider"] == "bankofai"
        # Legacy numeric keys stay intact.
        assert perf["promptTokens"] == 432
        assert perf["completionTokens"] == 87

    def test_history_without_identity_returns_nulls(self, route_store):
        route_store.ensure_session("sess-noident")
        route_store.append("sess-noident", Message(role=Role.USER, content="hi"))
        route_store.append(
            "sess-noident",
            Message(role=Role.ASSISTANT, content="hello", metrics={"prompt_tokens": 5}),
        )

        body = asyncio.run(sessions_routes.get_history("sess-noident"))
        perf = body["history"][1]["performance"]
        assert perf["model"] is None
        assert perf["provider"] is None

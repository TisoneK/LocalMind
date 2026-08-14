"""
Session 26: E2E behavioral tests — structural audit for silent-failure
and state-leak points.

These tests simulate real usage sequences, not just "does function X
return Y." They cover:

1. Session lifecycle: cleanup on delete — state doesn't leak across sessions
2. Adapter contract: unsupported kwargs are logged (not silently swallowed)
3. Engine cleanup_session: all per-session dicts are cleaned

The common thread across nearly every bug found in Sessions 21-25 was
silent failure at a boundary — between sessions, between tools and
generation, between adapters and unsupported params. These tests assert
boundaries hold.
"""

from __future__ import annotations

from adapters.openai_compat import OpenAICompatAdapter

# ── 1. Session lifecycle: cleanup_session removes all per-session state ──────


def test_cleanup_session_removes_intent_history(tmp_path, monkeypatch):
    """cleanup_session() removes the session from _intent_history."""
    from core.engine import Engine

    monkeypatch.setenv("LOCALMIND_DB_PATH", str(tmp_path / "test.db"))
    engine = Engine()

    session_id = "test-session-cleanup-1"
    engine._intent_history[session_id] = ["chat", "shell", "code_exec"]
    assert session_id in engine._intent_history

    engine.cleanup_session(session_id)

    assert session_id not in engine._intent_history


def test_cleanup_session_removes_pending_writes(tmp_path, monkeypatch):
    """cleanup_session() removes pending writes."""
    from core.engine import Engine

    monkeypatch.setenv("LOCALMIND_DB_PATH", str(tmp_path / "test.db"))
    engine = Engine()

    session_id = "test-session-cleanup-2"
    engine._pending_writes[session_id] = {"path": "/tmp/test.py", "content": "x = 1"}
    assert session_id in engine._pending_writes

    engine.cleanup_session(session_id)

    assert session_id not in engine._pending_writes


def test_cleanup_session_removes_pending_clarification(tmp_path, monkeypatch):
    """cleanup_session() removes pending clarifications."""
    from core.engine import Engine

    monkeypatch.setenv("LOCALMIND_DB_PATH", str(tmp_path / "test.db"))
    engine = Engine()

    session_id = "test-session-cleanup-3"
    engine._pending_clarification[session_id] = {"question": "What file?", "intent": "file_task"}
    assert session_id in engine._pending_clarification

    engine.cleanup_session(session_id)

    assert session_id not in engine._pending_clarification


def test_cleanup_session_removes_last_code(tmp_path, monkeypatch):
    """cleanup_session() removes cached code."""
    from core.engine import Engine

    monkeypatch.setenv("LOCALMIND_DB_PATH", str(tmp_path / "test.db"))
    engine = Engine()

    session_id = "test-session-cleanup-4"
    engine._last_code[session_id] = {"lang": "python", "code": "print('hi')"}
    assert session_id in engine._last_code

    engine.cleanup_session(session_id)

    assert session_id not in engine._last_code


def test_cleanup_session_removes_last_observation(tmp_path, monkeypatch):
    """cleanup_session() removes cached observations."""
    from core.engine import Engine

    monkeypatch.setenv("LOCALMIND_DB_PATH", str(tmp_path / "test.db"))
    engine = Engine()

    session_id = "test-session-cleanup-5"
    engine._last_observation[session_id] = {"intent": "chat", "confidence": 0.9}
    assert session_id in engine._last_observation

    engine.cleanup_session(session_id)

    assert session_id not in engine._last_observation


def test_cleanup_session_does_not_affect_other_sessions(tmp_path, monkeypatch):
    """cleanup_session() only removes the specified session — not others."""
    from core.engine import Engine

    monkeypatch.setenv("LOCALMIND_DB_PATH", str(tmp_path / "test.db"))
    engine = Engine()

    session_a = "test-session-a"
    session_b = "test-session-b"
    engine._intent_history[session_a] = ["chat"]
    engine._intent_history[session_b] = ["shell"]
    engine._pending_writes[session_a] = {"path": "/a.py"}
    engine._pending_writes[session_b] = {"path": "/b.py"}

    engine.cleanup_session(session_a)

    assert session_a not in engine._intent_history
    assert session_a not in engine._pending_writes
    assert session_b in engine._intent_history
    assert session_b in engine._pending_writes


def test_cleanup_session_idempotent(tmp_path, monkeypatch):
    """cleanup_session() on a non-existent session doesn't crash."""
    from core.engine import Engine

    monkeypatch.setenv("LOCALMIND_DB_PATH", str(tmp_path / "test.db"))
    engine = Engine()

    engine.cleanup_session("nonexistent-session")
    engine.cleanup_session("nonexistent-session")


# ── 2. SessionContextManager cleanup ─────────────────────────────────────────


def test_session_context_clear_session():
    """SessionContextManager.clear_session() removes the session context."""
    from core.session_context import SessionContextManager

    mgr = SessionContextManager()
    session_id = "test-ctx-cleanup"

    mgr.get_context(session_id)
    assert session_id in mgr._contexts

    result = mgr.clear_session(session_id)
    assert result is True
    assert session_id not in mgr._contexts

    result = mgr.clear_session(session_id)
    assert result is False


# ── 3. Adapter contract: unsupported kwargs are logged ──────────────────────


def test_adapter_chat_logs_unsupported_kwargs(caplog):
    """OpenAICompatAdapter.chat() logs a warning for unsupported kwargs
    instead of silently swallowing them. This is the fix for the
    stream=True bug class from Session 24.

    We test the kwargs validation logic directly — the adapter's __init__
    requires an API key which isn't available in the test environment,
    but the kwargs validation is in chat() not __init__()."""
    import logging
    from unittest.mock import MagicMock, patch

    # Mock the adapter so we can call chat() without a real API key
    with patch.object(OpenAICompatAdapter, "_chat_openai_style") as mock_chat:
        # Make the mock yield nothing (empty stream)
        async def _empty_stream(*args, **kwargs):
            return
            yield  # never reached — makes it an async generator

        mock_chat.side_effect = _empty_stream

        # Create an adapter instance without going through __init__
        adapter = OpenAICompatAdapter.__new__(OpenAICompatAdapter)
        adapter._provider_name = "openai"
        adapter._timeouts = {"chat": 10}

        with caplog.at_level(logging.WARNING, logger="adapters.openai_compat"):
            import asyncio

            async def _test():
                try:
                    async for _ in adapter.chat(
                        [{"role": "user", "content": "hi"}],
                        stream=True,
                        some_other_bad_param="bad",
                    ):
                        pass
                except Exception:
                    pass

            asyncio.run(_test())

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("unsupported kwargs" in r.message.lower() for r in warnings), (
        f"Expected 'unsupported kwargs' warning, got: {[r.message for r in warnings]}"
    )


# ── 4. Engine state isolation: new sessions get fresh state ──────────────────


def test_new_session_gets_fresh_intent_history(tmp_path, monkeypatch):
    """A new session_id gets an empty intent history — no leakage from
    a previous session that used the same ID (after cleanup)."""
    from core.engine import Engine
    from core.models import Intent

    monkeypatch.setenv("LOCALMIND_DB_PATH", str(tmp_path / "test.db"))
    engine = Engine()

    session_id = "test-recycle-id"

    engine._update_intent_history(session_id, Intent.CHAT)
    engine._update_intent_history(session_id, Intent.SHELL)
    assert len(engine._intent_history[session_id]) == 2

    engine.cleanup_session(session_id)
    assert session_id not in engine._intent_history

    engine._update_intent_history(session_id, Intent.CODE_EXEC)
    assert len(engine._intent_history[session_id]) == 1
    assert engine._intent_history[session_id] == ["code_exec"]

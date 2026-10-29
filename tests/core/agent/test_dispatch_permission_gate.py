"""§U item 5 — the permission gate enforced at the tool-dispatch seam.

``dispatch_with_retry`` resolves the running session's pinned file-effect mode
and, for a file-effecting intent, denies before the tool body can run, journals
an allowed call 'pending' → terminal, and fails closed when the mode cannot be
read. These tests drive that seam with a stubbed ``dispatch`` and a temp store,
so no real tool runs.
"""

from __future__ import annotations

import core.agent.tool_dispatch as td
import core.permission_mode as pm
import pytest
from core.models import Intent, ToolResult
from core.session_workspace import reset_current_session, set_current_session
from storage.db import SessionStore


@pytest.fixture
def wired(tmp_db, monkeypatch):
    """A temp store wired into the dispatch seam, with a bound session id.
    Yields (store, session_id); unbinds the contextvar on teardown."""
    store = SessionStore(tmp_db)
    monkeypatch.setattr(td, "_perm_store", lambda: store)
    token = set_current_session("sess-gate")
    try:
        yield store, "sess-gate"
    finally:
        reset_current_session(token)


def _stub_dispatch(monkeypatch, calls):
    async def fake(intent, tool_input):
        calls.append((intent, tool_input))
        return ToolResult(content="ok", source=intent.value, success=True)

    monkeypatch.setattr(td, "dispatch", fake)


@pytest.mark.asyncio
async def test_read_only_denies_write_before_the_body_runs(wired, monkeypatch):
    store, sid = wired
    store.set_permission_mode(sid, "read_only")
    calls: list = []
    _stub_dispatch(monkeypatch, calls)

    result, failed, retries = await td.dispatch_with_retry(Intent.FILE_WRITE, "x.txt:\n\nhi")

    assert failed is True
    assert result.success is False
    assert result.error_type == "permission"
    assert calls == []  # body never ran
    rows = store.list_permission_audit(sid)
    assert rows[0]["decision"] == "deny" and rows[0]["outcome"] == "done"


@pytest.mark.asyncio
async def test_workspace_allows_and_journals_pending_then_done(wired, monkeypatch):
    store, sid = wired
    store.set_permission_mode(sid, "workspace_write")
    calls: list = []
    _stub_dispatch(monkeypatch, calls)

    result, failed, _ = await td.dispatch_with_retry(Intent.FILE_WRITE, "x.txt:\n\nhi")

    assert failed is False and result.success is True
    assert len(calls) == 1  # body ran exactly once
    row = store.list_permission_audit(sid)[0]
    assert row["decision"] == "allow"
    assert row["outcome"] == "done"  # pending was resolved after the body


@pytest.mark.asyncio
async def test_allowed_call_that_fails_is_journalled_failed(wired, monkeypatch):
    store, sid = wired
    store.set_permission_mode(sid, "workspace_write")

    async def boom(intent, tool_input):
        return ToolResult(content="nope", source=intent.value, success=False, error_type="runtime")

    monkeypatch.setattr(td, "dispatch", boom)

    _, failed, _ = await td.dispatch_with_retry(Intent.SHELL, "ls", max_retries=0)
    assert failed is True
    assert store.list_permission_audit(sid)[0]["outcome"] == "failed"


@pytest.mark.asyncio
async def test_fail_closed_when_mode_read_raises(wired, monkeypatch):
    store, sid = wired

    def boom(_sid):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "get_permission_mode", boom)
    calls: list = []
    _stub_dispatch(monkeypatch, calls)

    result, failed, _ = await td.dispatch_with_retry(Intent.CODE_EXEC, "print(1)")

    assert failed is True and result.success is False
    assert result.error_type == "permission"
    assert calls == []
    row = store.list_permission_audit(sid)[0]
    assert row["decision"] == "deny" and row["fail_closed"] is True


@pytest.mark.asyncio
async def test_non_effecting_intent_is_not_gated(wired, monkeypatch):
    store, sid = wired
    store.set_permission_mode(sid, "read_only")  # would block effects
    calls: list = []
    _stub_dispatch(monkeypatch, calls)

    result, failed, _ = await td.dispatch_with_retry(Intent.WEB_SEARCH, "weather")

    assert failed is False and result.success is True
    assert len(calls) == 1
    assert store.list_permission_audit(sid) == []  # reads are never audited by mode


@pytest.mark.asyncio
async def test_no_session_falls_back_to_default_without_audit(tmp_db, monkeypatch):
    # No bound session id → the shipped default (workspace_write), allowed, and
    # nothing journalled (no session to attribute the row to). Guards against a
    # regression of today's no-session tool behaviour.
    store = SessionStore(tmp_db)
    monkeypatch.setattr(td, "_perm_store", lambda: store)
    calls: list = []
    _stub_dispatch(monkeypatch, calls)

    result, failed, _ = await td.dispatch_with_retry(Intent.FILE_WRITE, "x.txt:\n\nhi")

    assert failed is False and result.success is True
    assert len(calls) == 1

"""§U item 5 — permission modes (row H) + the durable audit/journal (row J).

Three layers, pinned by these tests:

  * ``permission_mode.decide`` is pure: the verdict depends only on (mode,
    intent). Read-only denies file effects and allows reads; workspace/full
    permit the effect class; an unresolved mode fails closed for an effecting
    intent but never for a read.
  * The store pins a mode per session durably — a *new* ``SessionStore`` on the
    same DB file reads the pin back (the "survives restart" guarantee) — and
    records every decision in a model-invisible audit log.
  * The write-ahead journal recovers an interrupted effecting call as
    ``unknown`` on store open, never silently re-executed.
"""

from __future__ import annotations

from pathlib import Path

import core.permission_mode as pm
from core.models import Intent
from storage.db import SessionStore

EFFECTING = [Intent.FILE_WRITE, Intent.FILE_EDIT, Intent.APPLY_PROPOSED, Intent.SHELL, Intent.CODE_EXEC]
NON_EFFECTING = [Intent.FILE_TASK, Intent.GREP_SEARCH, Intent.WEB_SEARCH, Intent.WEB_FETCH, Intent.MEMORY_OP, Intent.CHAT]


# ── decide(): pure policy ───────────────────────────────────────────────────

def test_read_only_denies_every_effecting_intent():
    for intent in EFFECTING:
        d = pm.decide(pm.FileEffectMode.READ_ONLY, intent)
        assert d.allowed is False
        assert d.fail_closed is False  # policy denial, not a fault
        assert d.decision == "deny"


def test_read_only_allows_reads_and_web():
    for intent in NON_EFFECTING:
        assert pm.decide(pm.FileEffectMode.READ_ONLY, intent).allowed is True


def test_workspace_and_full_permit_the_effect_class():
    for mode in (pm.FileEffectMode.WORKSPACE_WRITE, pm.FileEffectMode.FULL):
        for intent in EFFECTING:
            assert pm.decide(mode, intent).allowed is True


def test_unresolved_mode_fails_closed_for_effects_only():
    for intent in EFFECTING:
        d = pm.decide(None, intent)
        assert d.allowed is False
        assert d.fail_closed is True
        assert d.mode is None
    for intent in NON_EFFECTING:
        # A read was never a file effect — an unresolved mode never blocks it.
        assert pm.decide(None, intent).allowed is True


def test_coerce_mode():
    assert pm.coerce_mode("full") is pm.FileEffectMode.FULL
    assert pm.coerce_mode("  Read_Only ") is pm.FileEffectMode.READ_ONLY
    assert pm.coerce_mode(pm.FileEffectMode.FULL) is pm.FileEffectMode.FULL
    assert pm.coerce_mode("nonsense") is None
    assert pm.coerce_mode(None) is None
    assert pm.coerce_mode(42) is None


def test_default_mode_is_workspace_write():
    assert pm.DEFAULT_MODE is pm.FileEffectMode.WORKSPACE_WRITE


def test_write_path_allowed_full_lifts_boundary():
    class _S:
        def is_path_allowed(self, path):  # noqa: D401 — never consulted for full
            raise AssertionError("full mode must not consult the folder boundary")

    assert pm.write_path_allowed(pm.FileEffectMode.FULL, "/anywhere", _S()) is True


def test_write_path_allowed_non_full_keeps_boundary_and_fails_closed():
    class _Yes:
        def is_path_allowed(self, path):
            return True

    class _Boom:
        def is_path_allowed(self, path):
            raise RuntimeError("boom")

    assert pm.write_path_allowed(pm.FileEffectMode.WORKSPACE_WRITE, "/p", _Yes()) is True
    # A boundary check that raises is a fault → closed (False), never True.
    assert pm.write_path_allowed(pm.FileEffectMode.WORKSPACE_WRITE, "/p", _Boom()) is False
    assert pm.write_path_allowed(None, "/p", _Boom()) is False


# ── store: pin is durable and session-scoped ────────────────────────────────

def test_mode_pin_round_trip_and_default(tmp_db):
    store = SessionStore(tmp_db)
    sid = "sess-mode"
    assert store.get_permission_mode(sid) is None  # unpinned
    store.set_permission_mode(sid, pm.FileEffectMode.READ_ONLY.value)
    assert store.get_permission_mode(sid) == "read_only"
    # overwrite
    store.set_permission_mode(sid, pm.FileEffectMode.FULL.value)
    assert store.get_permission_mode(sid) == "full"


def test_mode_pin_survives_a_fresh_store_on_the_same_db(tmp_db):
    SessionStore(tmp_db).set_permission_mode("sess-restart", "read_only")
    # A brand-new store object on the same file = a backend restart.
    assert SessionStore(tmp_db).get_permission_mode("sess-restart") == "read_only"


def test_mode_pin_never_crosses_sessions(tmp_db):
    store = SessionStore(tmp_db)
    store.set_permission_mode("sess-a", "read_only")
    assert store.get_permission_mode("sess-b") is None


def test_delete_session_clears_the_pin_and_audit(tmp_db):
    store = SessionStore(tmp_db)
    sid = "sess-del"
    store.set_permission_mode(sid, "read_only")
    store.record_permission_decision(sid, "file_write", "read_only", "deny", "nope")
    store.delete_session(sid)
    assert store.get_permission_mode(sid) is None
    assert store.list_permission_audit(sid) == []


# ── store: audit + write-ahead journal ──────────────────────────────────────

def test_audit_records_a_denial(tmp_db):
    store = SessionStore(tmp_db)
    sid = "sess-audit"
    store.record_permission_decision(
        sid, "file_write", "read_only", "deny", "read-only mode", outcome="done"
    )
    rows = store.list_permission_audit(sid)
    assert len(rows) == 1
    assert rows[0]["decision"] == "deny"
    assert rows[0]["tool"] == "file_write"
    assert rows[0]["outcome"] == "done"


def test_journal_pending_resolves_to_done(tmp_db):
    store = SessionStore(tmp_db)
    sid = "sess-journal"
    aid = store.record_permission_decision(
        sid, "file_write", "workspace_write", "allow", "ok", outcome="pending"
    )
    assert isinstance(aid, int)
    assert store.list_permission_audit(sid)[0]["outcome"] == "pending"
    store.resolve_tool_effect(aid, "done")
    assert store.list_permission_audit(sid)[0]["outcome"] == "done"


def test_interrupted_pending_recovers_as_unknown_on_restart(tmp_db):
    # An allowed effecting call journalled 'pending' whose body never resolved.
    store = SessionStore(tmp_db)
    sid = "sess-crash"
    store.record_permission_decision(
        sid, "shell", "workspace_write", "allow", "ok", outcome="pending"
    )
    # A fresh store = restart. Its _init_db reconcile must sweep the pending row.
    reopened = SessionStore(tmp_db)
    row = reopened.list_permission_audit(sid)[0]
    assert row["outcome"] == "unknown"
    # And a late resolve from a since-dead process must NOT revive it.
    reopened.resolve_tool_effect(row["id"], "done")
    assert reopened.list_permission_audit(sid)[0]["outcome"] == "unknown"


def test_reconcile_returns_count_and_is_idempotent(tmp_db):
    store = SessionStore(tmp_db)
    store.record_permission_decision("s1", "shell", "full", "allow", "", outcome="pending")
    store.record_permission_decision("s2", "code_exec", "full", "allow", "", outcome="pending")
    assert store.reconcile_interrupted_effects() == 2
    assert store.reconcile_interrupted_effects() == 0  # nothing left pending


# ── config.is_path_allowed: full mode lifts the workspace boundary ──────────
# The workspace↔full distinction is enforced at the one path boundary used by
# the boundary-checking tools (edit_file, file reads, dir/csv/json/sql). full
# lifts it; every other mode — and no session — keeps it.

#   An absolute path that is under no allowed folder (never needs to exist —
#   is_path_allowed resolves it non-strictly, and the full-mode case returns
#   before resolving). Patching storage.db.get_shared_store (config imports it
#   lazily inside the method) wires the pin store without touching the frozen
#   settings model.
_OUTSIDE = Path("/__perm_mode_test_root__/secret.txt")


def test_full_mode_lifts_the_path_boundary(tmp_db, monkeypatch):
    import storage.db as dbmod
    from core.config import settings
    from core.session_workspace import reset_current_session, set_current_session

    store = SessionStore(tmp_db)
    monkeypatch.setattr(dbmod, "get_shared_store", lambda *a, **k: store)

    # No session bound yet → the lift never engages → outside path blocked.
    assert settings.is_path_allowed(_OUTSIDE) is False

    token = set_current_session("sess-full")
    try:
        store.set_permission_mode("sess-full", "full")
        assert settings.is_path_allowed(_OUTSIDE) is True  # boundary lifted
        store.set_permission_mode("sess-full", "read_only")
        assert settings.is_path_allowed(_OUTSIDE) is False  # kept (fail-closed default)
    finally:
        reset_current_session(token)


def test_path_boundary_unchanged_without_a_session():
    from core.config import settings

    # No bound session → the lift never engages, folder boundary holds.
    assert settings.is_path_allowed(_OUTSIDE) is False

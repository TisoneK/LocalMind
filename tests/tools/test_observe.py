"""
Tests for the observe tool (Session 130, B-2026-07-31-9).

Design contract (learned from the Session 124/125 context-flood bugs):
  - BOUNDED output by construction: caps on running apps and recent
    files, no raw dumps.
  - GRACEFUL DEGRADATION: every sub-query degrades to a short note on
    unsupported platforms / missing CLIs — never an exception, never a
    silent empty answer. That is the user's core complaint: silent
    failure is worse than slow failure.

The platform-dependent sub-queries (active window, clipboard) are tested
via monkeypatched platform helpers; the deterministic ones (system state,
recent files) are tested directly.
"""

from __future__ import annotations

from tools.observe import _observe, _recent_files, _running_apps, _system_state, observe


def _allow(monkeypatch, tmp_path):
    """Make tmp_path an allowed folder (tmp is normally outside ~).

    Mirrors tests/tools/test_find_path.py — recent_files enforces
    settings.is_path_allowed so it can't dump arbitrary filenames.
    """
    from pathlib import Path

    # macOS tmp_path is /var/... but resolves to /private/var/... — include both.
    monkeypatch.setattr(
        "core.config._allowed_user_folders",
        lambda: [str(tmp_path), str(tmp_path.resolve()), str(Path.home())],
    )


# ── Routing ───────────────────────────────────────────────────────────────────


def test_default_query_returns_summary(monkeypatch):
    """No keywords → window + apps + state summary (compact, multi-line)."""
    monkeypatch.setattr("tools.observe._active_window", lambda: "Active window: TestApp")
    monkeypatch.setattr("tools.observe._running_apps", lambda: "Running apps: fake")
    monkeypatch.setattr("tools.observe._system_state", lambda: "System state: fake")
    out = _observe("what is happening right now")
    assert "Active window: TestApp" in out
    assert "Running apps" in out
    assert "System state" in out


def test_clipboard_keyword_routes_only_to_clipboard(monkeypatch):
    monkeypatch.setattr("tools.observe._clipboard", lambda: "Clipboard: hello")
    monkeypatch.setattr("tools.observe._active_window", lambda: "SHOULD NOT RUN")
    monkeypatch.setattr("tools.observe._running_apps", lambda: "SHOULD NOT RUN")
    monkeypatch.setattr("tools.observe._system_state", lambda: "SHOULD NOT RUN")
    out = _observe("what's on my clipboard")
    assert out == "Clipboard: hello"


def test_recent_files_keyword(monkeypatch):
    monkeypatch.setattr("tools.observe._recent_files", lambda q: "Recent: fake")
    out = _observe("show me recently modified files")
    assert "Recent: fake" in out


def test_window_keyword(monkeypatch):
    monkeypatch.setattr("tools.observe._active_window", lambda: "Active window: X")
    monkeypatch.setattr("tools.observe._running_apps", lambda: "SHOULD NOT RUN")
    monkeypatch.setattr("tools.observe._system_state", lambda: "SHOULD NOT RUN")
    out = _observe("which window is active")
    assert "Active window: X" in out
    assert "SHOULD NOT RUN" not in out


# ── Graceful degradation ─────────────────────────────────────────────────────


def test_platform_helpers_never_raise(monkeypatch):
    """Every platform helper must return a string even when commands fail."""
    monkeypatch.setattr("tools.observe._run", lambda *a, **k: "")
    monkeypatch.setattr("tools.observe._is_available", lambda *a: False)
    monkeypatch.setattr("tools.observe._platform", lambda: "darwin")
    out = _observe("active window")
    assert isinstance(out, str)
    assert "unavailable" in out or "Active window" in out


def test_system_state_without_psutil(monkeypatch):
    # Force the `import psutil` inside _system_state() to raise ImportError.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = _system_state()
    assert "unavailable" in out


# ── Bounded output ────────────────────────────────────────────────────────────


def test_running_apps_bounded(monkeypatch):
    class FakeP:
        def __init__(self, name, mem):
            self.info = {"name": name, "memory_percent": mem}

    class FakePsutil:
        @staticmethod
        def process_iter(attrs=None):
            return [FakeP(f"app{i}", float(i)) for i in range(50)]

        class NoSuchProcess(Exception):
            pass

        class AccessDenied(Exception):
            pass

    import sys

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil())
    out = _running_apps()
    # Capped at _MAX_APPS = 8.
    assert out.count("\n- ") <= 8


def test_recent_files_bounded_and_fresh(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    # One fresh file, many stale files.
    (tmp_path / "fresh.txt").write_text("x")
    import os
    import time

    old = time.time() - 7200  # 2h ago — outside the default 60-min window
    os.utime(tmp_path / "fresh.txt", (old, old))
    for i in range(30):
        p = tmp_path / f"stale{i}.txt"
        p.write_text("x")
        os.utime(p, (old, old))
    out = _recent_files("files changed in the last hour")
    assert "No files modified" in out or "Recently modified" in out
    assert out.count("\n") <= 9  # header + ≤8 results


def test_recent_files_rejects_disallowed_path(tmp_path, monkeypatch):
    """A walk root outside allowed folders is refused, not walked."""
    import os

    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        (tmp_path / "secret.txt").write_text("x")
        out = _recent_files("files changed in the last hour")
        assert "not allowed" in out
    finally:
        os.chdir(cwd)


def test_recent_files_custom_window(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "recent.txt").write_text("x")
    out = _recent_files("files changed in the last 120 minutes")
    assert "recent.txt" in out


# ── Async entry point ────────────────────────────────────────────────────────


def test_observe_async_returns_toolresult(monkeypatch):
    monkeypatch.setattr("tools.observe._observe", lambda q: "fake observation")
    import asyncio

    result = asyncio.run(observe("clipboard"))
    assert result.content == "fake observation"
    assert result.source == "observe"


def test_observe_async_never_raises(monkeypatch):
    def boom(q):
        raise RuntimeError("boom")

    monkeypatch.setattr("tools.observe._observe", boom)
    import asyncio

    result = asyncio.run(observe("anything"))
    assert "error" in result.content.lower()

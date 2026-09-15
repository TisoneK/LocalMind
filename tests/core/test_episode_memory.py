"""
ADR-22 P1  — session episode memory tests.

The system-level session distillation layer (invisible to users):
  - store roundtrip / upsert / latest_episode / sessions_needing_episode
  - distill() writes an episode via the adapter when it works
  - deterministic fallback when the adapter fails / returns garbage
  - trivial sessions (<2 user turns) and already-distilled sessions skip
  - format_episode_hint shapes the bridge hint
  - sweep() distills stale un-episoded sessions (restart/crash coverage)
"""

from __future__ import annotations

import time

import pytest
from core.episode_memory import EpisodeMemory, format_episode_hint
from core.models import Message, Role
from storage.db import SessionStore

_EPISODE_TEXT = (
    "Summary: The user asked to find their CV on Windows.\n"
    "Decisions: Use PowerShell for file searches.\n"
    "Failures: Get-ChildItem failed under cmd.exe once.\n"
    "Next steps: Retry the search with the fixed shell routing.\n"
)


def _append(store, session_id, role, content, ts=None):
    store.append(
        session_id,
        Message(role=Role(role), content=content, timestamp=ts or time.time()),
    )


class _Chunk:
    def __init__(self, text="", error=None):
        self.text = text
        self.error = error


class _FakeAdapter:
    """Adapter contract: async chat() yields chunks with .text/.error."""

    def __init__(self, text=None, error=None, raise_exc=None):
        self._text = text
        self._error = error
        self._raise = raise_exc

    async def chat(self, messages, **kwargs):
        if self._raise:
            raise self._raise
        if self._error:
            yield _Chunk(text="", error=self._error)
            return
        yield _Chunk(text=self._text or "")


def _store(tmp_path) -> SessionStore:
    return SessionStore(str(tmp_path / "ep.db"))


# ── Storage layer ────────────────────────────────────────────────────────


def test_store_episode_roundtrip_and_upsert(tmp_path):
    store = _store(tmp_path)
    store.record_episode("s1", summary="first pass", turn_count=3)
    ep = store.get_episode("s1")
    assert ep is not None
    assert ep["summary"] == "first pass"
    assert ep["turn_count"] == 3

    # Re-distill overwrites (one episode per session).
    store.record_episode("s1", summary="second pass", failures="tool x failed", turn_count=5)
    ep = store.get_episode("s1")
    assert ep["summary"] == "second pass"
    assert ep["turn_count"] == 5
    assert ep["failures"] == "tool x failed"


def test_latest_episode_excludes_current(tmp_path):
    store = _store(tmp_path)
    store.record_episode("prev", summary="previous session digest")
    store.record_episode("current", summary="current session digest")

    latest = store.latest_episode(exclude_session_id="current")
    assert latest is not None and latest["session_id"] == "prev"

    latest_all = store.latest_episode()
    assert latest_all is not None and latest_all["session_id"] == "current"


def test_sessions_needing_episode_returns_stale_candidates(tmp_path):
    store = _store(tmp_path)
    old = time.time() - 7200
    _append(store, "stale", "user", "find my cv", old)
    _append(store, "stale", "assistant", "searching", old + 1)
    _append(store, "stale", "user", "read it aloud", old + 2)

    needs = store.sessions_needing_episode(grace_secs=3600, min_turns=2, limit=5)
    assert "stale" in needs


def test_sessions_needing_episode_excludes_fresh_trivial_and_distilled(tmp_path):
    store = _store(tmp_path)
    old = time.time() - 7200
    _append(store, "fresh", "user", "hi", time.time())
    _append(store, "fresh", "user", "yo", time.time() + 1)
    _append(store, "trivial", "user", "hello", old)
    _append(store, "distilled", "user", "task", old)
    _append(store, "distilled", "user", "more", old + 1)
    store.record_episode("distilled", summary="done")

    needs = store.sessions_needing_episode(grace_secs=3600, min_turns=2, limit=5)
    assert needs == []


# ── Distillation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_distill_writes_episode_via_adapter(tmp_path):
    store = _store(tmp_path)
    _append(store, "s1", "user", "find my cv on windows")
    _append(store, "s1", "assistant", "searching your home directory...")
    _append(store, "s1", "user", "thanks")
    _append(store, "s1", "assistant", "found resume.docx")

    ep = EpisodeMemory(store=store, adapter_getter=lambda: _FakeAdapter(text=_EPISODE_TEXT))
    ok = await ep.distill("s1")
    assert ok is True

    row = store.get_episode("s1")
    assert row is not None
    assert "CV" in row["summary"]
    assert row["failures"]
    assert row["next_steps"]
    assert row["turn_count"] == 2


@pytest.mark.asyncio
async def test_distill_falls_back_when_adapter_fails(tmp_path):
    store = _store(tmp_path)
    _append(store, "s1", "user", "find my cv")
    _append(store, "s1", "assistant", "here it is")
    _append(store, "s1", "user", "thanks")

    ep = EpisodeMemory(store=store, adapter_getter=lambda: _FakeAdapter(error="provider 429"))
    ok = await ep.distill("s1")
    assert ok is True  # deterministic fallback still writes the episode

    row = store.get_episode("s1")
    assert row is not None
    assert "find my cv" in row["summary"]


@pytest.mark.asyncio
async def test_distill_falls_back_when_adapter_raises(tmp_path):
    store = _store(tmp_path)
    _append(store, "s1", "user", "do the thing")
    _append(store, "s1", "assistant", "done")
    _append(store, "s1", "user", "and verify it")

    ep = EpisodeMemory(
        store=store, adapter_getter=lambda: _FakeAdapter(raise_exc=RuntimeError("boom"))
    )
    ok = await ep.distill("s1")
    assert ok is True

    row = store.get_episode("s1")
    assert row is not None
    assert "do the thing" in row["summary"]


@pytest.mark.asyncio
async def test_distill_falls_back_on_unparseable_output(tmp_path):
    store = _store(tmp_path)
    _append(store, "s1", "user", "help me set up node")
    _append(store, "s1", "assistant", "sure, here you go")
    _append(store, "s1", "user", "thanks")

    ep = EpisodeMemory(store=store, adapter_getter=lambda: _FakeAdapter(text="no structure at all"))
    ok = await ep.distill("s1")
    assert ok is True

    row = store.get_episode("s1")
    assert row is not None
    assert "help me set up node" in row["summary"]


@pytest.mark.asyncio
async def test_distill_skips_trivial_and_already_distilled(tmp_path):
    store = _store(tmp_path)
    ep = EpisodeMemory(store=store, adapter_getter=lambda: _FakeAdapter(text=_EPISODE_TEXT))

    # One greeting turn — not worth distilling.
    _append(store, "t", "user", "hi")
    assert await ep.distill("t") is False
    assert store.get_episode("t") is None

    # Already distilled at its current size — no re-distill.
    _append(store, "s", "user", "do the thing")
    _append(store, "s", "user", "and more")
    store.record_episode("s", summary="done", turn_count=2)
    assert await ep.distill("s") is False


@pytest.mark.asyncio
async def test_distill_reruns_when_session_grows(tmp_path):
    store = _store(tmp_path)
    _append(store, "s1", "user", "first task")
    _append(store, "s1", "user", "second task")
    store.record_episode("s1", summary="two turns", turn_count=2)

    # User returned and continued the session — re-distill must run.
    _append(store, "s1", "user", "third task")
    _append(store, "s1", "assistant", "done")

    ep = EpisodeMemory(store=store, adapter_getter=lambda: _FakeAdapter(text=_EPISODE_TEXT))
    assert await ep.distill("s1") is True
    row = store.get_episode("s1")
    assert row is not None
    assert row["turn_count"] == 3


def test_needs_distill(tmp_path):
    store = _store(tmp_path)
    ep = EpisodeMemory(store=store, adapter_getter=lambda: None)

    _append(store, "s1", "user", "one turn only")
    assert ep.needs_distill("s1") is False

    _append(store, "s1", "user", "second turn")
    assert ep.needs_distill("s1") is True

    store.record_episode("s1", summary="done")
    assert ep.needs_distill("s1") is False


@pytest.mark.asyncio
async def test_sweep_distills_stale_sessions(tmp_path):
    store = _store(tmp_path)
    old = time.time() - 7200
    _append(store, "a", "user", "task one", old)
    _append(store, "a", "user", "more detail", old + 1)
    _append(store, "b", "user", "task two", old)
    _append(store, "b", "user", "more detail", old + 1)

    ep = EpisodeMemory(store=store, adapter_getter=lambda: _FakeAdapter(text=_EPISODE_TEXT))
    done = await ep.sweep(grace_secs=3600, limit=5)
    assert done == 2
    assert store.get_episode("a") is not None
    assert store.get_episode("b") is not None


# ── Bridge hint ──────────────────────────────────────────────────────────


def test_format_episode_hint_shapes():
    assert format_episode_hint(None) == ""
    assert format_episode_hint({}) == ""

    hint = format_episode_hint(
        {
            "summary": "User built a sports scraper.",
            "failures": "web search timed out once",
            "next_steps": "add Playwright",
        }
    )
    assert "From your previous session" in hint
    assert "scraper" in hint
    assert "Past issues" in hint
    assert "Playwright" in hint

    # NONE sections are skipped, summary alone still produces a bridge.
    hint2 = format_episode_hint({"summary": "hello", "failures": "NONE", "next_steps": "NONE"})
    assert "Past issues" not in hint2
    assert "Left open" not in hint2
    assert "hello" in hint2

    # Empty episode (no content at all) must not inject a bare header.
    assert format_episode_hint({"summary": "", "failures": "", "next_steps": ""}) == ""

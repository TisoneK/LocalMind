"""Tests for the ParentSession rolling summary (ADR-52 phase 2 / B-2026-08-20-1).

Covers:
- compaction policy (tail overflow → summary, summary trim)
- persistence round-trip via SessionStore
- prompt section injection
- from_store / to_store serde
"""

from __future__ import annotations

from core.parent_session import (
    RECENT_TAIL_MAX,
    SUMMARY_MAX_CHARS,
    ParentSession,
)
from storage.db import SessionStore


def test_fresh_session_has_no_summary():
    ps = ParentSession(session_id="s1")
    assert ps.is_empty
    assert ps.to_prompt_section() is None
    assert ps.turn_count == 0
    assert ps.recent_tail == []


def test_single_turn_stays_in_tail_no_summary():
    ps = ParentSession(session_id="s1")
    ps.update_with_turn("Hello", "Hi there!")
    assert ps.turn_count == 1
    assert len(ps.recent_tail) == 1
    assert ps.rolling_summary == ""
    assert ps.to_prompt_section() is None


def test_tail_compacts_when_over_limit():
    ps = ParentSession(session_id="s1")
    for i in range(RECENT_TAIL_MAX + 3):
        ps.update_with_turn(f"q{i}", f"a{i}")
    # Tail is capped at RECENT_TAIL_MAX; the oldest 3 were folded into summary.
    assert len(ps.recent_tail) == RECENT_TAIL_MAX
    assert ps.rolling_summary != ""
    # Most recent tail entry is the last turn we added.
    assert ps.recent_tail[-1]["user"] == f"q{RECENT_TAIL_MAX + 2}"
    # The oldest turns (0, 1, 2) are in the summary, not the tail.
    assert "q0" in ps.rolling_summary
    assert "q1" in ps.rolling_summary
    assert "q2" in ps.rolling_summary
    # The tail holds the most recent turns (not in summary).
    assert "q0" not in ps.recent_tail[-1]["user"]


def test_summary_includes_tool_action():
    ps = ParentSession(session_id="s1")
    ps.update_with_turn("list files", "done", tool_summary="shell(ls -la)")
    # Force compaction by overflowing the tail.
    for i in range(RECENT_TAIL_MAX):
        ps.update_with_turn(f"q{i}", f"a{i}")
    assert "shell(ls -la)" in ps.rolling_summary


def test_summary_trims_at_char_cap():
    ps = ParentSession(session_id="s1")
    # Generate enough turns to blow past SUMMARY_MAX_CHARS (4000 chars / ~35
    # chars per entry ≈ 114 summary entries needed → ~120 turns total).
    for i in range(150):
        ps.update_with_turn(f"q{i}", f"a{i}")
    assert len(ps.rolling_summary) <= SUMMARY_MAX_CHARS
    # The most recent turns are preserved (the trim drops the oldest third).
    # After 150 turns with RECENT_TAIL_MAX=6, the summary held turns 0..143;
    # trimming kept the most recent 2/3 by char count, so high-numbered turns
    # survive and the oldest ones (0, 1) are gone.
    assert "answered: a140" in ps.rolling_summary
    # Use full-entry match (not substring) — "answered: a0" only matches the
    # turn-0 entry, not "answered: a103" etc.
    assert "answered: a0\n" not in ps.rolling_summary + "\n"
    assert "answered: a1\n" not in ps.rolling_summary + "\n"


def test_empty_messages_skipped():
    ps = ParentSession(session_id="s1")
    ps.update_with_turn("", "")
    assert ps.turn_count == 0
    assert ps.recent_tail == []


def test_to_prompt_section_format():
    ps = ParentSession(session_id="s1")
    ps.update_with_turn("q1", "a1")
    for i in range(RECENT_TAIL_MAX):
        ps.update_with_turn(f"q{i}", f"a{i}")
    section = ps.to_prompt_section()
    assert section is not None
    assert "compacted summary" in section.lower()
    assert "verbatim" in section.lower()


def test_recent_tail_messages_chronological():
    ps = ParentSession(session_id="s1")
    ps.update_with_turn("first", "answer1")
    ps.update_with_turn("second", "answer2")
    msgs = ps.recent_tail_messages()
    # Chronological order: user/assistant for turn 1, then turn 2.
    assert msgs[0] == {"role": "user", "content": "first"}
    assert msgs[1] == {"role": "assistant", "content": "answer1"}
    assert msgs[2] == {"role": "user", "content": "second"}
    assert msgs[3] == {"role": "assistant", "content": "answer2"}


def test_from_store_handles_none():
    """Loading a session that doesn't exist yields a fresh empty one."""
    ps = ParentSession.from_store("s1", None)
    assert ps.is_empty
    assert ps.session_id == "s1"


def test_to_store_round_trip():
    ps = ParentSession(session_id="s1")
    ps.update_with_turn("q1", "a1", tool_summary="shell(ls)")
    ps.update_with_turn("q2", "a2")
    stored = ps.to_store()
    assert stored["turn_count"] == 2
    assert stored["rolling_summary"] is None  # under tail cap, no summary
    assert len(stored["recent_tail"]) == 2

    # Round-trip
    ps2 = ParentSession.from_store("s1", {
        "rolling_summary": stored["rolling_summary"],
        "recent_tail": stored["recent_tail"],
        "turn_count": stored["turn_count"],
    })
    assert ps2.turn_count == 2
    assert len(ps2.recent_tail) == 2
    assert ps2.recent_tail[0]["user"] == "q1"


def test_persistence_via_session_store(tmp_db):
    """The SessionStore saves and loads a ParentSession row correctly."""
    store = SessionStore(tmp_db)
    sid = "test-session-persist"
    ps = ParentSession(session_id=sid)
    for i in range(RECENT_TAIL_MAX + 2):
        ps.update_with_turn(f"q{i}", f"a{i}", tool_summary=f"shell(cmd{i})")

    store.save_parent_session(
        sid,
        rolling_summary=ps.rolling_summary or None,
        recent_tail=ps.recent_tail,
        turn_count=ps.turn_count,
    )

    loaded = store.get_parent_session(sid)
    assert loaded is not None
    assert loaded["turn_count"] == RECENT_TAIL_MAX + 2
    assert loaded["rolling_summary"] is not None
    assert "q0" in loaded["rolling_summary"]
    assert len(loaded["recent_tail"]) == RECENT_TAIL_MAX

    # Reconstruct and verify
    ps2 = ParentSession.from_store(sid, loaded)
    assert ps2.turn_count == RECENT_TAIL_MAX + 2
    assert ps2.rolling_summary == ps.rolling_summary
    assert len(ps2.recent_tail) == RECENT_TAIL_MAX


def test_persistence_survives_reconnect(tmp_db):
    """A fresh SessionStore on the same DB file reads the saved row."""
    sid = "test-session-survive"
    store1 = SessionStore(tmp_db)
    ps = ParentSession(session_id=sid)
    ps.update_with_turn("hello", "world")
    store1.save_parent_session(
        sid,
        rolling_summary=None,
        recent_tail=ps.recent_tail,
        turn_count=ps.turn_count,
    )

    # Simulate a backend restart by opening a new store on the same file.
    store2 = SessionStore(tmp_db)
    loaded = store2.get_parent_session(sid)
    assert loaded is not None
    assert loaded["turn_count"] == 1
    assert loaded["recent_tail"][0]["user"] == "hello"


def test_get_parent_session_returns_none_for_missing(tmp_db):
    store = SessionStore(tmp_db)
    assert store.get_parent_session("does-not-exist") is None

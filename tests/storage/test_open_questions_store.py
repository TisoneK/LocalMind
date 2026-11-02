"""Tests for the durable open-question record (storage layer).

Contract under test:
- record() upserts: the latest outstanding question replaces the previous
  one — one current record per session, nothing archived.
- get() returns the record and clears a too-old one (a stale question can no
  longer be assumed to be what a short reply answers).
- clear() consumes/supersedes: True when a record was removed, False when
  none existed.
- An empty question is refused (a record with no text is a structure bug).
"""

from __future__ import annotations

import time
from unittest import mock

import pytest

from storage.open_questions import OpenQuestionStore


def test_record_upsert_latest_wins(tmp_db):
    store = OpenQuestionStore(tmp_db)
    store.record("s1", "What specific location information are you looking for?", "turn-1")
    second = store.record("s1", "Do you want the report as CSV or JSON?", "turn-2")

    got = store.get("s1")
    assert got is not None
    assert got.question == "Do you want the report as CSV or JSON?"
    assert got.asked_by_turn == "turn-2"
    assert got.session_id == "s1"
    # Sessions are independent — the first session keeps its own record.
    assert store.get("s2") is None
    assert second.created_at > 0


def test_clear_consumes_and_reports(tmp_db):
    store = OpenQuestionStore(tmp_db)
    store.record("s1", "Proceed with the install?")
    assert store.clear("s1") is True
    assert store.get("s1") is None
    # Clearing again is honest: nothing was there.
    assert store.clear("s1") is False


def test_empty_question_refused(tmp_db):
    store = OpenQuestionStore(tmp_db)
    with pytest.raises(ValueError):
        store.record("s1", "   ")


def test_stale_record_is_cleared_on_read(tmp_db):
    store = OpenQuestionStore(tmp_db)
    store.record("s1", "Old question from hours ago")
    # Age the record past the staleness bound without sleeping.
    with mock.patch("storage.open_questions.time.time", return_value=time.time() + 7 * 60 * 60):
        assert store.get("s1") is None
    # The stale read also removed the row.
    assert store.clear("s1") is False

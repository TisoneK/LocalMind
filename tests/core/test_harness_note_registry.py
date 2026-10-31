"""The harness-note marker registry (B-2026-10-31-25 increment, owner-approved
reference study 2026-11-01 §G1): every user-role message the agent loop writes
is a NOTE, never the user speaking. Provenance is carried in band via a
bracketed tag line, and ONE registry (`_HARNESS_NOTE_TAGS`) drives every
consumer — recognition (_is_harness_injected), original-request extraction
(_user_message_text), and the builders (harness_note, _stage_card).

The masquerade bug class this pins: the S009 finding where a loop-injected
demand card was quoted back by the model as "an imagined user instruction",
and the unmarked observation-log injection that a stage card would read as
the user's goal."""

from __future__ import annotations

import pytest

from core.agent.loop import (
    _HARNESS_NOTE_TAGS,
    _HARNESS_USER_PREFIXES,
    _is_harness_injected,
    _stage_card,
    _user_message_text,
    harness_note,
)


@pytest.mark.parametrize("tag", _HARNESS_NOTE_TAGS)
def test_every_registered_tag_is_recognized(tag):
    """Canonical shape: every registered tag opens as a recognized note."""
    note = harness_note(tag, "body text")
    assert note.startswith("\n[")
    assert _is_harness_injected(note)


@pytest.mark.parametrize("tag", _HARNESS_NOTE_TAGS)
def test_every_registered_tag_is_skipped_by_user_message_text(tag):
    """Original-request extraction never returns a harness note — wherever it
    sits in the history and whatever text surrounds the tag line."""
    messages = [
        {"role": "user", "content": "the real task"},
        {"role": "assistant", "content": "working"},
        {"role": "user", "content": f"progress so far\n\n{harness_note(tag, 'body')}\nmore"},
    ]
    assert _user_message_text(messages) == "the real task"


def test_thinker_block_is_recognized_without_leading_newline():
    """Legacy flush-start shape (pre-canonical blocks) still recognized."""
    assert _is_harness_injected("[THINKER ANALYSIS]\nYour analysis of the evidence so far")


def test_unbracketed_recovery_prose_is_still_recognized():
    for prefix in _HARNESS_USER_PREFIXES:
        assert _is_harness_injected(prefix + " …rest")


def test_real_user_messages_are_never_notes():
    assert not _is_harness_injected("[URGENT] the build is broken, look now")
    assert not _is_harness_injected("hi")
    assert not _is_harness_injected("please check [TOOL COMMITMENT] in the docs")
    # A tag embedded mid-sentence does not make a user message a note.
    assert _user_message_text(
        [{"role": "user", "content": "please check [TOOL COMMITMENT] in the docs"}]
    ) == "please check [TOOL COMMITMENT] in the docs"


def test_observation_log_injection_is_marked_and_skipped():
    """The per-iteration context block (observation log + failure hint) must
    carry its tag — before the registry it shipped unmarked and a stage card
    reading the 'Goal:' would quote the observation log as the user's aim."""
    note = harness_note(
        "ITERATION CONTEXT",
        "search (failed)\nIteration 2/6.",
    )
    assert _is_harness_injected(note)
    assert _user_message_text(
        [
            {"role": "user", "content": "find the flaky test"},
            {"role": "user", "content": note},
        ]
    ) == "find the flaky test"


def test_harness_note_and_stage_card_fail_loud_on_unregistered_tags():
    with pytest.raises(ValueError, match="unregistered"):
        harness_note("TOTALLY NEW TAG", "body")
    with pytest.raises(ValueError, match="unregistered"):
        _stage_card("TOTALLY NEW TAG", "act", "decide", [], None)


def test_stage_card_output_keeps_canonical_shape():
    card = _stage_card("STAGE: CONTINUE", "continue", "Wrap up now.", [], None)
    assert card.startswith("\n[STAGE: CONTINUE] Stage: continue.")
    assert _is_harness_injected(card)


def test_registry_has_no_duplicates():
    assert len(_HARNESS_NOTE_TAGS) == len(set(_HARNESS_NOTE_TAGS))

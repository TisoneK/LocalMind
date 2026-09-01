"""Tests for the final-answer PUNT + scaffold-leak detectors (handoff
agent-followthrough-persistence, live bankofai/glm-5.3-flash).

The punt: "Arsenal livescore and news" — one web_research, the score answered
well, then the turn ENDED with "I couldn't pull additional news headlines in
this pass — the Sofascore match page is tracking it live." No tool failure, so
answer_fails_follow_through (mid-turn retry talk) never fired.

The scaffold leak (same before-trace family): the "final answer" was 77 chars
of internal-scaffolding prose — "The synthesis reminder says do NOT call
another tool and present results now." — classified ANSWER, turn over.
"""

from __future__ import annotations

from core.agent.loop import answer_is_internal_scaffold, answer_punts_requested_part

ARSENAL_PUNT = (
    "Aston Villa 0-0 Arsenal, and they sit mid-table. I couldn't pull "
    "additional news headlines in this pass — the live match is the main "
    "story right now, and the Sofascore match page is tracking it live."
)


def test_arsenal_punt_text_is_detected():
    assert answer_punts_requested_part(ARSENAL_PUNT) is True


def test_admission_phrases_fire():
    for phrase in (
        "I couldn't pull the news headlines.",
        "I couldn't get the forecast part.",
        "I couldn't fetch the second page.",
        "I couldn't retrieve the schema.",
        "I wasn't able to get the file contents.",
        "I was unable to retrieve the page.",
    ):
        assert answer_punts_requested_part(phrase) is True, phrase


def test_deferral_phrases_fire():
    for phrase in (
        "I'll cover the rest in this pass later.",
        "You can look it up yourself on the site.",
        "You can check it yourself in the settings.",
        "The stream is tracking it live.",
    ):
        assert answer_punts_requested_part(phrase) is True, phrase


def test_substantive_complete_answer_is_not_a_punt():
    assert answer_punts_requested_part(
        "The score is 0-0 and Arteta named an unchanged squad; Saka is fit again."
    ) is False


def test_ui_pointer_is_not_a_punt():
    # A pointer to OUTPUT the agent already produced is not deferring a
    # requested part to the user.
    assert answer_punts_requested_part(
        "Created groceries.txt — you can check the file for the list."
    ) is False


def test_empty_text_is_not_a_punt():
    assert answer_punts_requested_part("") is False
    assert answer_punts_requested_part(None) is False  # type: ignore[arg-type]


def test_scaffold_leak_lines_fire():
    for phrase in (
        "The synthesis reminder says do NOT call another tool and present results now.",
        "[RECOVERY] retry the failing tool with the next URL",
        "Per the reminder, wrap up now.",
    ):
        assert answer_is_internal_scaffold(phrase) is True, phrase


def test_real_answer_is_not_scaffold():
    assert answer_is_internal_scaffold(
        "24°C, partly cloudy, with a high of 26°C tomorrow."
    ) is False


def test_scaffold_detection_is_case_insensitive():
    assert answer_is_internal_scaffold("The Synthesis Reminder says stop.") is True
    assert answer_punts_requested_part("I COULDN'T PULL the news.") is True


def test_punt_with_no_tools_ran_is_gated_off():
    # zcode review concern 1 (relevant-tool guardrail): the loop wires the
    # punt flag as (_tools_ran AND detector) — with ZERO tools run this turn
    # the flag stays False, so a knowledge-answer "couldn't find X" (no
    # applicable tool) classifies as a plain ANSWER instead of forcing a
    # wasted tool call. This pins that call-site contract through the seam:
    # without the flag set, the same punt text does not recover.
    from core.agent.turn_outcome import Recovery, TurnOutcome, classify_turn_outcome

    a = classify_turn_outcome(
        has_tool_calls=False,
        final_text=ARSENAL_PUNT,
        tools_ran_this_turn=False,
        is_punted_requested_part=False,
    )
    assert a.outcome is TurnOutcome.ANSWER
    assert a.recovery is Recovery.NONE

"""The turn-completion contract (loop-discipline re-architecture, step 1).

Pins the single seam that the ~10 scattered loop-discipline detectors will be
migrated onto: every completed model turn is ACT, ANSWER, or INCOMPLETE, and an
INCOMPLETE turn carries exactly one recovery.
"""

from __future__ import annotations

from core.agent.turn_outcome import (
    Recovery,
    TurnOutcome,
    classify_turn_outcome,
)


def test_tool_calls_are_ACT():
    a = classify_turn_outcome(has_tool_calls=True, final_text="", tools_ran_this_turn=False)
    assert a.outcome is TurnOutcome.ACT
    assert a.recovery is Recovery.NONE


def test_substantive_text_is_ANSWER():
    a = classify_turn_outcome(
        has_tool_calls=False, final_text="The capital of Kenya is Nairobi.",
        tools_ran_this_turn=False,
    )
    assert a.outcome is TurnOutcome.ANSWER
    assert a.recovery is Recovery.NONE


def test_pending_action_narration_is_INCOMPLETE_force_tool():
    # "Deleting the files now:" — a promised action with no tool call.
    a = classify_turn_outcome(
        has_tool_calls=False, final_text="Deleting the two files now:",
        tools_ran_this_turn=False, is_pending_action_narration=True,
    )
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.FORCE_TOOL


def test_pending_action_wins_even_after_tools_ran():
    # A committed pending action must happen even if earlier tools ran.
    a = classify_turn_outcome(
        has_tool_calls=False, final_text="Now deleting them:",
        tools_ran_this_turn=True, is_pending_action_narration=True,
    )
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.FORCE_TOOL


def test_empty_without_evidence_forces_a_tool():
    a = classify_turn_outcome(has_tool_calls=False, final_text="", tools_ran_this_turn=False)
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.FORCE_TOOL


def test_empty_after_tools_synthesizes():
    a = classify_turn_outcome(has_tool_calls=False, final_text="   ", tools_ran_this_turn=True)
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.SYNTHESIZE


def test_post_evidence_narration_synthesizes():
    a = classify_turn_outcome(
        has_tool_calls=False, final_text="Let me now call web_fetch to get the page.",
        tools_ran_this_turn=True, is_post_evidence_narration=True,
    )
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.SYNTHESIZE


def test_post_evidence_narration_ignored_before_any_tool():
    # Before any tool ran, narration-shaped text is a normal first answer, not a
    # synthesize case (mirrors narrates_after_evidence being iteration-gated).
    a = classify_turn_outcome(
        has_tool_calls=False, final_text="Let me check the weather for you.",
        tools_ran_this_turn=False, is_post_evidence_narration=True,
    )
    assert a.outcome is TurnOutcome.ANSWER

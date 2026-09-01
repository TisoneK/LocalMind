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


def test_follow_through_failure_forces_a_tool():
    a = classify_turn_outcome(
        has_tool_calls=False, final_text="Let me try the next source.",
        tools_ran_this_turn=True, is_follow_through_failure=True,
    )
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.FORCE_TOOL


def test_hedge_after_evidence_synthesizes():
    a = classify_turn_outcome(
        has_tool_calls=False, final_text="Would you like me to fetch weather-atlas.com?",
        tools_ran_this_turn=True, is_hedge_after_evidence=True,
    )
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.SYNTHESIZE


def test_force_tool_beats_synthesize_when_both_flags_set():
    # A committed action (FORCE_TOOL) takes precedence over a hedge (SYNTHESIZE).
    a = classify_turn_outcome(
        has_tool_calls=False, final_text="Deleting now; would you like me to continue?",
        tools_ran_this_turn=True, is_pending_action_narration=True, is_hedge_after_evidence=True,
    )
    assert a.recovery is Recovery.FORCE_TOOL


# ── Handoff agent-followthrough-persistence: punt + scaffold flags ──────────

def test_punted_requested_part_is_INCOMPLETE_force_tool():
    # Live shape (bankofai/glm-5.3-flash, "Arsenal livescore and news"):
    # part 1 answered well, part 2 conceded and deferred to the user.
    a = classify_turn_outcome(
        has_tool_calls=False,
        final_text=(
            "Aston Villa 0-0 Arsenal. I couldn't pull additional news headlines "
            "in this pass — the Sofascore match page is tracking it live."
        ),
        tools_ran_this_turn=True, is_punted_requested_part=True,
    )
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.FORCE_TOOL


def test_punt_alone_does_not_need_a_prior_tool_failure():
    # The punt usually follows a SUCCESSFUL partial answer — the old
    # follow-through detector required a tool failure; the punt does not.
    a = classify_turn_outcome(
        has_tool_calls=False,
        final_text="Here's the score. You can check the news yourself.",
        tools_ran_this_turn=True, is_punted_requested_part=True,
    )
    assert a.recovery is Recovery.FORCE_TOOL


def test_substantive_answer_without_punt_stays_ANSWER():
    a = classify_turn_outcome(
        has_tool_calls=False,
        final_text="The score is 0-0 and Arteta has named an unchanged squad.",
        tools_ran_this_turn=True,
    )
    assert a.outcome is TurnOutcome.ANSWER


def test_punt_does_not_override_pending_action():
    a = classify_turn_outcome(
        has_tool_calls=False, final_text="Deleting now; couldn't get the rest.",
        tools_ran_this_turn=True, is_pending_action_narration=True,
        is_punted_requested_part=True,
    )
    assert a.recovery is Recovery.FORCE_TOOL
    assert a.reason == "narrated a pending action without a tool call"


def test_has_tool_calls_beats_punt():
    a = classify_turn_outcome(
        has_tool_calls=True, final_text="I couldn't pull the news.",
        tools_ran_this_turn=False, is_punted_requested_part=True,
    )
    assert a.outcome is TurnOutcome.ACT


def test_scaffold_leak_with_evidence_synthesizes():
    # Live baseline shape (handoff-before trace): 77 chars of pure scaffolding
    # prose ended the turn as ANSWER with zero sub-goals covered.
    a = classify_turn_outcome(
        has_tool_calls=False,
        final_text="The synthesis reminder says do NOT call another tool and present results now.",
        tools_ran_this_turn=True, is_internal_scaffold_text=True,
    )
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.SYNTHESIZE


def test_scaffold_leak_without_evidence_forces_a_tool():
    a = classify_turn_outcome(
        has_tool_calls=False,
        final_text="[RECOVERY] retry the failing tool",
        tools_ran_this_turn=False, is_internal_scaffold_text=True,
    )
    assert a.outcome is TurnOutcome.INCOMPLETE
    assert a.recovery is Recovery.FORCE_TOOL

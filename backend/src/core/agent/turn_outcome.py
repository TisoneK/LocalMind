"""The agent loop's turn-completion contract — one seam, not ten guards.

Loop discipline (§40 quality bar) accreted ~10 overlapping detectors, each added
for one model misbehavior: narration-without-action, empty-after-reasoning,
post-evidence narration, premature "done", … Every one of them is judging the
SAME event: what did this model turn actually do? This module names that once:

    ACT        — the model emitted tool call(s) → execute them.
    ANSWER     — the model produced a grounded final answer → the turn is done.
    INCOMPLETE — it did neither (narrated an intention, went empty, …) → apply
                 exactly ONE recovery, chosen by `Recovery`.

`classify_turn_outcome` is a PURE function: the loop computes the narration
booleans with its existing detectors and passes them in, so this module has no
dependency on (and no import cycle with) the 8.5k-line loop. Migrating a scattered
guard means routing its decision through here and deleting the ad-hoc copy — the
guard count goes DOWN, and each step is covered by tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TurnOutcome(Enum):
    ACT = "act"
    ANSWER = "answer"
    INCOMPLETE = "incomplete"


class Recovery(Enum):
    NONE = "none"
    # The model committed to / promised an action but emitted no tool call, or
    # produced nothing at all with no evidence yet — make it CALL a tool.
    FORCE_TOOL = "force_tool"
    # The model has evidence (tools already ran) but narrated a next step or went
    # empty instead of answering — make it SYNTHESIZE the answer from evidence.
    SYNTHESIZE = "synthesize"


@dataclass(frozen=True)
class TurnAssessment:
    outcome: TurnOutcome
    reason: str
    recovery: Recovery = Recovery.NONE


def classify_turn_outcome(
    *,
    has_tool_calls: bool,
    final_text: str,
    tools_ran_this_turn: bool,
    is_pending_action_narration: bool = False,
    is_post_evidence_narration: bool = False,
) -> TurnAssessment:
    """Classify a completed model turn as ACT / ANSWER / INCOMPLETE.

    Args:
        has_tool_calls: the model emitted one or more tool calls this turn.
        final_text: the answer text the model streamed (may be empty).
        tools_ran_this_turn: at least one tool has executed this turn/run — so
            evidence exists and an empty/narrated turn should SYNTHESIZE rather
            than be forced to act again.
        is_pending_action_narration: the detector says the text narrates a
            committed-but-unexecuted action ("Deleting the files now:").
        is_post_evidence_narration: the detector says the text narrates the NEXT
            action instead of synthesizing already-gathered evidence.
    """
    if has_tool_calls:
        return TurnAssessment(TurnOutcome.ACT, "emitted tool call(s)")

    text = (final_text or "").strip()

    # A committed pending action with no tool call is INCOMPLETE regardless of
    # whether other tools ran — the promised action must actually happen.
    if is_pending_action_narration:
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "narrated a pending action without a tool call",
            Recovery.FORCE_TOOL,
        )

    if not text:
        # Empty: with evidence in hand, synthesize; otherwise nudge it to act.
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "empty response (no tool call, no answer)",
            Recovery.SYNTHESIZE if tools_ran_this_turn else Recovery.FORCE_TOOL,
        )

    if tools_ran_this_turn and is_post_evidence_narration:
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "narrated the next action instead of synthesizing evidence",
            Recovery.SYNTHESIZE,
        )

    return TurnAssessment(TurnOutcome.ANSWER, "produced a final answer")

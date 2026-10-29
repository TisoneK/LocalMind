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
from typing import Optional


class TurnOutcome(Enum):
    ACT = "act"
    ANSWER = "answer"
    INCOMPLETE = "incomplete"
    # The model never finished its write-up, but the evidence it gathered is
    # already in hand: the turn still owes the user that answer and delivers it
    # as gathered, framed with what stopped the write-up. This is the state the
    # provider-death path resolves to — not an error, not a plain ANSWER either:
    # the answer is real, the synthesis is missing, and both are said.
    DEGRADED_ANSWER = "degraded_answer"


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
    is_follow_through_failure: bool = False,
    is_punted_requested_part: bool = False,
    is_internal_scaffold_text: bool = False,
    is_post_evidence_narration: bool = False,
    is_hedge_after_evidence: bool = False,
    tools_withheld: bool = False,
) -> TurnAssessment:
    """Classify a completed model turn as ACT / ANSWER / INCOMPLETE.

    The INCOMPLETE detector-flags collapse to exactly two recoveries:
      * FORCE_TOOL — the model committed to / promised an action but emitted no
        tool call (pending-action narration, or "let me try the next source"
        follow-through after a failure). The action must actually happen.
      * SYNTHESIZE — the model has evidence (tools ran) but narrated the next
        step, hedged ("would you like me to…?"), or went empty instead of
        answering. It must synthesize the answer from that evidence.

    Args:
        has_tool_calls: the model emitted one or more tool calls this turn.
        final_text: the answer text the model streamed (may be empty).
        tools_ran_this_turn: at least one tool has executed this run — evidence
            exists, so an empty/narrated/hedged turn should SYNTHESIZE.
        is_pending_action_narration: text narrates a committed-but-unexecuted
            action ("Deleting the files now:").
        is_follow_through_failure: text says it will try again ("let me try the
            next source") after a tool failed, but emitted no tool call.
        is_punted_requested_part: the final answer concedes an explicitly
            requested part is still unmet ("couldn't pull X in this pass",
            "you can check X yourself") — the requested work must happen, not
            be deferred to the user.
        is_internal_scaffold_text: the "answer" is internal-scaffolding prose
            (references to reminders/directives/instructions) rather than
            content for the user.
        is_post_evidence_narration: text narrates the NEXT action instead of
            synthesizing already-gathered evidence.
        is_hedge_after_evidence: text asks the user to choose/confirm instead of
            answering from the evidence already gathered.
        tools_withheld: the loop deliberately withheld tool schemas on this
            call (the evidence-sufficient answer-only call). Post-evidence
            narration under this mode means the model is asking for a tool it
            was not given (e.g. a genuinely needed second fetch) — FORCE_TOOL
            (restore the schemas), not SYNTHESIZE.
    """
    if has_tool_calls:
        return TurnAssessment(TurnOutcome.ACT, "emitted tool call(s)")

    text = (final_text or "").strip()

    # FORCE_TOOL: a committed/promised action with no tool call must actually
    # happen — this wins even if earlier tools ran (search-then-delete shape).
    if is_pending_action_narration:
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "narrated a pending action without a tool call",
            Recovery.FORCE_TOOL,
        )
    if is_follow_through_failure:
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "said it would retry after a failure but emitted no tool call",
            Recovery.FORCE_TOOL,
        )
    if is_punted_requested_part:
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "final answer concedes a requested part is unmet (punted to the user or a later pass)",
            Recovery.FORCE_TOOL,
        )
    if is_internal_scaffold_text:
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "final text is internal scaffolding, not a user answer",
            Recovery.SYNTHESIZE if tools_ran_this_turn else Recovery.FORCE_TOOL,
        )

    if not text:
        # Empty: with evidence in hand, synthesize; otherwise nudge it to act.
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "empty response (no tool call, no answer)",
            Recovery.SYNTHESIZE if tools_ran_this_turn else Recovery.FORCE_TOOL,
        )

    # SYNTHESIZE: evidence exists but the model narrated/hedged instead of answering.
    # Under the evidence-sufficient answer-only call, tool
    # schemas were deliberately withheld — narration of a further action
    # therefore means the model NEEDS a tool (e.g. a genuinely required
    # second fetch), so the recovery is FORCE_TOOL (schemas restored), the
    # opposite of the normal post-evidence direction.
    if tools_ran_this_turn and is_post_evidence_narration:
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "narrated the next action instead of synthesizing evidence",
            Recovery.FORCE_TOOL if tools_withheld else Recovery.SYNTHESIZE,
        )
    if tools_ran_this_turn and is_hedge_after_evidence:
        return TurnAssessment(
            TurnOutcome.INCOMPLETE,
            "hedged (asked the user to choose) instead of synthesizing evidence",
            Recovery.SYNTHESIZE,
        )

    return TurnAssessment(TurnOutcome.ANSWER, "produced a final answer")


# ── Done-rule: a dead synthesis still owes the user an answer ────────────────
#
# Every other INCOMPLETE detector exists because the model stopped early. The
# 12:45 run (2026-10-27) failed the opposite way: the provider died AFTER the
# evidence was gathered, and the harness threw a completed run away — the
# answer was in hand and never reached the user. That path used to live inline
# in the loop as a rescue. It is an obligation of the turn like any other, so
# it is stated here: synthesis death with usable evidence is DEGRADED_ANSWER —
# deliver what the evidence supports, say what stopped the write-up — and only
# a turn with nothing in hand ends as an error.

_TERMINAL_DEATH_CODES = frozenset({"payment_required", "auth_error"})


@dataclass(frozen=True)
class ProviderDeathRule:
    """What a synthesis death means for this turn's obligation to answer."""

    outcome: TurnOutcome
    preserve_evidence: bool
    terminal: bool
    reason: str


def classify_provider_death(
    *,
    error_code: str = "",
    error_source: str = "",
    retryable: bool = False,
    has_successful_evidence: bool = False,
) -> ProviderDeathRule:
    """Decide whether a provider error during write-up leaves the turn owing an answer.

    Preserving evidence is the rule for a model-provider failure while the turn
    holds successful tool work: the evidence is the answer's substance, and it
    exists whether or not the write-up happened. Two classes of death qualify —
    retryable ones (rate limits: the same turn would very likely succeed later)
    and terminal ones whose code is known and non-retryable (a dead balance, a
    revoked credential: no retry exists). Anything else — a non-provider source,
    an unrecognized non-retryable code, or no successful tool work at all —
    leaves nothing to deliver, and the turn ends honestly instead.
    """
    if error_source != "model_provider":
        return ProviderDeathRule(
            TurnOutcome.INCOMPLETE, False, False, "not a model-provider failure"
        )
    if not has_successful_evidence:
        return ProviderDeathRule(
            TurnOutcome.INCOMPLETE, False, False, "no successful tool work in hand to deliver"
        )
    terminal = not retryable and error_code in _TERMINAL_DEATH_CODES
    if retryable:
        return ProviderDeathRule(
            TurnOutcome.DEGRADED_ANSWER,
            True,
            False,
            "provider died during write-up; evidence in hand, failure retryable",
        )
    if terminal:
        return ProviderDeathRule(
            TurnOutcome.DEGRADED_ANSWER,
            True,
            True,
            f"provider died during write-up; evidence in hand, {error_code} is terminal",
        )
    return ProviderDeathRule(
        TurnOutcome.INCOMPLETE,
        False,
        False,
        f"provider died with {error_code or 'an unclassified error'}; nothing deliverable",
    )


def provider_death_answer(
    *,
    rule: ProviderDeathRule,
    provider: str = "",
    error_code: str = "",
    extracted: str = "",
    evidence_blocks: Optional[list[str]] = None,
    tool_count: int = 0,
) -> str:
    """The delivered answer for a DEGRADED_ANSWER turn.

    The evidence is the substance; the death note is the provenance. Wording is
    chosen by what is actually in hand — an extracted answer, raw evidence
    blocks, or nothing — and a terminal death is named as such, because
    \"try again\" is known-dead advice when the balance is zero or the
    credential was revoked.
    """
    named = provider or "The model provider"
    if extracted:
        if not rule.terminal:
            return extracted
        return (
            f"⚠️ {named} returned `{error_code}` while I was writing the answer up, "
            "so here is what the evidence already supports, as gathered:\n\n" + extracted
        )

    blocks = [b for b in (evidence_blocks or []) if b]
    if rule.terminal:
        death_note = (
            f"{provider or 'the model provider'} returned `{error_code}` (not retryable) "
            "on my final write-up"
        )
    else:
        death_note = "the model provider was rate-limited on my final synthesis"

    if blocks:
        return (
            f"Here's what I found ({death_note}, so this is the raw evidence):\n\n"
            + "\n\n---\n\n".join(blocks[:3])
        )
    if tool_count > 0:
        if rule.terminal:
            return (
                "I gathered the information you asked for, but "
                f"{death_note}; this turn can't continue."
            )
        return (
            "I gathered the information you asked for, but the model provider "
            "was rate-limited. Please try again in a moment and I'll give you a "
            "clean summary."
        )
    if rule.terminal:
        return (
            f"⚠️ {named} returned `{error_code}` (not retryable); this turn can't continue."
        )
    return "The model provider rate-limited my request. Please try again in a moment."


# ── Done-rule: nothing is owed on a call that never answered ─────────────────
#
# A turn closes only when nothing is owed. A tool call that fails mid-flight
# must still be answered in the transcript — an assistant tool_calls message
# with no matching tool result is a broken request (the provider rejects it) and
# a broken record (later turns cannot tell what happened). The result is not
# invented either: when the outcome is genuinely unknown, the placeholder says
# UNKNOWN and tells the model to check the state before touching it again.

SIDE_EFFECT_FREE_TOOLS = frozenset(
    {
        "file_task",
        "dir_explorer",
        "web_search",
        "web_fetch",
        "sysinfo",
        "observe",
        "calculator",
        "csv",
        "json",
        "sql",
        "describe_tool",
        "search_tool_results",
        "todo_write",
    }
)


@dataclass(frozen=True)
class UnansweredCall:
    """The recorded result for a call that produced no definite outcome."""

    tool_name: str
    unknown: bool
    retry_safe: bool
    text: str


def classify_unanswered_call(
    *,
    tool_name: str,
    error: Optional[BaseException] = None,
    timed_out: bool = False,
) -> UnansweredCall:
    """Build the placeholder result for a call whose outcome nobody knows.

    Two facts decide it: whether the failure can only have happened before the
    tool body did anything (an argument/shape error), and whether the tool can
    leave a durable effect. Anything else — a timeout, an abandoned call, a
    crash mid-run — is UNKNOWN, and re-running it blind is only safe when the
    tool cannot leave an effect behind.
    """
    side_effect_free = tool_name in SIDE_EFFECT_FREE_TOOLS
    unknown = timed_out or not isinstance(error, (ValueError, KeyError, TypeError))
    if not unknown:
        # A parse/shape error is raised before the tool body does anything.
        return UnansweredCall(
            tool_name=tool_name,
            unknown=False,
            retry_safe=True,
            text=f"[Tool '{tool_name}' failed: {error}]",
        )

    what = (
        "timed out and was abandoned"
        if timed_out
        else "was abandoned mid-run"
        if error is None
        else f"was abandoned mid-run ({error})"
    )
    if side_effect_free:
        guidance = (
            "This tool has no durable side effect, so calling it again is safe."
        )
    else:
        guidance = (
            "Its effect is unknown, so do NOT run it again blindly: inspect the "
            "current state first (the file, process or listing it would have "
            "changed), then decide."
        )
    return UnansweredCall(
        tool_name=tool_name,
        unknown=True,
        retry_safe=side_effect_free,
        text=(
            f"[Tool '{tool_name}' — OUTCOME UNKNOWN: it {what}. "
            f"{guidance}]"
        ),
    )


def unanswered_call_text(tool_name: str, *, reason: str = "") -> str:
    """The placeholder text for a call the turn moved past without a result."""
    call = classify_unanswered_call(tool_name=tool_name, timed_out=True)
    if not reason:
        return call.text
    return call.text[:-1] + f" — {reason}]"


def pair_unanswered_tool_calls(
    messages: list[dict], *, reason: str = ""
) -> list[str]:
    """Give every unpaired assistant tool call a recorded result. Mutates in place.

    Returns the tool_call ids it repaired, so the caller can put the repair on
    the audit record instead of letting it happen invisibly. Cheap enough to run
    at every iteration head: it walks the message list once and appends at most
    one message per dangling call.
    """
    pending: dict[str, str] = {}  # tool_call id -> tool name, in order
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        calls = msg.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if isinstance(call, dict) and isinstance(call.get("id"), str):
                    name = ""
                    fn = call.get("function")
                    if isinstance(fn, dict):
                        name = str(fn.get("name") or "")
                    pending[call["id"]] = name
        elif msg.get("role") == "tool":
            pending.pop(str(msg.get("tool_call_id") or ""), None)
    repaired: list[str] = []
    for call_id, name in pending.items():
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": unanswered_call_text(name or "tool", reason=reason),
            }
        )
        repaired.append(call_id)
    return repaired

"""
Failure memory — the loop's "Remember" stage.

The gap being closed: nothing wrote what-failed-and-why at loop
end; the earlier learning decision was never wired into the runtime (memory is
retrieval-centric). This module closes that gap:

  - `classify_failure(trace)` — deterministic what-failed-and-why from
    the AgentTrace: iteration_limit (hit the cap), empty_response (the
    model returned nothing), criteria_unmet (the acceptance gate was NOT
    passed at the end), tool_failure (a tool failed this run). Empty
    string when the run is not a failure — a successful run is NOT
    remembered (remembering success would flood the table with noise).
  - `build_failure_summary(trace)` — a compact human-readable line:
    which failure, how many iterations, what tools failed.
  - `format_recall_hint(rows)` — the read-back shape injected into the
    next similar turn's context (alongside memory facts): "past similar
    failures to avoid".

Wire-in (core/agent_runtime.py):
  - WRITE: after the parent agent loop converges, scan obs for the loop's
    termination event and record via SessionStore.record_failure.
  - READ: before building the loop prompt, SessionStore.recall_failures
    returns matching past failures; format_recall_hint appends them to
    memory_facts so the model sees them.

Deterministic, no LLM calls — pure + unit-testable (flaw-log friendly).
"""

from __future__ import annotations


def classify_failure(trace: object) -> str:
    """What kind of failure ended this run? Empty string = not a failure.

    Priority order (a capped loop that also failed a tool reports the
    cap — it's the more actionable signal):
      1. iteration_limit — trace.hit_limit (hit the iteration/wall cap)
      2. criteria_unmet — success_criteria existed but gate_passed is
         explicitly False at the end (the acceptance contract was not
         verified)
      3. tool_failure — at least one tool step failed this run

    A tool_failure is only classified as
    a failure when the run did NOT produce a final answer. If the model
    recovered from a failed tool (tried a different URL, retried, etc.)
    and produced a real answer, the run is a SUCCESS — emitting
    agent_loop_failure would show "Agent loop terminated: tool_failure"
    to the user even though they got their answer. Check final_response
    before classifying tool_failure.
    """
    if getattr(trace, "hit_limit", False):
        # A capped run whose forced synthesis delivered a real
        # answer is a rescued turn, not a failure — same logic as the
        # tool_failure guard below. The old order classified
        # the cap BEFORE the rescue ran, so "Agent loop failed" showed above
        # a complete answer (the "find my CV" transcript).
        final_response = (getattr(trace, "final_response", "") or "").strip()
        if len(final_response) >= 20:
            return ""
        # Report WHICH budget ended the loop — the wall-clock
        # break used to be classified as "iteration_limit". The remedies
        # differ (time cap: smaller turns / faster provider; step cap:
        # continue or raise the step budget), and the fallback
        # contract requires the stated cause to be the real one.
        kind = (getattr(trace, "limit_kind", "") or "").strip()
        if kind == "wall_clock":
            return "wall_clock_limit"
        if kind == "repetition":
            return "repetition_loop"
        return "iteration_limit"
    if getattr(trace, "empty_response", False):
        return "empty_response"
    criteria = getattr(trace, "success_criteria", None) or []
    gate_passed = getattr(trace, "gate_passed", None)
    if criteria and gate_passed is False:
        return "criteria_unmet"
    # Only classify as tool_failure if the run did NOT
    # produce a final answer. A recovered tool failure (model tried a
    # different approach and succeeded) is a success, not a failure.
    final_response = (getattr(trace, "final_response", "") or "").strip()
    if final_response and len(final_response) >= 20:
        return ""  # the model produced a real answer — not a failure
    if any(getattr(step, "tool_failed", False) for step in getattr(trace, "steps", [])):
        return "tool_failure"
    return ""


def build_failure_summary(trace: object) -> str:
    """One-line what-failed-and-why from the trace (deterministic)."""
    failure_type = classify_failure(trace)
    iterations = getattr(trace, "iterations_used", 0) or len(getattr(trace, "steps", []))
    if failure_type == "iteration_limit":
        return (
            f"Hit the iteration limit after {iterations} iteration(s); "
            f"the run was cut off before the objective was verified."
        )
    if failure_type == "wall_clock_limit":
        return (
            f"Hit the wall-clock cap after {iterations} iteration(s); "
            f"the turn ran out of time before the objective was verified."
        )
    if failure_type == "repetition_loop":
        return (
            f"Repeated the same tool call with the same arguments and result "
            f"{iterations} time(s); the run was stopped as a no-progress loop."
        )
    if failure_type == "empty_response":
        return "The model returned an empty response for this step; the turn ended with no usable synthesis."
    if failure_type == "criteria_unmet":
        unmet = [
            c
            for c, passed, _ in getattr(trace, "criteria_results", [])
            if not passed
        ]
        if unmet:
            return f"Acceptance criteria not verified at end: {', '.join(unmet[:3])}."
        return "Acceptance criteria were not verified when the run ended."
    if failure_type == "tool_failure":
        failed = [
            f"{step.tool_name}({step.tool_input or ''})"
            for step in getattr(trace, "steps", [])
            if getattr(step, "tool_failed", False)
        ]
        if failed:
            return f"Tool failure(s): {', '.join(failed[:3])}."
        return "A tool failed during the run."
    return ""


def format_recall_hint(rows: list[dict], max_entries: int = 2) -> str:
    """Format recalled past failures into a context hint for the next
    similar turn. Empty rows → empty string (no hint injected)."""
    if not rows:
        return ""
    lines = ["Past similar failures to avoid (from failure memory):"]
    for row in rows[:max_entries]:
        ftype = row.get("failure_type", "")
        summary = (row.get("summary") or "").strip()
        if summary:
            lines.append(f"  - [{ftype}] {summary}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)

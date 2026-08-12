"""
ADR-18 P2 — Failure memory (the "Remember" stage, Session 175).

Per ADR-18 decision point 5: nothing wrote what-failed-and-why at loop
end; ADR-7's learning step was never wired into the runtime (memory is
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

Wire-in (engine/_pipeline.py):
  - WRITE: after the agent loop converges, scan obs for the loop's
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
    """
    if getattr(trace, "hit_limit", False):
        return "iteration_limit"
    if getattr(trace, "empty_response", False):
        return "empty_response"
    criteria = getattr(trace, "success_criteria", None) or []
    gate_passed = getattr(trace, "gate_passed", None)
    if criteria and gate_passed is False:
        return "criteria_unmet"
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

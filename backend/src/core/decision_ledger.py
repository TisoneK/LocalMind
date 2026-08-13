"""
ADR-19 P2 — Cross-session decision ledger (the "never compress this away"
store, Session 178).

Design.md §6 names this slice: a durable store of "decisions that must
never be compressed away." The user's lossy-compression example — "user
wants PostgreSQL, rejected MongoDB, wants SQLite locally, production
uses PostgreSQL" collapsing to "Database: PostgreSQL" — is exactly what
this ledger prevents from being lost FOREVER (not just for one turn).

P0 already preserves decision lines for the current turn (the summarizer's
[Preserved decisions] block). P2 makes them durable:

  - WRITE: the task-aware summarizer emits the preserved lines; the engine
    passes them to `record_decisions_from_compression()` which persists
    each line to the decision_ledger table (best-effort, deduped, pruned).
    A line survives even after the conversation that produced it is
    compressed away or the session is deleted.
  - READ: before building the agent loop's context, the engine recalls
    recent ledger decisions (optionally per task type) and appends
    `format_ledger_hint()` to memory_facts, so a NEW session — or a later
    turn in this one — still honors decisions made earlier.

Deterministic, no LLM calls — pure formatting + a thin DB write adapter
(flaw-log friendly: unit-tested without a live model).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from core.context_policy import ContextPolicy
from core.summarizer import _preserved_decision_lines

if TYPE_CHECKING:
    from storage.db import SessionStore


def extract_decision_lines(
    excerpt: str,
    policy: Optional[ContextPolicy] = None,
) -> list[str]:
    """Extract decision-relevant lines from an excerpt using the policy's
    keep_markers (reuses the summarizer's preservation logic so the write
    path matches exactly what the compression turn preserved). Empty
    policy → no markers → no lines."""
    if policy is None or policy.task_type == "default" or not policy.keep_markers:
        return []
    return _preserved_decision_lines(excerpt, policy)


def record_decisions_from_compression(
    store: "SessionStore",
    session_id: str,
    decision_lines: list[str],
    task_type: str = "",
    max_lines: int = 6,
) -> int:
    """Persist preserved decision lines into the ledger. Best-effort per
    line (a ledger write must never break the turn). Returns the number
    of lines actually recorded."""
    if not decision_lines:
        return 0
    recorded = 0
    for line in decision_lines[:max_lines]:
        try:
            store.record_decision(session_id=session_id, decision=line, task_type=task_type)
            recorded += 1
        except Exception:  # pragma: no cover — defensive
            continue
    return recorded


def format_ledger_hint(rows: list[dict], max_entries: int = 4) -> str:
    """Format recalled ledger decisions into a context hint for the next
    turn. Empty rows → empty string (no hint injected)."""
    if not rows:
        return ""
    lines = ["Past decisions to honor (from the decision ledger):"]
    for row in rows[:max_entries]:
        decision = (row.get("decision") or "").strip()
        if not decision:
            continue
        task = (row.get("task_type") or "").strip()
        prefix = f"[{task}] " if task else ""
        lines.append(f"  - {prefix}{decision}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)

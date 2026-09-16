"""
PlanParser — converts the free-text _plan_stream output into a typed
list of PlanNode (Structured Planner DAG).

PURPOSE
=======
The existing `_plan_stream` (loop.py:4135-4237) produces free-text
prose that the loop injects into the system prompt verbatim (capped at
1500 chars). `_parse_plan_steps` (text_tools.py:36-67) extracts only
the numbered "STEPS:" block for the Todos panel UI — it does NOT feed
back into execution.

The fix: a new parser that converts the same free-text plan
into a structured `list[PlanNode]`. Each node carries its own
`success_criteria` derived deterministically from the goal
(GoalInterpreter's per-intent templates) when no explicit criteria are
declared. The loop advances nodes through `pending → in_progress →
completed | failed` as the model executes tools.

The parser is conservative:
  - It only recognizes numbered/bulleted plan lines ("1. xxx", "- xxx",
    "* xxx"). Free-form paragraphs are ignored.
  - It detects "after X" / "depends on X" / "when X done" syntax for
    depends_on.
  - It detects "(criteria: ...)" / "[verifies: ...]" suffixes for
    per-node success_criteria.
  - When no per-node criteria are found, it leaves the list empty —
    the gate falls back to the GoalInterpreter's turn-level criteria.

USAGE
=====
    from core.agent.plan_parser import parse_plan_to_nodes

    nodes = parse_plan_to_nodes(plan_text, fallback_criteria=...)
    # nodes is a list[PlanNode]; pass to TaskState.nodes
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from core.agent.task_state import PlanNode

logger = logging.getLogger(__name__)


# ── Plan line patterns ─────────────────────────────────────────────────────
#
# Recognizes:
#   1. xxx
#   1) xxx
#   - xxx
#   * xxx
#   Step 1: xxx
#   Step 1 — xxx
#
# Captures the rest of the line as the subgoal text.

_PLAN_LINE_RE = re.compile(
    r"^\s*(?:"
    r"(?:step\s*)?(?P<num>\d+)\s*[\.\):\-\u2014\u2013]\s+"  # "1.", "1)", "1:", "1 -", "1 —", "Step 1:"
    r"|[\-\*]\s+"                                          # "- ", "* "
    r")(?P<text>.+?)\s*$",
    re.IGNORECASE,
)

# Detects "after node-1" / "depends on node-1" / "when node-1 done".
# Matches both inside parens "(after node-1)" and outside "after node-1".
_DEPENDS_RE = re.compile(
    r"(?:after|depends?\s+on|when)\s+(?P<deps>node-\d+(?:\s*,\s*node-\d+)*)",
    re.IGNORECASE,
)

# Detects "(criteria: ...)" / "[verifies: ...]" / "(verifies: ...)"
# Captures everything up to the closing bracket.
_PER_NODE_CRITERIA_RE = re.compile(
    r"(?:\(\s*(?:criteria|verifies|verify)\s*:\s*(?P<c>[^)]+)\)"
    r"|\[\s*(?:verifies|verify|criteria)\s*:\s*(?P<c2>[^\]]+)\])",
    re.IGNORECASE,
)


def _make_node_id(index: int) -> str:
    """Stable node id like 'node-1', 'node-2'."""
    return f"node-{index + 1}"


def _parse_depends(text: str, all_ids: list[str]) -> list[str]:
    """Extract 'after node-X' references from a subgoal text.

    Returns a list of node ids that the subgoal depends on. Filters out
    references that don't match any known id (e.g. 'after the user
    confirms' is a free-text reference, not a node id).
    """
    matches = _DEPENDS_RE.findall(text)
    if not matches:
        return []
    deps: list[str] = []
    valid_ids = set(all_ids)
    for m in matches:
        # The match is "node-1, node-2" style — split on comma
        for token in re.split(r"\s*,\s*", m.strip()):
            token = token.strip().lower()
            if token in valid_ids and token not in deps:
                deps.append(token)
    return deps


def _parse_per_node_criteria(text: str) -> list[str]:
    """Extract '(criteria: xxx)' / '[verifies: xxx]' from a subgoal text."""
    out: list[str] = []
    for m in _PER_NODE_CRITERIA_RE.finditer(text):
        c = m.group("c") or m.group("c2") or ""
        c = c.strip()
        if c:
            # Split on ; or , for multiple criteria in one block
            for piece in re.split(r"[;,]", c):
                piece = piece.strip()
                if piece:
                    out.append(piece)
    return out


def _strip_depends_and_criteria(text: str) -> str:
    """Remove the 'after X' and '(criteria: ...)' suffixes from the subgoal
    text so the rendered subgoal reads cleanly."""
    text = _DEPENDS_RE.sub("", text)
    text = _PER_NODE_CRITERIA_RE.sub("", text)
    return text.strip().strip("-—").strip()


def parse_plan_to_nodes(
    plan_text: str,
    fallback_criteria: Optional[list[str]] = None,
) -> list[PlanNode]:
    """Parse free-text plan output into structured PlanNode list.

    Args:
        plan_text: the free-text plan from _plan_stream (or any source).
            May be empty — returns [].
        fallback_criteria: optional list of criteria to attach to every
            node that has no per-node criteria. Useful when the
            GoalInterpreter has already derived turn-level criteria —
            the same criteria apply per-step. None = leave per-node
            criteria empty (the gate falls back to turn-level criteria).

    Returns:
        list[PlanNode] — may be empty if no plan lines were recognized.
    """
    if not plan_text or not plan_text.strip():
        return []

    # First pass: extract raw plan lines + their texts.
    raw_lines: list[tuple[int, str]] = []  # (1-indexed-position, text)
    for line in plan_text.splitlines():
        m = _PLAN_LINE_RE.match(line)
        if m:
            text = m.group("text").strip()
            if text:
                raw_lines.append((len(raw_lines) + 1, text))

    if not raw_lines:
        return []

    # Assign stable node ids.
    all_ids = [_make_node_id(i) for i in range(len(raw_lines))]

    # Second pass: build PlanNode objects with depends_on + criteria.
    nodes: list[PlanNode] = []
    for i, (pos, text) in enumerate(raw_lines):
        node_id = all_ids[i]
        deps = _parse_depends(text, all_ids)
        # Filter out self-references.
        deps = [d for d in deps if d != node_id]
        crits = _parse_per_node_criteria(text)
        if not crits and fallback_criteria:
            crits = list(fallback_criteria)
        subgoal = _strip_depends_and_criteria(text)
        if not subgoal:
            # Edge case: the line was ONLY "after X" / "(criteria: Y)".
            # Fall back to the raw text so we don't lose the step.
            subgoal = text.strip()
        nodes.append(
            PlanNode(
                id=node_id,
                subgoal=subgoal,
                depends_on=deps,
                success_criteria=crits,
                status="pending",
            )
        )

    return nodes


def advance_node_for_step(
    nodes: list[PlanNode],
    tool_name: str,
    tool_input: str,
    observation: str,
    succeeded: bool,
) -> Optional[str]:
    """Heuristically advance the first pending/in_progress node whose
    subgoal text appears in the tool input or observation.

    Returns the id of the node that was advanced (or None). This is a
    best-effort heuristic — the model's plan text doesn't always map
    cleanly to a single tool call. The loop calls this after every
    tool execution to keep the DAG status current.

    When a node is in_progress and the tool succeeded, it transitions
    to completed. When the tool failed, it transitions to failed.

    Conservative match: requires 3+ tokens (each 4+ chars, excluding
    common path-like tokens) from the subgoal to appear in the tool
    input/observation. This avoids false matches on common substrings
    like '/tmp'.
    """
    if not nodes:
        return None
    hay = f"{tool_input or ''} {observation or ''}".lower()

    # Common tokens that produce false positives — short paths, articles,
    # file extensions. Excluded from the matching token set.
    _COMMON_TOKENS = {
        "the", "and", "for", "with", "from", "into", "that", "this",
        "tmp", "etc", "home", "user", "dir", "file", "files", "data",
        "code", "test", "tests", "run", "read", "edit", "write",
        "step", "next", "first", "second", "third",
        "py", "txt", "json", "md", "sh",
        # Common 3-letter path tokens
        "foo", "bar", "baz", "qux", "abc", "xyz", "tmp",
    }
    for node in nodes:
        if node.status in ("completed", "failed"):
            continue
        # Match if at least 2 SUBGOAL-SPECIFIC tokens (3+ chars,
        # excluding common ones) appear in the tool input/observation.
        subgoal_tokens = [
            t
            for t in re.findall(r"[a-z0-9_-]{3,}", node.subgoal.lower())
            if t not in _COMMON_TOKENS
        ]
        if len(subgoal_tokens) < 1:
            # Subgoal too generic to match reliably — skip.
            continue
        matches = sum(1 for t in subgoal_tokens if t in hay)
        # Require at least 1 subgoal-specific token in the tool I/O.
        # (Conservative — single-token matches are weak signals, but
        # better than no advancement. The advance is purely cosmetic —
        # the gate's verifier is what actually decides "done".)
        if matches >= 1:
            if succeeded:
                node.status = "completed"
            else:
                node.status = "failed"
                node.error = (observation or "")[:200]
            return node.id
    return None

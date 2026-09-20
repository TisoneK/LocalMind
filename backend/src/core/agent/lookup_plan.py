"""Display-only plan rows derived from what the request itself says.

The goal planner (`goal_interpreter`) lists only checkable deliverables ("file exists at …"),
because those become the acceptance gate's criteria. A request also says what to DO next ("then
add tea to it", "and show me what's in it") and sometimes spells out its own sequence ("run ls,
then cat nope.txt and tell me"). Those become extra plan rows here. Everything is display only:
never a success criterion, so it cannot gate or block completion.

There is deliberately no canned plan for an open-ended request such as a web lookup. A fixed
"search, read, answer" skeleton made every lookup look the same and could not follow what really
happened; those tasks are the model's own (todo_write) or appear as the agent acts.
"""

from __future__ import annotations

import re

# ── follow-on steps for file work ────────────────────────────────────────────────────────
#
# The goal planner lists only checkable deliverables ("file exists at …"), because those become
# the acceptance gate's criteria. A request also says what to DO next — "then add tea to it",
# "and show me what's in it" — and a plan that leaves those out looks like the agent ignored
# half the request. These are shown as extra plan rows, after the goals. They are display only:
# never success criteria, so they cannot gate or block completion.

_EDIT_FOLLOWUP_RE = re.compile(
    r"\b(?:add|append|insert|put)\s+(?P<what>[^,.;]{1,40}?)\s+"
    r"(?:to|onto|into)\s+(?:the\s+end\s+of\s+)?(?:it|the\s+file|that\s+file|them)\b",
    re.IGNORECASE,
)
_SHOW_FOLLOWUP_RE = re.compile(
    r"\b(?:show|display|print)\s+me\b|\bread\s+(?:it\s+)?back\b|\bwhat'?s\s+in\s+it\b|"
    r"\blist\s+the\s+(?:folder|directory|files)\b",
    re.IGNORECASE,
)


def derive_followup_steps(message: str, goal_items: list[str]) -> list[str]:
    """Display-only steps for the follow-on actions a file request asks for."""
    if not goal_items or not message:
        return []
    steps: list[str] = []
    edit = _EDIT_FOLLOWUP_RE.search(message)
    if edit:
        steps.append(f"Add {edit.group('what').strip()} to the file")
    if _SHOW_FOLLOWUP_RE.search(message):
        steps.append("Show you the result")
    return steps


# ── a request that spells out its own sequence ──────────────────────────────────────────
#
# "run ls, then try to cat nope.txt and tell me what happened" already IS a plan, in the
# user's own words. When a request is sequenced with an explicit word (then / after that /
# next / finally) and nothing else supplied a plan, show those steps. Faithful by
# construction: every label comes from the request, nothing is guessed.

_SEQUENCE_SPLIT_RE = re.compile(
    r"\s*(?:[,;]\s*)?(?:\band\s+)?\bthen\b\s*|\s*[,;]?\s*\bafter\s+that\b\s*|"
    r"\s*[,;]\s*\b(?:next|finally)\b\s*|\s*;\s*",
    re.IGNORECASE,
)
_REPORT_TAIL_RE = re.compile(
    r"\s+and\s+(?P<verb>tell|show|let|report|summari[sz]e|explain)\s+(?P<rest>me\b.*|.*)$",
    re.IGNORECASE,
)
_LEADING_FILLER_RE = re.compile(
    r"^(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|i\s+want\s+you\s+to\s+|and\s+)+",
    re.IGNORECASE,
)


def _tidy_step(text: str) -> str:
    text = _LEADING_FILLER_RE.sub("", text.strip(" .,!?;:"))
    text = re.sub(r"\bme\b", "you", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmy\b", "your", text, flags=re.IGNORECASE)
    return (text[:1].upper() + text[1:])[:70]


def derive_sequence_plan(message: str) -> list[str]:
    """The steps a request itself spells out ("A, then B and tell me C"), else an empty list."""
    text = (message or "").strip()
    if len(text.split()) < 5:
        return []
    clauses = [c for c in _SEQUENCE_SPLIT_RE.split(text) if c and c.strip()]
    if len(clauses) < 2:
        return []
    steps: list[str] = []
    for clause in clauses:
        tail = _REPORT_TAIL_RE.search(clause)
        if tail:
            head = clause[: tail.start()]
            if head.strip():
                steps.append(_tidy_step(head))
            steps.append(_tidy_step(f"{tail.group('verb')} {tail.group('rest')}"))
        else:
            steps.append(_tidy_step(clause))
    steps = [s for s in steps if len(s) >= 3]
    return steps[:5] if len(steps) >= 2 else []

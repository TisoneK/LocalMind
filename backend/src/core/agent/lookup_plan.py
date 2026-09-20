"""The plan for a request that needs live information, known before the first tool runs.

The warm-kernel runtime skips the model's planning stage, so a turn only gets an upfront
checklist when a deterministic step derives one (see `goal_interpreter`, which covers file
work). A plain lookup — "what's the weather in Nairobi", "latest arsenal score" — had none:
the task panel grew one task per tool as each started, and showed "1/1 done" while the agent
was still working.

A lookup always has the same shape: search, read the best source, answer. This module
recognises the request and supplies those three steps as a DISPLAY plan. It is not a success
criterion, so it never gates completion; a request it does not recognise simply behaves as it
did before (per-tool tasks).
"""

from __future__ import annotations

import re

LOOKUP_STEPS: tuple[str, ...] = ("Search the web", "Check the sources", "Answer from what I found")

# Words that say the answer changes over time or lives outside the machine.
_LIVE_INFO_RE = re.compile(
    r"\b(?:"
    r"weather|forecast|temperature|humidity|rain(?:ing)?|"
    r"news|headlines?|"
    r"stock|shares?\s+price|exchange\s+rate|price\s+of|prices?\s+(?:for|of)|how\s+much\s+(?:is|are|does|do)\b.{0,40}\bcost|"
    r"scores?|fixtures?|standings|league\s+table|results?\s+(?:of|for)|who\s+won|"
    r"latest|newest|breaking|trending|right\s+now|rn|currently|"
    r"opening\s+hours|open\s+(?:now|today)|traffic|"
    r"release\s+date|when\s+(?:is|does|did|will)\b.{0,40}\b(?:release|start|open|play|launch)|"
    r"search\s+(?:the\s+)?(?:web|internet|online)|look\s*up|google|"
    r"what(?:'s| is)\s+happening"
    r")\b",
    re.IGNORECASE,
)

# Work on the user's own machine or files is not a web lookup, even when it says "latest".
_LOCAL_RE = re.compile(
    r"\b(?:file|files|folder|directory|disk|drive|ram|memory|cpu|my\s+(?:computer|machine|laptop|pc)|"
    r"workspace|repo|repository|code|script|log|logs|commit|branch)\b",
    re.IGNORECASE,
)


def request_needs_live_lookup(message: str) -> bool:
    """True for a request that needs current information from the web."""
    text = (message or "").strip()
    if len(text.split()) < 3:
        return False
    if _LOCAL_RE.search(text):
        return False
    # Questions the loop answers from its own injected context (the clock, the System line)
    # are not lookups: the acceptance gate already accepts them without a tool.
    from core.agent.injected_context_gate import (
        request_matches_grounded_class,
        request_matches_system_fact_class,
    )

    if request_matches_grounded_class(text) or request_matches_system_fact_class(text):
        return False
    return bool(_LIVE_INFO_RE.search(text))


# Which plan step a finished tool completes. Search finishes step 0; opening a page finishes
# step 1 (checking the sources). The last step is the answer, which the end of the turn ticks.
_STEP_FOR_TOOL = {"web_search": 0, "web_fetch": 1, "browse": 1}


def lookup_step_for_tool(tool_name: str) -> int | None:
    """The lookup-plan step a successfully finished tool completes, or None."""
    return _STEP_FOR_TOOL.get(tool_name)


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    host = urlparse(url if "://" in url else f"https://{url}").hostname or ""
    return host[4:] if host.startswith("www.") else host


def lookup_step_label(tool_name: str, tool_input: str) -> tuple[int, str] | None:
    """A specific label for the lookup step a tool is starting, or None.

    The plan starts generic ("Search the web") because nothing is known yet. The moment the
    agent commits to a query or a page, the step can say what it is actually doing: what is
    being searched, which site is being read. Same step, same id — the text just gets truer.
    """
    idx = lookup_step_for_tool(tool_name)
    if idx is None:
        return None
    detail = (tool_input or "").strip().splitlines()[0].strip() if (tool_input or "").strip() else ""
    if not detail:
        return None
    if idx == 0:
        return 0, f"Search the web for {detail[:60]}"
    host = _host_of(detail)
    return (1, f"Read {host}") if host else None


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


def derive_lookup_plan(message: str) -> list[str]:
    """The three lookup steps for a live-information request, else an empty list."""
    return list(LOOKUP_STEPS) if request_needs_live_lookup(message) else []

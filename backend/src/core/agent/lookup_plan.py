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


def derive_lookup_plan(message: str) -> list[str]:
    """The three lookup steps for a live-information request, else an empty list."""
    return list(LOOKUP_STEPS) if request_needs_live_lookup(message) else []

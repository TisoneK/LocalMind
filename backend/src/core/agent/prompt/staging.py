"""Later-call input selection — what a model call mid-turn still needs.

A call that already holds a tool result does not need the guidance for
choosing its FIRST tool (the style examples, the tool-list one-liners, the
selection hints); every RULE stays. An answer-only call (no tools offered)
also drops the on-demand-loading paragraph. The selection is by section
NAME — the head-string find this replaces could silently no-op when a
section moved; a name cut cannot drift.

Two selectors live here:

- staged_static_content cuts a REGISTRY-built prompt by section name —
  the selector the loop uses for the parent prompt. A cut of sections a
  prompt never had is a no-op.
- staged_system_prompt is the legacy head-string cutter for prompts
  built as plain strings (the chat path). It finds the same section
  heads the parent builder interpolates, so the boundaries cannot drift
  from the text they describe; a prompt without them is returned
  untouched.
"""

from __future__ import annotations

from core.agent.prompt.names import (
    SECTION_ON_DEMAND_LOADING,
    SECTION_SELECTION_HINTS,
    SECTION_STYLE_EXAMPLES,
    SECTION_TOOL_INDEX,
)
from core.agent.prompt.sections.parent import _CORE_HEAD, _SAFETY_HEAD, _STYLE_HEAD
from core.agent.prompt.structure import Band, SectionRegistry

STAGED_TOOL_RESULT_EXCLUDES = (
    SECTION_STYLE_EXAMPLES,
    SECTION_TOOL_INDEX,
    SECTION_SELECTION_HINTS,
)
STAGED_ANSWER_ONLY_EXCLUDES = (
    SECTION_STYLE_EXAMPLES,
    SECTION_TOOL_INDEX,
    SECTION_SELECTION_HINTS,
    SECTION_ON_DEMAND_LOADING,
)


def staged_static_content(
    registry: SectionRegistry,
    with_tools: bool,
    prefix: str = "",
) -> str:
    """The STATIC band for a later model call, staged by section name.

    `prefix` is any system content the loop merged in front of the
    registry render (the conversation-summary section) — it is never
    staged. A registry without the parent sections renders unchanged:
    the staged cut of sections a prompt never had is a no-op, matching
    the legacy head-find's "returned untouched" contract.
    """
    excludes = STAGED_TOOL_RESULT_EXCLUDES if with_tools else STAGED_ANSWER_ONLY_EXCLUDES
    body = registry.render(Band.STATIC, exclude=list(excludes))
    if prefix and body:
        return prefix + "\n\n" + body
    return prefix or body


def staged_system_prompt(prompt: str, with_tools: bool) -> str:
    """Input selection for calls AFTER a tool result: what the model still needs.

    The style examples, the tool-list one-liners and the selection hints only
    help it choose its FIRST tool and its reply style, so a call that already
    holds a tool result drops them; every rule (multi-part completion,
    act-not-announce, anti-hedging, check-before-write, machine facts, safety)
    stays, because those decide whether it stops too early. An answer-only call
    (no tools offered) also drops the on-demand-loading paragraph. A prompt
    without the expected sections is returned untouched.
    """
    a = prompt.find(_STYLE_HEAD)
    c = prompt.find(_CORE_HEAD)
    d = prompt.find(_SAFETY_HEAD)
    if not (0 <= a < c < d):
        return prompt
    return prompt[:a] + (prompt[c:] if with_tools else prompt[d:])

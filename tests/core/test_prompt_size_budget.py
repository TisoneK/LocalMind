"""
Session 126: regression guard on agent system-prompt size.

The system prompt is a fixed per-step cost in the agent loop (paid on EVERY
step, multiplied by the number of steps in a plan). Session 124 scoped the
tool definitions; Session 126 trimmed the static prompt itself:
  - removed the `shell_guidance` block (verbatim duplicate of CRITICAL RULES)
  - condensed the 9 personas in `_PERSONA_MAP` (dropped fabrication/narration
    duplicates; kept find_path, file_task-vs-shell, binary, read-before-write,
    web_fetch-when-thin rules)
  - trimmed `skills/shell.md` (dropped "Output handling" = exact duplicate of
    CRITICAL RULES #4 and the platform table duplicated by TOOL ARGUMENT RULES)

Session 144 (ADR-17 track 1): consolidated the post-persona tail — merged
CRITICAL RULES + VERIFICATION + RESULT VERIFICATION + RESPONSE FORMATTING into
one deduplicated block (anti-fabrication / "never say Done" / exact-report
appeared 3-4x) and capped the injected skill fragment at 2,000 chars (heads
carry the distinctive per-intent expertise; tails overlapped the universal
rules). SHELL system prompt: 16,449 → 12,981 chars (~876 tok saved per
agent-path call); editing intents: ~20.5K → ~13K chars.

Budgets below are the measured post-144 sizes + ~1-1.5K headroom so normal
prompt evolution doesn't churn the test daily, but re-adding a duplicate
section (a multi-KB regression) trips it. Intentional additions must be
justified, not silently absorbed.
"""

import pytest
from core.agent.prompts import build_agent_system_prompt
from core.models import Intent

# intent -> max chars for the system prompt with EMPTY tool metadata list
# (the tool list is measured separately by test_intent_tool_scoping).
# Measured 2026-08-11 post-Session-144 trim.
_BUDGETS = {
    Intent.SHELL: 15_000,  # measured 12,981 (was 16,449 post-126)
    Intent.SYSINFO: 13_500,  # measured 11,654
    Intent.CODE_EXEC: 15_500,  # measured 13,043
    Intent.FILE_WRITE: 15_500,  # measured 13,083
    Intent.FILE_EDIT: 15_500,  # measured 13,088
    Intent.FILE_TASK: 16_000,  # measured 13,566
    Intent.WEB_SEARCH: 16_000,  # measured 13,630
    Intent.WEB_FETCH: 15_000,  # measured 12,817
    Intent.MEMORY_OP: 14_000,  # measured 12,150
    Intent.BROWSE: 14_500,  # measured 12,285
    Intent.CHAT: 6_000,  # measured 4,730 (unchanged)
}

# Load-bearing rules that MUST survive future trims — the budget test guards
# against bloat; these guard against over-trimming (a smaller prompt is only
# good if it still carries the rules past sessions fought for).
_LOAD_BEARING_MARKERS = {
    Intent.SHELL: [
        "find_path",  # Session 125: locate-by-name, never dir-dump
        "file_task",  # directory listings vs file contents split
    ],
    Intent.CODE_EXEC: ["file_task"],  # read-before-write
    Intent.WEB_SEARCH: ["web_fetch"],  # fetch when snippets too thin
}


@pytest.mark.parametrize("intent", sorted(_BUDGETS, key=lambda i: i.value))
def test_system_prompt_within_budget(intent: Intent) -> None:
    # SHELL measured 16,449 post-126 (was 19,027 pre-change) — the budget
    # keeps it well below the pre-126 bloat while allowing normal evolution.
    prompt = build_agent_system_prompt(intent=intent, available_tools=[])
    assert len(prompt) <= _BUDGETS[intent], (
        f"system prompt for {intent.value} grew to {len(prompt):,} chars "
        f"(budget {_BUDGETS[intent]:,}) — likely a duplicate section was "
        f"re-added; trim or justify before raising the budget"
    )


@pytest.mark.parametrize("intent", sorted(_LOAD_BEARING_MARKERS, key=lambda i: i.value))
def test_load_bearing_rules_survive(intent: Intent) -> None:
    """Future trims must not drop the rules past sessions fought for — a
    smaller prompt is only good if it still carries them."""
    prompt = build_agent_system_prompt(intent=intent, available_tools=[])
    for marker in _LOAD_BEARING_MARKERS[intent]:
        assert marker in prompt, (
            f"{intent.value} prompt lost load-bearing marker {marker!r} — "
            f"re-add it or get explicit sign-off on removing the rule"
        )




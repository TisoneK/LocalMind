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

Budgets below are the measured post-126 sizes + ~1-1.5K headroom so normal
prompt evolution doesn't churn the test daily, but re-adding a duplicate
section (a multi-KB regression) trips it. Intentional additions must be
justified, not silently absorbed.
"""

import pytest
from core.agent.prompts import build_agent_system_prompt
from core.models import Intent

# intent -> max chars for the system prompt with EMPTY tool metadata list
# (the tool list is measured separately by test_intent_tool_scoping).
_BUDGETS = {
    Intent.SHELL: 17_500,  # measured 16,449 (was 19,027 pre-126)
    Intent.SYSINFO: 16_500,  # measured 15,122 (shares skills/shell.md)
    Intent.CODE_EXEC: 21_000,  # measured 20,056
    Intent.FILE_WRITE: 21_000,  # measured 19,950
    Intent.FILE_EDIT: 21_500,  # measured 20,548
    Intent.FILE_TASK: 21_500,  # measured 20,579
    Intent.WEB_SEARCH: 21_000,  # measured 19,825
    Intent.WEB_FETCH: 20_000,  # measured 19,012
    Intent.MEMORY_OP: 16_500,  # measured 15,618
    Intent.BROWSE: 18_500,  # measured 17,761
    Intent.CHAT: 6_000,  # measured 4,730
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




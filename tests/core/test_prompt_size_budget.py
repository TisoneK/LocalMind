"""
Regression guard on agent system-prompt size.

The system prompt is a fixed per-step cost in the agent loop (paid on EVERY
step, multiplied by the number of steps in a plan). An earlier pass scoped
the tool definitions; this guard then trimmed the static prompt itself:
  - removed the `shell_guidance` block (verbatim duplicate of CRITICAL RULES)
  - condensed the 9 personas in `_PERSONA_MAP` (dropped fabrication/narration
    duplicates; kept find_path, file_task-vs-shell, binary, read-before-write,
    web_fetch-when-thin rules)
  - trimmed `skills/shell.md` (dropped "Output handling" = exact duplicate of
    CRITICAL RULES #4 and the platform table duplicated by TOOL ARGUMENT RULES)

The prompt-assembly consolidation merged the post-persona tail — merged
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
# Measured 2026-08-11 after that trim.
_BUDGETS = {
    # Env vars moved to a trailing turn-context
    # message and the formatting example trimmed — ~2,270 chars off each
    # execute intent. Budgets tightened to lock the reduction in.
    # +400 each (rule 10 "TOOL OUTPUT IS RETAINED" — the
    # repeated-listings fix; hard-capped at ~330 chars, this is the once-off
    # cost of telling models not to re-list what they already have).
    Intent.SHELL: 12_200,  # +100; +200 (shell-writes-last-resort)
    Intent.SYSINFO: 11_500,  # 2026-08-21: +500; +400; +300; +300 (dir_explorer steering in the planning templates + TOOL ARGUMENT rule — the always-present executor prompt grew with the new core tool; measured 11,355, justified rather than absorbed)
    Intent.CODE_EXEC: 12_500,  # Session 351: +100; +350; +250
    Intent.FILE_WRITE: 12_600,  # +400; +200
    Intent.FILE_EDIT: 12_600,  # +400; +200
    Intent.FILE_TASK: 13_100,  # 2026-08-21: +500; +400; +200
    Intent.WEB_SEARCH: 13_100,  # 2026-08-21: +500; +400; +200
    Intent.WEB_FETCH: 12_300,  # +100; +200
    Intent.MEMORY_OP: 11_700,  # +500; +200
    Intent.BROWSE: 11_800,  # +100; +200
    Intent.CHAT: 6_000,  # measured 4,730 (unchanged — no CRITICAL RULES in CHAT branch)
}

# Load-bearing rules that MUST survive future trims — the budget test guards
# against bloat; these guard against over-trimming (a smaller prompt is only
# good if it still carries the rules past sessions fought for).
_LOAD_BEARING_MARKERS = {
    Intent.SHELL: [
        "system_search",  # Session 400: unified search front door, never dir-dump
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


def test_system_prompt_has_no_dynamic_env_that_busts_cache() -> None:
    """Session 245 Lever 1: the agent system prompt must stay byte-stable so
    the system+tools prefix caches. It must NOT embed per-turn/per-minute
    content (the current time, or the '## Environment' block that carries it) —
    that lives in a trailing turn-context message instead.
    """
    prompt = build_agent_system_prompt(intent=Intent.SHELL, available_tools=[])
    assert "## Environment" not in prompt, "env block leaked back into the cached prompt"
    assert "Current time:" not in prompt, "current time (per-minute cache-buster) is back in the cached prompt"
    # Two builds a moment apart must be identical (no clock/date/uuid inside).
    import time as _t
    a = build_agent_system_prompt(intent=Intent.SHELL, available_tools=[])
    _t.sleep(0.01)
    b = build_agent_system_prompt(intent=Intent.SHELL, available_tools=[])
    assert a == b, "system prompt is not byte-stable across builds — a dynamic value leaked in"




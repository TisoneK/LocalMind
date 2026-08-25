"""Tests for the pending-ACTION narration detector (B-2026-08-25-11, Session 405).

The user's live "delete huge files" report: the agent narrated "Got it — time
to act. Let me verify the exact paths and then delete them." and the loop ended
with nothing deleted. `narrates_pending_action` detects a committed-but-
unexecuted state-changing action so the gate can FORCE a tool call — the
OPPOSITE remedy from `narrates_after_evidence` (which wants synthesis).

Safety-critical negative: an OFFER ("let me know if you want me to delete
them") must NOT be treated as a pending action — coercing a tool call there
would delete files the user never confirmed.
"""

from __future__ import annotations

import pytest

from core.agent.loop import narrates_pending_action

# ── Positive: committed state-changing action, no tool call ──────────────────


def test_live_delete_narration_fires():
    """The exact live-trace prose that ended the turn with nothing deleted."""
    text = "Got it — time to act. Let me verify the exact paths and then delete them."
    assert narrates_pending_action(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Let me delete those files now.",
        "I'll remove the old logs.",
        "Now I'll create the project structure.",
        "I'm going to move them into an archive folder.",
        "Time to run the cleanup script.",
        "Let me write the config file.",
        "I'll uninstall the unused package.",
    ],
)
def test_committed_actions_fire(text):
    assert narrates_pending_action(text) is True


def test_live_gerund_ending_fires():
    """Session 405 live-test (bankofai/deepseek-v4-flash): the turn ended with
    this exact answer and no rm — a gerund ending with no 'let me/I'll' lead-in."""
    text = (
        "The folder contains exactly two .bin files — bigfile_A.bin (40M) and "
        "bigfile_B.bin (55M) — plus a keep/ subdirectory, which I will leave "
        "untouched. Deleting the two .bin files now:"
    )
    assert narrates_pending_action(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Deleting the two files now:",
        "Removing the old logs now.",
        "Creating the project structure now:",
        "Great — the paths check out. Deleting them now:",
    ],
)
def test_gerund_imminent_endings_fire(text):
    assert narrates_pending_action(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # Synthesis gerunds ending in "now:" are NOT actions — post-evidence owns them.
        "I have all the data. Summarizing the results now:",
        "Checking the remaining directories now:",
        # A gerund action mentioned but the answer does NOT end on the imminent tail.
        "Deleting files can be risky, so I recommend reviewing them first.",
    ],
)
def test_gerund_non_actions_do_not_fire(text):
    assert narrates_pending_action(text) is False


# ── Safety negative: offers must NOT be coerced into an action ───────────────


@pytest.mark.parametrize(
    "text",
    [
        "I found 3 large files. Let me know if you want me to delete them.",
        "There are old logs here. Would you like me to remove them?",
        "I can move them to an archive if you'd like.",
        "Shall I delete the duplicates?",
        "Should I run the cleanup for you?",
    ],
)
def test_offers_do_not_fire(text):
    """An un-confirmed offer must never force a destructive tool call."""
    assert narrates_pending_action(text) is False


# ── Other negatives ──────────────────────────────────────────────────────────


def test_past_tense_completion_does_not_fire():
    """Already done — no future-intent lead-in, so no coercion to redo it."""
    assert narrates_pending_action("I deleted the three files; 4.2 GB reclaimed.") is False
    assert narrates_pending_action("Removed them. Your disk now has 12 GB free.") is False


def test_synthesis_narration_does_not_fire():
    """'Let me check the results' is post-evidence synthesis, not a mutation."""
    assert narrates_pending_action("Let me check the results and summarize.") is False


def test_no_action_verb_does_not_fire():
    assert narrates_pending_action("I'll explain what I found in the directory.") is False


def test_long_report_does_not_fire():
    """A long answer that merely mentions deleting is real content, not narration."""
    text = "Here is a summary of your disk. " * 30 + "You could delete the cache."
    assert len(text) > 500
    assert narrates_pending_action(text) is False


def test_empty_and_short_do_not_fire():
    assert narrates_pending_action("") is False
    assert narrates_pending_action("delete") is False


# ── Gate integration: force a tool call, never suppress the action ───────────


def _make_trace(final_response: str, *, has_tool_step: bool = True):
    """Minimal trace-like object; a search step ran (the delete-huge-files
    shape) so the iter-0 ACTION-NARRATION detector does not preempt."""
    from types import SimpleNamespace

    steps = []
    if has_tool_step:
        steps.append(SimpleNamespace(tool_name="system_search", tool_input="largest", tool_failed=False))
    steps.append(SimpleNamespace(tool_name="", tool_input=None, tool_failed=False))
    return SimpleNamespace(
        steps=steps,
        success_criteria=[],
        final_response=final_response,
        gate_summary="",
    )


@pytest.mark.asyncio
async def test_gate_forces_tool_on_pending_delete():
    """The live delete case: gate rejects, injects [PENDING ACTION], forces a tool."""
    from core.agent.loop import AgentLoop
    from core.models import Intent

    loop = AgentLoop(adapter=None)
    trace = _make_trace(
        "Got it — time to act. Let me verify the exact paths and then delete them.",
    )
    loop_messages = [{"role": "user", "content": "delete the huge files"}]
    force = [False]

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=1,
        effective_max_iter=10,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=Intent.SHELL,
        obs=None,
        is_parent=True,
        gate_force_tool=force,
    )

    assert is_final is False
    assert suffix == ""
    assert any("[PENDING ACTION]" in str(m.get("content", "")) for m in loop_messages)
    assert force[0] is True, "the main loop must be told to force a tool_choice"


@pytest.mark.asyncio
async def test_gate_does_not_coerce_an_offer():
    """SAFETY: an un-confirmed offer must be accepted as-is — never force a delete."""
    from core.agent.loop import AgentLoop
    from core.models import Intent

    loop = AgentLoop(adapter=None)
    trace = _make_trace(
        "I found 3 large files (12 GB total). Let me know if you want me to delete them.",
    )
    loop_messages = [{"role": "user", "content": "find the huge files"}]
    force = [False]

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=1,
        effective_max_iter=10,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=Intent.SHELL,
        obs=None,
        is_parent=True,
        gate_force_tool=force,
    )

    assert not any("[PENDING ACTION]" in str(m.get("content", "")) for m in loop_messages)
    assert force[0] is False


@pytest.mark.asyncio
async def test_gate_oneshot_does_not_renudge():
    """A second consecutive pending-action narration does not re-nudge."""
    from core.agent.loop import AgentLoop
    from core.models import Intent

    loop = AgentLoop(adapter=None)
    trace = _make_trace("Let me delete those files now.")
    loop_messages = [
        {"role": "user", "content": "delete the huge files"},
        {"role": "user", "content": "\n[PENDING ACTION] ... (already nudged)\n"},
    ]
    force = [False]

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=2,
        effective_max_iter=10,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=Intent.SHELL,
        obs=None,
        is_parent=True,
        gate_force_tool=force,
    )

    # One-shot: fell through to accept, no second nudge, no force.
    assert is_final is True
    assert force[0] is False

"""Tests for the prose-tool-commitment detector + gate re-prompt (B-2026-08-20-6, Session 307).

Covers:
- ``prose_commits_to_tool_action`` positive/negative cases
- the gate's new branch: when the parent produces a prose commitment with no
  tool_call, the gate returns ``("", False)`` and injects a ``[TOOL COMMITMENT]``
  re-prompt into ``loop_messages``
- the one-shot guard: a second consecutive prose commitment does NOT re-nudge
  (falls through to accept)
- the no-tool-call guard: a prose commitment on an iteration that DID run a
  tool is not triggered (the completion-floor path owns that case)
- non-parent agents: the detector is scoped to ``is_parent`` only
"""

from __future__ import annotations

import pytest

from core.agent.loop import prose_commits_to_tool_action

# ── Detector unit tests ─────────────────────────────────────────────────────


def test_detector_positive_phrase_plus_tool_name():
    """The exact live-trace prose from Session 306 should be detected."""
    text = (
        "I'll help you list the files in the /tmp directory using the shell tool. "
        "Let me first describe the shell tool to understand its schema."
    )
    assert prose_commits_to_tool_action(text) is True


def test_detector_positive_describe_tool_commitment():
    text = "Let me describe the shell tool to understand its schema."
    assert prose_commits_to_tool_action(text) is True


def test_detector_positive_ill_use():
    text = "I'll use the file_read tool to look at that."
    assert prose_commits_to_tool_action(text) is True


def test_detector_positive_i_need_to():
    text = "I need to call the web_search tool to find that."
    assert prose_commits_to_tool_action(text) is True


def test_detector_positive_first_i_should():
    text = "First, I should run the shell command to check."
    assert prose_commits_to_tool_action(text) is True


def test_detector_negative_legitimate_prose_answer():
    """A real answer that happens to mention 'tool' must not trigger."""
    text = (
        "I have access to many tools including shell, file_read, and web_search. "
        "You can ask me to use any of them. What would you like me to do?"
    )
    # No commitment phrase → not triggered, even though "tool" appears.
    assert prose_commits_to_tool_action(text) is False


def test_detector_negative_phrase_without_tool_name():
    """A commitment phrase without a tool name is conversational, not a preamble."""
    text = "Let me use an analogy to explain this concept."
    assert prose_commits_to_tool_action(text) is False


def test_detector_negative_tool_name_without_commitment_phrase():
    """A tool mention without a commitment phrase is a capability question."""
    text = "The shell tool is available for running commands."
    assert prose_commits_to_tool_action(text) is False


def test_detector_negative_empty_text():
    assert prose_commits_to_tool_action("") is False
    assert prose_commits_to_tool_action(None) is False  # type: ignore[arg-type]


def test_detector_case_insensitive():
    """Phrases match regardless of capitalization."""
    text = "LET ME DESCRIBE THE SHELL TOOL."
    assert prose_commits_to_tool_action(text) is True


def test_detector_negative_past_tense_answer():
    """A past-tense 'I used the shell tool' is a report, not a commitment.

    Note: 'i used' is NOT in the commitment-phrase list (the list is
    present/future tense: 'let me', 'i'll', 'i need to', 'i should',
    'i'm going to', 'i will'). So a legitimate post-tool summary that
    says 'I used the shell tool and found...' is correctly NOT triggered.
    """
    text = "I used the shell tool and found 3 files in the directory."
    assert prose_commits_to_tool_action(text) is False


# ── Gate integration tests ──────────────────────────────────────────────────
# These test the new branch in ``_acceptance_gate_at_final_answer`` directly
# by constructing a minimal trace + loop_messages and calling the method.


def _make_trace_with_final_response(final_response: str, *, has_tool_step: bool = False):
    """Build a minimal trace-like object for the gate."""
    from types import SimpleNamespace

    steps = []
    if has_tool_step:
        steps.append(SimpleNamespace(tool_name="shell", tool_input="ls", tool_failed=False))
    # The final-answer step (no tool_name) carries the prose.
    steps.append(SimpleNamespace(tool_name="", tool_input=None, tool_failed=False))
    return SimpleNamespace(
        steps=steps,
        success_criteria=[],  # no criteria → triggers the no-criteria branch
        final_response=final_response,
        gate_summary="",
    )


@pytest.mark.asyncio
async def test_gate_reprompts_on_prose_commitment_no_tool_call():
    """Parent produces a prose commitment with no tool_call → gate injects re-prompt."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_final_response(
        "I'll help you list the files using the shell tool. Let me first describe it.",
        has_tool_step=False,
    )
    loop_messages = [{"role": "user", "content": "list /tmp files"}]

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=10,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=None,  # type: ignore[arg-type]
        obs=None,
        is_parent=True,
    )

    # Gate returned "not final" — the loop should continue.
    assert is_final is False
    assert suffix == ""
    # The re-prompt was appended to loop_messages.
    assert any("[TOOL COMMITMENT]" in str(m.get("content", "")) for m in loop_messages)


@pytest.mark.asyncio
async def test_gate_oneshot_guard_does_not_renudge_twice():
    """A second consecutive prose commitment does NOT re-nudge (one-shot bound)."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_final_response(
        "I'll use the shell tool to list files.", has_tool_step=False,
    )
    # loop_messages already contains a [TOOL COMMITMENT] nudge from a prior iter.
    loop_messages = [
        {"role": "user", "content": "list /tmp files"},
        {"role": "assistant", "content": "I'll use the shell tool to list files."},
        {"role": "user", "content": "\n[TOOL COMMITMENT] You wrote that you would use a tool..."},
        {"role": "assistant", "content": "I'll use the shell tool to list files."},  # still no tool_call
    ]
    original_len = len(loop_messages)

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=1,  # second iteration
        effective_max_iter=10,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=None,  # type: ignore[arg-type]
        obs=None,
        is_parent=True,
    )

    # One-shot guard: fall through to accept (the model had its chance).
    assert is_final is True
    assert suffix == ""
    # No new nudge was appended.
    assert len(loop_messages) == original_len


@pytest.mark.asyncio
async def test_gate_does_not_trigger_when_tool_ran():
    """If a tool ran this run, the prose-commitment detector is skipped
    (the completion-floor path owns that case)."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    # has_tool_step=True → the detector's no-tool-call guard skips.
    trace = _make_trace_with_final_response(
        "I used the shell tool. Let me describe what I found.",  # commitment phrase + tool name
        has_tool_step=True,
    )
    loop_messages = [{"role": "user", "content": "list /tmp files"}]
    original_len = len(loop_messages)

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=10,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=None,  # type: ignore[arg-type]
        obs=None,
        is_parent=True,
    )

    # No re-prompt; the legacy path applies (tool ran, no failure → accept).
    assert is_final is True
    assert len(loop_messages) == original_len


@pytest.mark.asyncio
async def test_gate_does_not_trigger_for_non_parent():
    """Non-parent agents (legacy/child paths) don't get the prose-commitment nudge."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_final_response(
        "I'll use the shell tool to list files.", has_tool_step=False,
    )
    loop_messages = [{"role": "user", "content": "list /tmp files"}]
    original_len = len(loop_messages)

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=10,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=None,  # type: ignore[arg-type]
        obs=None,
        is_parent=False,  # non-parent
    )

    # Detector is parent-scoped; legacy path applies.
    assert is_final is True
    assert len(loop_messages) == original_len


@pytest.mark.asyncio
async def test_gate_does_not_trigger_on_legitimate_prose_answer():
    """A legitimate prose answer (no commitment phrase) is accepted as before."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_final_response(
        "The files in /tmp include cache, log, and scratch directories. "
        "I have access to many tools but didn't need any for this answer.",
        has_tool_step=False,
    )
    loop_messages = [{"role": "user", "content": "what's in /tmp?"}]
    original_len = len(loop_messages)

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=10,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=None,  # type: ignore[arg-type]
        obs=None,
        is_parent=True,
    )

    # Legitimate prose → accepted (no re-prompt).
    assert is_final is True
    assert len(loop_messages) == original_len


@pytest.mark.asyncio
async def test_gate_respects_iteration_cap():
    """At the iteration cap, the detector does NOT re-nudge (would exceed max_iter)."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_final_response(
        "I'll use the shell tool to list files.", has_tool_step=False,
    )
    loop_messages = [{"role": "user", "content": "list /tmp files"}]
    original_len = len(loop_messages)

    # iteration + 1 >= effective_max_iter → fall through to accept.
    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=9,
        effective_max_iter=10,  # iteration + 1 = 10 >= 10
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=None,
        intent=None,  # type: ignore[arg-type]
        obs=None,
        is_parent=True,
    )

    assert is_final is True
    assert len(loop_messages) == original_len

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


# ── The agent judges its own short reply (owner transcript 2026-09-21) ─────
# "…Let me open it." / "…Let me actually check where your network says you are."
# ended turns; a phrase list missed the second wording, so the MODEL decides
# (core/agent/completion_judge.py). Also closes P-2026-09-16-43.

from types import SimpleNamespace  # noqa: E402

from core.agent.completion_judge import reply_leaves_work_pending  # noqa: E402
from core.agent.text_tools import _is_tool_talk  # noqa: E402


class _Verdict:
    """Adapter stub: answers the judge with a fixed word, or raises."""

    def __init__(self, word="", boom=False):
        self.word, self.boom, self.calls = word, boom, 0

    async def chat(self, messages, temperature=0.0, intent="chat"):
        self.calls += 1
        if self.boom:
            raise RuntimeError("provider down")
        yield SimpleNamespace(text=self.word, error=None)


_PROMISE = (
    "Fair challenge — I've been assuming it from your locale. "
    "Let me actually check where your network says you are."
)


@pytest.mark.asyncio
async def test_judge_pending_and_done():
    assert await reply_leaves_work_pending(_Verdict("PENDING"), "am I in Nairobi?", _PROMISE) is True
    assert await reply_leaves_work_pending(_Verdict("DONE"), "am I in Nairobi?", "Yes — Nairobi.") is False


@pytest.mark.asyncio
async def test_judge_never_blocks():
    assert await reply_leaves_work_pending(_Verdict(boom=True), "q", _PROMISE) is False
    assert await reply_leaves_work_pending(None, "q", _PROMISE) is False


@pytest.mark.asyncio
async def test_judge_skips_long_or_question_replies_without_a_call():
    adapter = _Verdict("PENDING")
    assert await reply_leaves_work_pending(adapter, "q", "x" * 700) is False
    assert await reply_leaves_work_pending(adapter, "q", "Which folder do you mean?") is False
    assert adapter.calls == 0


def test_tool_talk_catches_describe():
    assert _is_tool_talk("Let me describe the shell tool first.") is True
    assert _is_tool_talk("I will describe the shell tool to the user.") is True


@pytest.mark.asyncio
async def test_gate_reprompts_after_tool_ran_when_judge_says_pending():
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_final_response(_PROMISE, has_tool_step=True)
    loop_messages = [{"role": "user", "content": "am I in Nairobi?"}]

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace, iteration=1, effective_max_iter=10, loop_messages=loop_messages,
        observation_log="", active_adapter=_Verdict("PENDING"), intent=None, obs=None, is_parent=True,  # type: ignore[arg-type]
    )

    assert is_final is False
    assert any("[TOOL COMMITMENT]" in str(m.get("content", "")) for m in loop_messages)


@pytest.mark.asyncio
async def test_gate_accepts_when_judge_says_done_and_nudges_only_once():
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    trace = _make_trace_with_final_response("Yes — Nairobi, per your IP.", has_tool_step=True)
    msgs = [{"role": "user", "content": "am I in Nairobi?"}]
    _, done = await loop._acceptance_gate_at_final_answer(
        trace=trace, iteration=1, effective_max_iter=10, loop_messages=msgs,
        observation_log="", active_adapter=_Verdict("DONE"), intent=None, obs=None, is_parent=True,  # type: ignore[arg-type]
    )
    assert done is True

    nudged = [{"role": "user", "content": "[TOOL COMMITMENT] act"}]
    adapter = _Verdict("PENDING")
    trace = _make_trace_with_final_response(_PROMISE, has_tool_step=True)
    await loop._acceptance_gate_at_final_answer(
        trace=trace, iteration=1, effective_max_iter=10, loop_messages=nudged,
        observation_log="", active_adapter=adapter, intent=None, obs=None, is_parent=True,  # type: ignore[arg-type]
    )
    assert adapter.calls == 0  # already nudged: no second judge call, no second nudge


# ── The judge is a lane on the turn bus (ADR-66) ────────────────────────────

from core.agent.completion_judge import SOURCE, evidence_digest, reply_is_pending  # noqa: E402
from core.agent.turn_bus import TurnBus  # noqa: E402


@pytest.mark.asyncio
async def test_verdict_is_published_as_a_fact_with_provenance():
    seen = []
    bus = TurnBus(on_fact=lambda f, stale: seen.append((f.source, f.kind, stale)))
    assert await reply_is_pending(bus, _Verdict("PENDING"), "am I in Nairobi?", _PROMISE, step=3) is True
    fact = bus.latest("verdict", source=SOURCE, step=3)
    assert fact.value["verdict"] == "pending" and fact.grounded_in == ("reply@step3",)
    assert (SOURCE, "verdict", False) in seen  # emitted for the bus_fact obs event


@pytest.mark.asyncio
async def test_failed_judge_is_an_unjudged_verdict_not_a_pending_one():
    bus = TurnBus()
    assert await reply_is_pending(bus, _Verdict(boom=True), "q", _PROMISE, step=1) is False
    assert bus.latest("verdict", source=SOURCE, step=1).value["verdict"] == "unjudged"


@pytest.mark.asyncio
async def test_verdict_about_a_replaced_plan_is_stale_and_never_applied():
    bus = TurnBus()

    class _ReplansMidJudge(_Verdict):
        async def chat(self, messages, temperature=0.0, intent="chat"):
            bus.replan()  # the plan is replaced while the judge is thinking
            async for c in super().chat(messages, temperature, intent):
                yield c

    assert await reply_is_pending(bus, _ReplansMidJudge("PENDING"), "q", _PROMISE, step=2) is False
    assert bus.facts(kind="verdict") == []  # stale: on record, not current
    assert len(bus.facts(kind="verdict", include_stale=True)) == 1


@pytest.mark.asyncio
async def test_judge_sees_the_evidence_gathered_this_turn():
    steps = [
        SimpleNamespace(tool_name="web_fetch", tool_failed=True, observation="HTTP 403 blocked"),
        SimpleNamespace(tool_name="", tool_failed=False, observation=""),
    ]
    assert "web_fetch [FAILED]: HTTP 403 blocked" in evidence_digest(steps)
    assert evidence_digest([]) == ""

    class _Capture(_Verdict):
        async def chat(self, messages, temperature=0.0, intent="chat"):
            self.prompt = messages[0]["content"]
            async for c in super().chat(messages, temperature, intent):
                yield c

    adapter = _Capture("DONE")
    await reply_is_pending(TurnBus(), adapter, "weather?", "It is 22 C.", steps=steps)
    assert "web_fetch [FAILED]" in adapter.prompt

"""Zero-tool conversational turns are accepted at the final-answer gate.

Regression for the live export of 2026-10-31 ("Quick check-in", glm-4.5-flash):
the greeting "Hey sup LM?" was answered correctly, then the acceptance gate
ran the reply-pending completion judge on it (a zero-evidence turn — the
judge's evidence digest is empty, so its only input is the text itself), the
weak model returned PENDING, and the gate injected a ``[TOOL COMMITMENT]``
re-prompt whose hardcoded unmet reason ("model committed to a tool action in
prose") was false. The turn burned 4 model calls and ~100 s re-answering a
greeting, and the model's visible thinking spent its cycles doubting a
commitment it never made.

Contract pinned here:
  1. A zero-tool turn with a clean reply — no prose commitment, no narrated
     pending action — is ACCEPTED whatever the intent says (the export's
     greeting was misrouted to `analyze`; the intent label must not matter).
     The completion judge is never invoked: every zero-tool false-positive
     it could catch is already caught deterministically by the detectors.
  2. The detectors still win when the prose actually commits to a tool
     action — even on a chat turn.
  3. When tools DID run, the judge keeps its job (an answer that ends by
     promising a next step it never took) — and when IT is the trigger, the
     gate event names the judge, never the prose-commitment reason.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.models import Intent
from core.obs import ObsCollector

pytestmark = pytest.mark.asyncio


def _trace(final_response: str, *, has_tool_step: bool = False):
    """Minimal trace for the gate's no-criteria branch."""
    steps = []
    if has_tool_step:
        steps.append(SimpleNamespace(tool_name="shell", tool_input="ls", tool_failed=False))
    steps.append(SimpleNamespace(tool_name="", tool_input=None, tool_failed=False))
    return SimpleNamespace(
        steps=steps,
        success_criteria=[],
        final_response=final_response,
        gate_summary="",
    )


def _gate_kwargs(intent, obs=None, message="Hey sup LM?", **overrides):
    kwargs = dict(
        iteration=0,
        effective_max_iter=10,
        loop_messages=[{"role": "user", "content": message}],
        observation_log="",
        active_adapter=None,
        intent=intent,
        obs=obs,
        is_parent=True,
        reformulated_message=message,
    )
    kwargs.update(overrides)
    return kwargs


async def _gate(loop, trace, **kwargs):
    return await loop._acceptance_gate_at_final_answer(trace=trace, **kwargs)


async def test_chat_greeting_accepts_without_judge_call():
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)

    async def _judge_must_not_run(*a, **k):
        raise AssertionError("reply_is_pending ran on a clean zero-tool turn")

    with patch("core.agent.loop.reply_is_pending", side_effect=_judge_must_not_run):
        suffix, is_final = await _gate(
            loop,
            _trace("Hey! I'm doing well, thanks for checking in. How can I help you today?"),
            **_gate_kwargs(Intent.CHAT),
        )

    assert is_final is True
    assert suffix == ""


async def test_misrouted_intent_still_accepts_a_clean_zero_tool_answer():
    """The live export's greeting was classified `analyze`, not `chat` — the
    accept must not depend on the intent label being right."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)

    async def _judge_must_not_run(*a, **k):
        raise AssertionError("reply_is_pending ran on a clean zero-tool turn")

    with patch("core.agent.loop.reply_is_pending", side_effect=_judge_must_not_run):
        suffix, is_final = await _gate(
            loop,
            _trace("Hey! I'm doing well, thanks for checking in."),
            **_gate_kwargs(Intent.ANALYZE),
        )

    assert is_final is True
    assert suffix == ""


async def test_chat_turn_whose_prose_commits_to_a_tool_still_gets_nudged():
    """The detectors win over the conversational accept: "let me use the
    shell tool" is narration even on a CHAT turn."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    messages = [{"role": "user", "content": "check what's in tmp"}]

    suffix, is_final = await _gate(
        loop,
        _trace("Sure, let me use the shell tool to check that for you."),
        **_gate_kwargs(Intent.CHAT, None, message="check what's in tmp", loop_messages=messages),
    )

    assert is_final is False
    assert suffix == ""
    assert any("[TOOL COMMITMENT]" in str(m.get("content", "")) for m in messages)


async def test_post_evidence_judge_nudge_names_the_judge_not_the_prose():
    """Tools ran, then the answer ends by promising more. The judge is the
    trigger — so the gate event must say THAT. The old hardcoded reason
    blamed a prose commitment the model never made."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    obs = ObsCollector()

    async def _pending(*a, **k):
        return True

    with patch("core.agent.loop.reply_is_pending", side_effect=_pending):
        suffix, is_final = await _gate(
            loop,
            _trace(
                "I found the server logs. Let me open the error file next.",
                has_tool_step=True,
            ),
            **_gate_kwargs(
                Intent.ANALYZE, obs,
                message="check the server logs",
                loop_messages=[{"role": "user", "content": "check the server logs"}],
            ),
        )

    assert is_final is False
    events = [e for e in obs.history() if e.type == "agent_loop_gate_failed_replan"]
    assert len(events) == 1
    assert events[0].data["unmet"] == ["completion judge judged the reply still pending"]


async def test_prose_commitment_nudge_keeps_its_reason():
    """The genuine prose-commitment trigger keeps its (correct) reason."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=None)
    obs = ObsCollector()
    messages = [{"role": "user", "content": "list /tmp files"}]

    async def _judge_must_not_run(*a, **k):
        raise AssertionError("judge should not run when the phrase detector already fired")

    with patch("core.agent.loop.reply_is_pending", side_effect=_judge_must_not_run):
        suffix, is_final = await _gate(
            loop,
            _trace("I'll use the shell tool to list the files for you."),
            **_gate_kwargs(None, obs, message="list /tmp files", loop_messages=messages),
        )

    assert is_final is False
    events = [e for e in obs.history() if e.type == "agent_loop_gate_failed_replan"]
    assert len(events) == 1
    assert events[0].data["unmet"] == [
        "model committed to a tool action in prose but emitted no tool_call"
    ]

"""The done-rules extension: what a turn owes when a step never reported back.

Two guarantees, both stated in `core.agent.turn_outcome` rather than inline in
the loop:

1. A dead synthesis with evidence in hand is a DEGRADED_ANSWER — the turn still
   owes the user what the evidence supports, framed with what stopped the
   write-up. It is not an error, and it is not a plain answer either.
2. A call that never reported a result is recorded, never dropped. When the
   outcome is genuinely unknown the placeholder says so and forbids a blind
   re-run; a model provider rejects an assistant tool call with no result, and
   a later turn cannot reason about a call that left no trace.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from core.agent.turn_outcome import (
    SIDE_EFFECT_FREE_TOOLS,
    TurnOutcome,
    classify_provider_death,
    classify_unanswered_call,
    pair_unanswered_tool_calls,
    provider_death_answer,
)
from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk, ToolResult

# ── 1. Provider death is a done-rule ────────────────────────────────────────


class TestProviderDeathRule:
    def test_terminal_code_with_evidence_still_delivers(self):
        rule = classify_provider_death(
            error_code="payment_required",
            error_source="model_provider",
            retryable=False,
            has_successful_evidence=True,
        )
        assert rule.outcome is TurnOutcome.DEGRADED_ANSWER
        assert rule.preserve_evidence is True
        assert rule.terminal is True
        assert "payment_required" in rule.reason

    def test_retryable_death_with_evidence_delivers_without_terminal_framing(self):
        rule = classify_provider_death(
            error_code="rate_limited",
            error_source="model_provider",
            retryable=True,
            has_successful_evidence=True,
        )
        assert rule.outcome is TurnOutcome.DEGRADED_ANSWER
        assert rule.preserve_evidence is True
        assert rule.terminal is False

    def test_terminal_code_without_evidence_is_incomplete(self):
        # Nothing in hand to deliver: the honest outcome is an error, not a
        # fabricated answer assembled from nothing.
        rule = classify_provider_death(
            error_code="payment_required",
            error_source="model_provider",
            retryable=False,
            has_successful_evidence=False,
        )
        assert rule.outcome is TurnOutcome.INCOMPLETE
        assert rule.preserve_evidence is False

    def test_non_provider_source_never_preserves(self):
        rule = classify_provider_death(
            error_code="payment_required",
            error_source="tool",
            retryable=False,
            has_successful_evidence=True,
        )
        assert rule.outcome is TurnOutcome.INCOMPLETE
        assert rule.preserve_evidence is False

    def test_unknown_non_retryable_code_is_not_assumed_deliverable(self):
        rule = classify_provider_death(
            error_code="weird_500",
            error_source="model_provider",
            retryable=False,
            has_successful_evidence=True,
        )
        assert rule.outcome is TurnOutcome.INCOMPLETE
        assert rule.preserve_evidence is False


class TestProviderDeathAnswer:
    def _terminal(self):
        return classify_provider_death(
            error_code="payment_required",
            error_source="model_provider",
            retryable=False,
            has_successful_evidence=True,
        )

    def _retryable(self):
        return classify_provider_death(
            error_code="rate_limited",
            error_source="model_provider",
            retryable=True,
            has_successful_evidence=True,
        )

    def test_extracted_answer_is_delivered_raw_when_retryable(self):
        text = provider_death_answer(
            rule=self._retryable(),
            provider="SomeProvider",
            error_code="rate_limited",
            extracted="25°C and sunny.",
        )
        assert text == "25°C and sunny."

    def test_terminal_death_frames_the_evidence_it_delivers(self):
        text = provider_death_answer(
            rule=self._terminal(),
            provider="BankOfAI",
            error_code="payment_required",
            extracted="25°C and sunny.",
        )
        assert "BankOfAI" in text
        assert "payment_required" in text
        assert "as gathered" in text
        assert "25°C and sunny." in text
        assert "try again" not in text.lower()

    def test_raw_evidence_blocks_are_delivered_with_the_death_note(self):
        text = provider_death_answer(
            rule=self._terminal(),
            provider="BankOfAI",
            error_code="payment_required",
            evidence_blocks=["MSN Weather: 25°C, partly sunny.", "Second source: 24°C."],
            tool_count=2,
        )
        assert "MSN Weather: 25°C" in text
        assert "Second source: 24°C." in text
        assert "payment_required" in text
        assert "not retryable" in text
        assert "try again" not in text.lower()

    def test_no_tools_no_evidence_names_the_code_and_refuses_retry_advice(self):
        text = provider_death_answer(
            rule=self._terminal(),
            provider="BankOfAI",
            error_code="payment_required",
            tool_count=0,
        )
        assert "BankOfAI" in text
        assert "payment_required" in text
        assert "not retryable" in text
        assert "try again" not in text.lower()

    def test_rate_limit_without_evidence_keeps_the_retry_offer(self):
        text = provider_death_answer(
            rule=self._retryable(),
            provider="SomeProvider",
            error_code="rate_limited",
            tool_count=0,
        )
        assert "rate-limited" in text
        assert "try again" in text.lower()


# ── 2. Unanswered calls get a recorded result ───────────────────────────────


class TestUnansweredCall:
    def test_timeout_on_a_mutating_tool_is_unknown_and_not_retry_safe(self):
        call = classify_unanswered_call(tool_name="shell", timed_out=True)
        assert call.unknown is True
        assert call.retry_safe is False
        assert "OUTCOME UNKNOWN" in call.text
        assert "timed out" in call.text
        assert "do NOT run it again blindly" in call.text

    def test_timeout_on_a_read_only_tool_is_unknown_but_safe_to_repeat(self):
        assert "file_task" in SIDE_EFFECT_FREE_TOOLS
        call = classify_unanswered_call(tool_name="file_task", timed_out=True)
        assert call.unknown is True
        assert call.retry_safe is True
        assert "no durable side effect" in call.text

    def test_mid_run_crash_is_unknown(self):
        call = classify_unanswered_call(
            tool_name="file_write", error=RuntimeError("connection dropped")
        )
        assert call.unknown is True
        assert call.retry_safe is False
        assert "connection dropped" in call.text

    def test_argument_error_is_a_known_failure(self):
        call = classify_unanswered_call(tool_name="shell", error=ValueError("bad args"))
        assert call.unknown is False
        assert "failed" in call.text
        assert "OUTCOME UNKNOWN" not in call.text


class TestPairUnansweredToolCalls:
    def test_a_dangling_call_gets_a_recorded_result(self):
        messages = [
            {"role": "user", "content": "clear the build folder"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "function": {"name": "shell"}}],
            },
        ]
        repaired = pair_unanswered_tool_calls(messages)
        assert repaired == ["call-1"]
        assert messages[-1]["role"] == "tool"
        assert messages[-1]["tool_call_id"] == "call-1"
        assert "OUTCOME UNKNOWN" in messages[-1]["content"]

    def test_a_paired_call_is_left_alone(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "function": {"name": "shell"}}],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
        ]
        before = [dict(m) for m in messages]
        assert pair_unanswered_tool_calls(messages) == []
        assert messages == before

    def test_only_the_unanswered_call_of_two_is_repaired(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call-1", "function": {"name": "file_task"}},
                    {"id": "call-2", "function": {"name": "web_fetch"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "contents"},
        ]
        assert pair_unanswered_tool_calls(messages) == ["call-2"]

    def test_repair_carries_the_reason_it_was_needed(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-9", "function": {"name": "shell"}}],
            }
        ]
        pair_unanswered_tool_calls(messages, reason="the loop moved on")
        assert "the loop moved on" in messages[-1]["content"]


# ── 3. The loop wires both rules ─────────────────────────────────────────────


def _parent_config():
    """A parent-agent config: the only shape whose turns run the completion floor."""
    cfg = MagicMock()
    cfg.name = "parent"
    cfg.allowed_tools = None
    return cfg


def _drive_loop(dispatch_result, *, raise_with: Exception | None = None, parent: bool = False):
    """Run one tool call through the real loop and capture the second request.

    Returns (messages_of_the_second_model_call, all_sse_text). The fake model
    asks for `shell` once, then answers — so the second request's messages are
    exactly what the loop recorded about that call.
    """
    from adapters.ollama import ToolCallResult

    seen = {"calls": 0}
    requests: list[list[dict]] = []

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1
        requests.append([dict(m) for m in messages])
        if seen["calls"] == 1:
            return ToolCallResult(tool_name="shell", tool_args={"command": "rm -rf build"})

        async def _stream():
            yield StreamChunk(text="That call never reported back.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def dispatch(intent, tool_input, *a, **k):
        if raise_with is not None:
            raise raise_with
        return dispatch_result

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = lambda *a, **k: iter(())

    async def go():
        with patch("core.agent.loop.dispatch_with_retry", dispatch):
            return [
                c
                async for c in AgentLoop(adapter=MagicMock()).run(
                    messages=[{"role": "user", "content": "clear the build folder"}],
                    intent=Intent.SHELL,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=adapter,
                    obs=None,
                    skip_planning=True,
                    agent_config=_parent_config() if parent else None,
                )
            ]

    chunks = asyncio.run(go())
    return requests, "".join(c.text for c in chunks)


class TestLoopRecordsAnUnansweredCall:
    def test_dispatch_exception_is_recorded_as_unknown_outcome(self):
        requests, _ = _drive_loop(None, raise_with=RuntimeError("connection dropped"))
        assert len(requests) >= 2, "the loop must continue after the failed call"
        second = requests[1]
        tool_msgs = [m for m in second if m.get("role") == "tool"]
        assert tool_msgs, "the failed call must still produce a tool message"
        assert "OUTCOME UNKNOWN" in tool_msgs[-1]["content"]
        assert "connection dropped" in tool_msgs[-1]["content"]

    def test_exhausted_retries_are_recorded_as_unknown_outcome(self):
        requests, _ = _drive_loop((None, True, 2))
        second = requests[1]
        tool_msgs = [m for m in second if m.get("role") == "tool"]
        assert tool_msgs
        assert "OUTCOME UNKNOWN" in tool_msgs[-1]["content"]
        assert "no result after 2 retries" in tool_msgs[-1]["content"]

    def test_a_parent_floor_does_not_replan_the_turn_forever(self):
        # The completion floor re-asked the model on every iteration when the
        # action had failed and the model would not act again — 19 gate
        # replans on a single failed call, each one a full provider round trip.
        # The floor now spends the same bounded replan budget the criteria
        # path uses, so the turn closes honestly instead.
        requests, answer = _drive_loop(
            None, raise_with=RuntimeError("connection dropped"), parent=True
        )
        assert "completion floor" in answer, (
            "the floor path must be the one under test — otherwise this pins nothing: "
            f"{answer[:200]!r}"
        )
        assert len(requests) <= 5, f"the floor replanned {len(requests)} times"

    def test_every_emitted_call_is_paired_in_the_request(self):
        requests, _ = _drive_loop(
            (ToolResult(source="shell", content="build removed"), False, 0)
        )
        for request in requests:
            pending = set()
            for msg in request:
                for call in msg.get("tool_calls") or []:
                    pending.add(call.get("id"))
                if msg.get("role") == "tool":
                    pending.discard(msg.get("tool_call_id"))
            assert not pending, "a request carried an assistant tool call with no result"

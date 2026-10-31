"""What goes on the wire per role — and what a strict provider does with it.

Field failure (2026-10-31, Cerebras/qwen-3.8-27b): the whole turn was rejected
with

    messages.2.user.tool_calls: property 'messages.2.user.tool_calls' is unsupported

because the history carried ``tool_calls`` on a user turn (null, in this case).
Lenient OpenAI-compatible servers ignore the key; Cerebras validates per role
and refuses the entire request. The fix has two halves: never put the field on
a turn that cannot carry it, and treat "this provider refuses our payload" as
a reason to use another provider instead of dead-ending the chat.
"""

import json

import pytest
from adapters.failover import FailoverAdapter, ProviderHealth
from adapters.openai_compat import normalize_messages_for_wire
from core.error_normalizer import (
    CONTEXT_OVERFLOW,
    INVALID_REQUEST,
    normalize_error,
)
from core.models import StreamChunk

CEREBRAS_REJECTION = (
    "cerebras returned 400: "
    + json.dumps(
        {
            "message": (
                "messages.2.user.tool_calls: property "
                "'messages.2.user.tool_calls' is unsupported"
            ),
            "type": "invalid_request_error",
            "code": None,
        }
    )
)


# ── normalize_messages_for_wire ─────────────────────────────────────────────


def test_user_turn_loses_tool_calls_whether_null_or_populated():
    messages = [
        {"role": "user", "content": "recall the weather", "tool_calls": None},
        {"role": "assistant", "content": "looking"},
        {
            "role": "user",
            "content": "and then?",
            "tool_calls": [{"id": "tc-2", "type": "function", "function": {"name": "x"}}],
        },
    ]
    out = normalize_messages_for_wire(messages)
    assert all("tool_calls" not in m for m in out if m["role"] == "user")


def test_assistant_turn_keeps_a_real_tool_call():
    calls = [{"id": "tc-1", "type": "function", "function": {"name": "memory_op", "arguments": "{}"}}]
    out = normalize_messages_for_wire(
        [
            {"role": "assistant", "content": "", "tool_calls": calls},
            {"role": "assistant", "content": "plain reply", "tool_calls": None},
        ]
    )
    assert out[0]["tool_calls"] == calls
    # An assistant turn that called nothing carries no empty field either.
    assert "tool_calls" not in out[1]


def test_tool_result_keeps_its_call_id_and_never_a_tool_calls_field():
    out = normalize_messages_for_wire(
        [
            {"role": "tool", "tool_call_id": "tc-1", "content": "42"},
            {"role": "tool", "content": "no id"},
            {"role": "user", "content": "hi", "tool_call_id": "tc-9"},
        ]
    )
    assert out[0] == {"role": "tool", "tool_call_id": "tc-1", "content": "42"}
    assert "tool_call_id" not in out[1]
    assert "tool_call_id" not in out[2]


def test_other_fields_are_left_alone():
    name = {"role": "user", "name": "tison", "content": "hi"}
    assert normalize_messages_for_wire([name])[0] == name


# ── classification: a refused payload is not the conversation's fault ───────


def test_schema_rejection_classifies_as_invalid_request_not_retryable():
    normalized = normalize_error(CEREBRAS_REJECTION)
    assert normalized["code"] == INVALID_REQUEST
    assert normalized["retryable"] is False


def test_a_400_that_means_too_long_stays_context_overflow():
    """The stricter rules above must not steal the too-long case: a provider
    that reports context overflow with a 400 still gets the right verdict."""
    text = "zai returned 400: maximum context length exceeded, too many tokens"
    assert normalize_error(text)["code"] == CONTEXT_OVERFLOW


# ── failover: use another provider instead of ending the chat ──────────────


class Fake:
    def __init__(self, name, *, error=None, text="hello from "):
        self.name, self.error, self.text = name, error, text
        self.calls = 0

    async def chat(self, messages, temperature=0.7, **kw):
        self.calls += 1
        if self.error:
            yield StreamChunk(text="", error=self.error, done=True)
            return
        yield StreamChunk(text=self.text + self.name)
        yield StreamChunk(text="", done=True)

    async def chat_with_tools(self, messages, tools, temperature=0.7, intent="chat", tool_choice=None):
        return self.chat(messages)


def build(primary, others, health=None):
    adapters = {o.name: o for o in others}
    return FailoverAdapter(
        primary,
        primary.name,
        candidates=lambda _p: [(o.name, "") for o in others],
        make_adapter=lambda n, m: adapters[n],
        health=health or ProviderHealth(),
        retry_delays=(),
    )


async def drain(stream):
    return [c async for c in stream]


@pytest.mark.asyncio
async def test_a_provider_that_refuses_the_payload_is_switched_away_from():
    strict, lenient = Fake("cerebras", error=CEREBRAS_REJECTION), Fake("zen")
    health = ProviderHealth()
    out = await drain(await build(strict, [lenient], health=health).chat_with_tools([], []))
    assert [c.error for c in out if c.error] == []
    assert "".join(c.text for c in out) == "hello from zen"
    # And the strict provider is skipped for the next call this turn.
    assert health.is_down("cerebras")


@pytest.mark.asyncio
async def test_it_does_not_wait_out_a_refused_payload_before_moving_on():
    """Waiting cannot teach a validator to accept the field, so no countdown."""
    strict = Fake("cerebras", error=CEREBRAS_REJECTION)
    out = await drain(await build(strict, [], health=ProviderHealth()).chat_with_tools([], []))
    assert strict.calls == 1
    assert any(c.error for c in out)

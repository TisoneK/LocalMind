"""Parent bootstrap + fast public thinker.

Validates that the streaming initializer:
1. Emits a bounded model-owned acknowledgement BEFORE the full decision.
2. Emits a bounded understanding line in the ThinkingBlock channel.
3. Never exposes raw JSON envelope or chain-of-thought.
4. Still raises TerminalProviderError on terminal pre-generation errors.
5. Falls back to execute mode on unparsable output (fail-open).
6. Emits the final InitializationDecision as the last event.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from core.agent.init_stream import (
    InitializationPreview,
    extract_preview,
    render_understanding,
)
from core.agent.initialization import InitializationDecision, parse_initialization
from core.agent.loop import AgentLoop, TerminalProviderError
from core.models import StreamChunk


class _FakeAdapter:
    """Minimal adapter that yields canned chunks for the streaming initializer."""

    def __init__(self, chunks: list[str], error: str | None = None):
        self._chunks = chunks
        self._error = error

    async def chat(self, messages, temperature=0.1, intent="chat") -> AsyncIterator[StreamChunk]:
        for chunk_text in self._chunks:
            yield StreamChunk(text=chunk_text, done=False)
        if self._error:
            yield StreamChunk(text="", done=True, error=self._error)


def _make_loop() -> AgentLoop:
    """Build a minimal AgentLoop without touching the real engine."""
    loop = AgentLoop.__new__(AgentLoop)
    # AgentLoop methods we test don't touch instance state beyond what
    # _initialize_parent_streaming sets up locally.
    return loop


@pytest.mark.asyncio
async def test_streaming_initializer_emits_ack_before_decision():
    """The model's acknowledgement must surface before the final decision."""
    # A realistic init JSON that streams the acknowledgement first.
    json_chunks = [
        '{"mode": "execute", ',
        '"acknowledgement": "Let me check the time for you.", ',
        '"objective": "Get current time", ',
        '"confidence": 0.95}',
    ]
    adapter = _FakeAdapter(json_chunks)
    loop = _make_loop()

    events: list[tuple[str, object]] = []
    async for event_type, payload in loop._initialize_parent_streaming(
        active_adapter=adapter,
        messages=[{"role": "user", "content": "whats the time?"}],

        env_context="",
        intent_history=None,
    ):
        events.append((event_type, payload))

    # The acknowledgement must arrive before the decision.
    ack_idx = next(i for i, (t, _) in enumerate(events) if t == "ack")
    dec_idx = next(i for i, (t, _) in enumerate(events) if t == "decision")
    assert ack_idx < dec_idx, f"ack (idx {ack_idx}) must precede decision (idx {dec_idx})"

    ack_payload = events[ack_idx][1]
    assert isinstance(ack_payload, str)
    assert "time" in ack_payload.lower()
    assert len(ack_payload) <= 600  # bounded

    decision = events[dec_idx][1]
    assert isinstance(decision, InitializationDecision)
    assert decision.mode == "execute"
    assert decision.objective == "Get current time"


@pytest.mark.asyncio
async def test_streaming_initializer_never_exposes_raw_json():
    """Raw JSON envelope and chain-of-thought must never appear in events."""
    json_chunks = [
        '{"mode": "direct", ',
        '"acknowledgement": "Hi there!", ',
        '"response": "Hello — what can I do for you?", ',
        '"confidence": 0.9}',
    ]
    adapter = _FakeAdapter(json_chunks)
    loop = _make_loop()

    raw_outputs: list[str] = []
    async for event_type, payload in loop._initialize_parent_streaming(
        active_adapter=adapter,
        messages=[{"role": "user", "content": "hey"}],

        env_context="",
        intent_history=None,
    ):
        if isinstance(payload, str):
            raw_outputs.append(payload)
        elif isinstance(payload, InitializationDecision):
            # The decision object is internal; its .raw field is bounded and
            # never streamed to the user.  We only check string payloads here.
            pass

    # No event payload may contain raw JSON braces or field names.
    for output in raw_outputs:
        assert "{" not in output, f"raw JSON leaked into stream: {output!r}"
        assert "}" not in output, f"raw JSON leaked into stream: {output!r}"
        assert '"mode"' not in output, f"schema field leaked: {output!r}"
        assert '"acknowledgement"' not in output, f"schema field leaked: {output!r}"


@pytest.mark.asyncio
async def test_streaming_initializer_terminal_error_propagates():
    """A terminal pre-generation provider error must raise TerminalProviderError."""
    # The error arrives AFTER some chunks — the producer must still raise.
    adapter = _FakeAdapter(
        chunks=['{"mode": "execute", "acknowledgement": "Working on it"'],
        error="HTTP 401 Unauthorized: invalid API key",
    )
    loop = _make_loop()

    with pytest.raises(TerminalProviderError, match="401"):
        async for _event_type, _payload in loop._initialize_parent_streaming(
            active_adapter=adapter,
            messages=[{"role": "user", "content": "hi"}],

            env_context="",
            intent_history=None,
        ):
            pass  # drain until the error raises


@pytest.mark.asyncio
async def test_streaming_initializer_resolves_prose_to_direct():
    """Unparsable model output resolves to a bounded DIRECT
    answer (execute is opt-in) — a model that replied in prose has that prose
    shown as the answer instead of being dragged into the tool loop."""
    adapter = _FakeAdapter(chunks=["This is not JSON at all, just prose."])
    loop = _make_loop()

    decision: InitializationDecision | None = None
    async for event_type, payload in loop._initialize_parent_streaming(
        active_adapter=adapter,
        messages=[{"role": "user", "content": "do something"}],

        env_context="",
        intent_history=None,
    ):
        if event_type == "decision":
            decision = payload

    assert decision is not None
    assert decision.mode == "direct"
    assert decision.response == "This is not JSON at all, just prose."


@pytest.mark.asyncio
async def test_streaming_initializer_non_terminal_error_does_not_hang():
    """A non-terminal adapter error (e.g. transient 503) must NOT hang the
    consumer.  The producer must put a fail-open decision event so the
    parent loop can retry or surface a clean error."""
    adapter = _FakeAdapter(
        chunks=['{"mode": "execute", "acknowledgement": "Working on it"'],
        error="zen returned 503: Service Unavailable",  # non-terminal
    )
    loop = _make_loop()

    # This must complete (not hang) and produce a decision.
    decision: InitializationDecision | None = None
    async for event_type, payload in loop._initialize_parent_streaming(
        active_adapter=adapter,
        messages=[{"role": "user", "content": "hi"}],

        env_context="",
        intent_history=None,
    ):
        if event_type == "decision":
            decision = payload

    assert decision is not None, "consumer hung — no decision event was put on the queue"
    # A truncated/errored init is not a parseable execute choice,
    # so it resolves to a bounded direct answer, never the tool loop.
    assert decision.mode == "direct"


@pytest.mark.asyncio
async def test_streaming_initializer_empty_stream_does_not_hang():
    """If the adapter yields zero chunks and no error, the consumer must
    still unblock with a fail-open decision."""
    adapter = _FakeAdapter(chunks=[])
    loop = _make_loop()

    decision: InitializationDecision | None = None
    async for event_type, payload in loop._initialize_parent_streaming(
        active_adapter=adapter,
        messages=[{"role": "user", "content": "hi"}],

        env_context="",
        intent_history=None,
    ):
        if event_type == "decision":
            decision = payload

    assert decision is not None, "consumer hung on empty stream"
    # Empty stream → bounded direct answer, never the tool loop.
    assert decision.mode == "direct"
    assert decision.response  # a non-empty fallback so the turn completes


@pytest.mark.asyncio
async def test_streaming_initializer_emits_understanding_for_execute_mode():
    """Execute mode must surface the objective as a bounded thinker line."""
    json_chunks = [
        '{"mode": "execute", ',
        '"acknowledgement": "On it.", ',
        '"objective": "Read the file and summarize its contents", ',
        '"confidence": 0.8}',
    ]
    adapter = _FakeAdapter(json_chunks)
    loop = _make_loop()

    understanding: str | None = None
    async for event_type, payload in loop._initialize_parent_streaming(
        active_adapter=adapter,
        messages=[{"role": "user", "content": "summarize foo.py"}],

        env_context="",
        intent_history=None,
    ):
        if event_type == "understanding":
            understanding = payload

    assert understanding is not None
    assert "Read the file" in understanding
    assert len(understanding) <= 600


@pytest.mark.asyncio
async def test_streaming_initializer_emits_understanding_for_clarify_mode():
    """Clarify mode must surface the clarifying question as the thinker line."""
    json_chunks = [
        '{"mode": "clarify", ',
        '"acknowledgement": "I need a detail.", ',
        '"clarifying_question": "Which file do you mean?", ',
        '"confidence": 0.7}',
    ]
    adapter = _FakeAdapter(json_chunks)
    loop = _make_loop()

    events: list[tuple[str, object]] = []
    async for event_type, payload in loop._initialize_parent_streaming(
        active_adapter=adapter,
        messages=[{"role": "user", "content": "summarize the file"}],

        env_context="",
        intent_history=None,
    ):
        events.append((event_type, payload))

    understanding_events = [p for t, p in events if t == "understanding"]
    assert len(understanding_events) == 1
    assert "Which file" in understanding_events[0]


@pytest.mark.asyncio
async def test_streaming_initializer_emits_each_event_at_most_once():
    """Ack and understanding are emitted at most once per turn, even if the
    field grows as the JSON streams in."""
    # The acknowledgement field grows across chunks: "Let me" → "Let me check".
    # Only ONE ack event should fire.
    json_chunks = [
        '{"acknowledgement": "Let me", ',
        '"acknowledgement_extra": "ignore", ',  # noise
        '"objective": "check", ',
        '"mode": "execute", ',
        '"confidence": 0.5}',
    ]
    adapter = _FakeAdapter(json_chunks)
    loop = _make_loop()

    ack_count = 0
    understanding_count = 0
    async for event_type, _payload in loop._initialize_parent_streaming(
        active_adapter=adapter,
        messages=[{"role": "user", "content": "test"}],

        env_context="",
        intent_history=None,
    ):
        if event_type == "ack":
            ack_count += 1
        elif event_type == "understanding":
            understanding_count += 1

    assert ack_count == 1, f"expected exactly 1 ack, got {ack_count}"
    assert understanding_count <= 1, f"expected at most 1 understanding, got {understanding_count}"


# ── Unit tests for init_stream helpers ──────────────────────────────────────


def test_extract_preview_finds_acknowledgement_in_partial_json():
    """The preview extractor must find a string field once its closing quote
    arrives.  During streaming, the ack is emitted as soon as the full string
    value is parseable — typically within 1-2 tokens of the opening quote."""
    # Complete string value (closing quote present) — matches immediately.
    preview = extract_preview('{"mode": "execute", "acknowledgement": "On it."')
    assert preview.acknowledgement == "On it."
    assert preview.mode == "execute"
    # Partial string value (no closing quote yet) — does NOT match, because
    # we cannot safely bound a value that is still being streamed.  The ack
    # fires on the next chunk once the closing quote arrives.
    partial = extract_preview('{"mode": "execute", "acknowledgement": "On it.')
    assert partial.acknowledgement == ""
    assert partial.mode == "execute"  # mode is a complete token, still matches


def test_extract_preview_returns_empty_for_no_match():
    preview = extract_preview("not json at all")
    assert preview.acknowledgement == ""
    assert preview.objective == ""


def test_extract_preview_decodes_json_escapes():
    """Newlines and quotes inside JSON strings must be decoded."""
    preview = extract_preview(r'{"acknowledgement": "Line1\nLine2 \"quoted\""}')
    assert "Line1" in preview.acknowledgement
    assert "Line2" in preview.acknowledgement
    assert '"quoted"' in preview.acknowledgement


def test_extract_preview_caps_long_fields():
    """A runaway field must be capped to _PREVIEW_CAP chars."""
    long_value = "x" * 5000
    preview = extract_preview(f'{{"acknowledgement": "{long_value}"}}')
    assert len(preview.acknowledgement) <= 600


def test_render_understanding_prefers_objective():
    preview = InitializationPreview(
        objective="Get the current time",
        acknowledgement="On it",
    )
    line = render_understanding(preview)
    assert "Get the current time" in line
    # Acknowledgement is separate; understanding line is the objective only.
    assert "On it" not in line


def test_render_understanding_uses_clarifying_question_when_no_objective():
    preview = InitializationPreview(clarifying_question="Which file?")
    line = render_understanding(preview)
    assert "Which file?" in line


def test_render_understanding_never_surfaces_the_response():
    """Session 224 regression: the thinker must show the model's reasoning
    (objective), never the answer. Surfacing `response` here made the
    "thought process" identical to the final answer (bug report: same blob
    in the ThinkingBlock and the workspace card) and exposed the answer as
    chain-of-thought, which ADR-34 forbids. A direct reply with only a
    response yields an empty understanding line."""
    preview = InitializationPreview(mode="direct", response="Hello there, how can I help?")
    assert render_understanding(preview) == ""
    # But a genuine objective (the model's reasoning) is still surfaced.
    preview_with_reasoning = InitializationPreview(
        mode="direct",
        objective="User is greeting me and wants a warm, brief reply",
        response="Hey! Doing great — how can I help?",
    )
    line = render_understanding(preview_with_reasoning)
    assert "greeting" in line
    assert "how can I help" not in line  # the answer must not leak in


def test_preview_diff_detects_new_fields_only():
    """diff() returns only fields that changed AND are non-empty."""
    old = InitializationPreview()
    new = InitializationPreview(acknowledgement="Hi", objective="Read file")
    diff = old.diff(new)
    assert "acknowledgement" in diff
    assert "objective" in diff
    assert diff["acknowledgement"] == "Hi"
    assert diff["objective"] == "Read file"


def test_preview_diff_ignores_unchanged_fields():
    old = InitializationPreview(acknowledgement="Hi", objective="Read")
    new = InitializationPreview(acknowledgement="Hi", objective="Read")
    assert old.diff(new) == {}


def test_preview_diff_ignores_empty_new_values():
    old = InitializationPreview(acknowledgement="Hi")
    new = InitializationPreview()  # all empty
    assert old.diff(new) == {}


# ── Legacy init fields (ADR-38 Step 1) ─────────────────────────────────


def test_parse_initialization_ignores_legacy_fields():
    """facts/ambiguities/tool_names remain DELETED from the contract; the legacy
    `plan_steps` KEY is also ignored. ADR-49: only the new `plan` key is parsed
    (tested separately) — this input carries none, so plan_steps stays empty."""
    text = (
        '{"mode": "execute", "acknowledgement": "On it.", '
        '"objective": "List projects", '
        '"facts": ["target is the dev folder", "platform is windows"], '
        '"ambiguities": ["folder may not exist"], '
        '"tool_names": ["shell"], '
        '"plan_steps": ["list the directory"], "confidence": 0.8}'
    )
    decision = parse_initialization(text)
    assert decision.objective == "List projects"
    assert not hasattr(decision, "facts")
    assert not hasattr(decision, "ambiguities")
    assert not hasattr(decision, "tool_names")
    # plan_steps is a real field now but the legacy `plan_steps` KEY is
    # NOT its source — only `plan` is — so it stays empty here.
    assert decision.plan_steps == []
    assert decision.objective_line() == "UNDERSTANDING: List projects"

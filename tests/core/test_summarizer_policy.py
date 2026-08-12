"""ADR-19 task-aware summarizer tests (Session 162).

`maybe_compress_history(..., policy=...)`:
  - policy=None / default → the original generic summary (byte-identical
    prompt, no preserved block) — wiring no-op.
  - a real policy → task-specific summary prompt + decision-relevant lines
    (matching keep_markers) preserved VERBATIM in a [Preserved decisions]
    block, so the PostgreSQL/MongoDB lossy-compression case survives.
  - all failure semantics preserved: adapter error → unchanged list.
"""

from __future__ import annotations

import pytest
from core.context_policy import policy_for
from core.models import StreamChunk
from core.summarizer import _preserved_decision_lines, maybe_compress_history


class _FakeAdapter:
    """Adapter that records the prompt and returns a canned summary."""

    def __init__(self, summary: str = "Canned summary text."):
        self.summary = summary
        self.last_messages = None

    async def chat(self, messages, temperature=0.2):
        # Async-generator form (matches the adapter contract the summarizer
        # uses: `async for chunk in adapter.chat(...)` with no await).
        self.last_messages = messages
        yield StreamChunk(text=self.summary, done=False)
        yield StreamChunk(text="", done=True)


def _msgs(system: bool = True) -> list[dict]:
    """A message list over the 75% threshold with 10 conversation messages."""
    msgs = []
    if system:
        msgs.append({"role": "system", "content": "SYS"})
    for i in range(10):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"message {i} " + "y" * 200})
    return msgs


# ── 1. Legacy no-op ──────────────────────────────────────────────────────────


# Token budget chosen so _msgs() (≈570 rough tokens) exceeds the 75%
# threshold (500*0.75=375) and compression actually fires.
_BUDGET = 500


@pytest.mark.asyncio
async def test_none_policy_uses_generic_prompt():
    adapter = _FakeAdapter()
    await maybe_compress_history(_msgs(), adapter, token_budget=_BUDGET)
    system_prompt = adapter.last_messages[0]["content"]
    assert "conversation summarizer" in system_prompt
    # No preserved-decisions block requested (no policy).
    assert "Preserved decisions" not in system_prompt


@pytest.mark.asyncio
async def test_default_policy_identical_to_none():
    adapter_none = _FakeAdapter()
    adapter_default = _FakeAdapter()
    await maybe_compress_history(_msgs(), adapter_none, token_budget=_BUDGET)
    await maybe_compress_history(_msgs(), adapter_default, token_budget=_BUDGET, policy=policy_for(None))
    assert adapter_none.last_messages == adapter_default.last_messages


# ── 2. Task-aware prompt + preserved decisions ──────────────────────────────


@pytest.mark.asyncio
async def test_policy_uses_task_specific_prompt():
    adapter = _FakeAdapter()
    await maybe_compress_history(
        _msgs(), adapter, token_budget=_BUDGET, policy=policy_for("debug")
    )
    system_prompt = adapter.last_messages[0]["content"]
    assert "PRESERVING verbatim" in system_prompt  # debug-specific prompt


def test_preserved_decision_lines_keep_constraints_verbatim():
    """The user's lossy-compression example: rejected options survive."""
    excerpt = (
        "USER: I want PostgreSQL for the backend\n"
        "USER: Actually rejected MongoDB, we don't need it\n"
        "USER: For local mode use SQLite\n"
        "USER: Production uses PostgreSQL\n"
        "ASSISTANT: ok\n"
    )
    kept = _preserved_decision_lines(excerpt, policy_for("plan"))
    joined = "\n".join(kept)
    # 'rejected' line survived verbatim.
    assert any("rejected MongoDB" in line for line in kept)
    # 'production uses' line survived.
    assert any("Production uses PostgreSQL" in line for line in kept)
    assert "ASSISTANT: ok" not in joined


def test_preserved_lines_bounded():
    excerpt = "\n".join(f"must not do thing {i}" for i in range(50))
    kept = _preserved_decision_lines(excerpt, policy_for("plan"))
    assert len(kept) <= 8
    total = sum(len(line) for line in kept)
    assert total <= 1200


def test_preserved_line_length_trimmed():
    long_line = "must not use this " + "z" * 1_000
    kept = _preserved_decision_lines(long_line, policy_for("plan"))
    assert len(kept) == 1
    assert len(kept[0]) <= 200


def test_preserved_matching_is_case_insensitive():
    excerpt = "USER: REJECTED the old plan\n"
    kept = _preserved_decision_lines(excerpt, policy_for("plan"))
    assert any("REJECTED" in line for line in kept)


def test_no_policy_no_preserved_lines():
    assert _preserved_decision_lines("must not lose this", policy_for(None)) == []


def test_preserved_line_survives_past_500_char_truncation():
    """Session 162 review fix: preserved extraction reads the RAW content,
    so a decision line past the 500-char excerpt cut still survives."""
    raw = "y" * 600 + "\nuser rejected MongoDB for compliance\n" + "z" * 200
    kept = _preserved_decision_lines(raw, policy_for("plan"))
    assert any("rejected MongoDB" in line for line in kept)


@pytest.mark.asyncio
async def test_summary_message_contains_preserved_block():
    # Build an excerpt with decision lines so the preserved block appears.
    adapter = _FakeAdapter()
    msgs = _msgs()
    msgs[1] = {"role": "user", "content": "must not use cloud, production uses postgres"}
    result = await maybe_compress_history(
        msgs, adapter, token_budget=_BUDGET, policy=policy_for("plan")
    )
    summary_msg = result[1] if result[0]["role"] == "system" else result[0]
    assert summary_msg["role"] == "system"
    assert "Preserved decisions" in summary_msg["content"]


# ── 3. Failure semantics preserved ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_adapter_error_returns_unchanged():
    class _BrokenAdapter:
        async def chat(self, messages, temperature=0.2):
            raise RuntimeError("provider down")
            yield  # pragma: no cover

    original = _msgs()
    result = await maybe_compress_history(
        original, _BrokenAdapter(), token_budget=1_000, policy=policy_for("debug")
    )
    assert result == original


@pytest.mark.asyncio
async def test_empty_summary_returns_unchanged():
    adapter = _FakeAdapter(summary="")
    original = _msgs()
    result = await maybe_compress_history(
        original, adapter, token_budget=1_000, policy=policy_for("debug")
    )
    assert result == original


@pytest.mark.asyncio
async def test_below_threshold_no_adapter_call():
    adapter = _FakeAdapter()
    small = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = await maybe_compress_history(
        small, adapter, token_budget=1_000_000, policy=policy_for("debug")
    )
    assert result == small
    assert adapter.last_messages is None

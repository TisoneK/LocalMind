"""Roadmap §U item 1 — the provider-death completion path.

Live lesson (2026-10-27 12:45): the answer was already in evidence
(web_search + web_fetch succeeded) when the provider died at synthesis with
payment_required — balance=0, retryable=False, both known at error time.
The retryable-only evidence gate threw the completed evidence run away, and
the user was told "please try again, or switch to a larger model" —
known-dead advice on both counts, with the provider rendered as "unknown".

Contract under test:
  1. A terminal provider death AFTER successful tool work delivers what the
     evidence supports, framed honestly (provider named, code verbatim,
     "as gathered" said plainly).
  2. The final chunk carries the error so the audit record keeps the
     failure and the honest card (provider named, no try-again) still shows.
  3. With no evidence in hand, the dead-end message names the provider and
     the code and never suggests retrying a non-retryable failure.
  4. A retryable rate-limit death keeps the existing degraded behavior:
     extraction without terminal framing, no error on the final chunk.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk, ToolResult
from core.obs import ObsCollector

DEATH_RAW = (
    "BankOfAI (promo free models — time-limited) returned 400: "
    '{"error":{"message":"credit insufficient balance: balance=0 '
    'required=5196 (request id: 2026102709455742)"}}'
)

RATE_LIMIT_RAW = "zen returned 429: rate limit exceeded, retry later"

EVIDENCE = (
    "MSN Weather: Kiambu Town — 25°C, partly sunny, wind 11 km/h, humidity 40%."
)

THINKING = (
    "The user asked about the weather where they are. "
    "Kiambu Town is 25°C and partly sunny with light winds."
)


def _adapter_streaming(*chunks: StreamChunk) -> MagicMock:
    seen = {"calls": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["calls"] += 1

        async def _stream():
            for c in chunks:
                yield c

        return _stream()

    mock = MagicMock()
    mock.chat_with_tools = chat_with_tools
    mock.seen = seen
    return mock


async def _run(mock_adapter, *, evidence: ToolResult | None, obs: ObsCollector):
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        return [
            chunk
            async for chunk in AgentLoop(adapter=MagicMock()).run(
                messages=[{"role": "user", "content": "what's the weather where I am"}],
                intent=Intent.WEB_SEARCH,
                initial_tool_result=evidence,
                available_tools=[],
                adapter=mock_adapter,
                obs=obs,
                skip_planning=True,
            )
        ]


class TestTerminalProviderDeathDeliversEvidence:
    @pytest.mark.asyncio
    async def test_death_after_evidence_delivers_it_framed_honestly(self):
        obs = ObsCollector()
        adapter = _adapter_streaming(
            StreamChunk(text="", done=False, thinking=THINKING),
            StreamChunk(text="", done=True, error=DEATH_RAW),
        )
        chunks = await _run(
            adapter,
            evidence=ToolResult(content=EVIDENCE, source="web_search", success=True),
            obs=obs,
        )
        full = "".join(c.text for c in chunks)
        # The provider is NAMED (never "unknown"), the code is verbatim, and
        # the answer's provenance ("as gathered") is said plainly.
        assert "BankOfAI (promo free models — time-limited)" in full
        assert "payment_required" in full
        assert "as gathered" in full
        # The evidence itself reached the user.
        assert "25°C" in full
        # Known-dead advice must not appear.
        assert "try again" not in full.lower()
        assert "larger model" not in full.lower()
        # The final chunk carries the error: the audit record keeps the
        # failure and the honest card (no try-again) still shows.
        final = chunks[-1]
        assert final.done is True
        assert final.error, "terminal death must ride the final chunk"
        # The degraded observation names the death as terminal, with provider.
        degraded = [e for e in obs.history() if e.type == "agent_loop_degraded"]
        assert degraded, "agent_loop_degraded must be emitted"
        assert any(getattr(e, "data", {}).get("terminal") is True for e in degraded)
        assert any(
            "BankOfAI" in str(getattr(e, "data", {}).get("provider") or "") for e in degraded
        )

    @pytest.mark.asyncio
    async def test_terminal_death_without_extractable_answer_still_says_the_truth(self):
        obs = ObsCollector()
        adapter = _adapter_streaming(
            StreamChunk(text="", done=True, error=DEATH_RAW),
        )
        chunks = await _run(
            adapter,
            evidence=ToolResult(content=EVIDENCE, source="web_search", success=True),
            obs=obs,
        )
        full = "".join(c.text for c in chunks)
        assert "payment_required" in full
        assert "BankOfAI" in full
        assert "try again" not in full.lower()
        assert chunks[-1].error


class TestTerminalProviderDeathWithoutEvidence:
    @pytest.mark.asyncio
    async def test_dead_end_names_provider_and_code_never_suggests_retry(self):
        obs = ObsCollector()
        adapter = _adapter_streaming(StreamChunk(text="", done=True, error=DEATH_RAW))
        chunks = await _run(adapter, evidence=None, obs=obs)
        full = "".join(c.text for c in chunks)
        assert "BankOfAI (promo free models — time-limited)" in full
        assert "payment_required" in full
        assert "not retryable" in full
        assert "try again" not in full.lower()
        assert "larger model" not in full.lower()
        assert chunks[-1].error
        assert any(e.type == "agent_loop_error" for e in obs.history())


class TestRetryableDeathKeepsExistingBehavior:
    @pytest.mark.asyncio
    async def test_rate_limit_extraction_has_no_terminal_framing_or_error(self):
        obs = ObsCollector()
        adapter = _adapter_streaming(
            StreamChunk(text="", done=False, thinking=THINKING),
            StreamChunk(text="", done=True, error=RATE_LIMIT_RAW),
        )
        chunks = await _run(
            adapter,
            evidence=ToolResult(content=EVIDENCE, source="web_search", success=True),
            obs=obs,
        )
        full = "".join(c.text for c in chunks)
        assert "25°C" in full, "extraction should still rescue the answer"
        assert "payment_required" not in full
        assert chunks[-1].done is True
        assert not chunks[-1].error, "retryable rescue must not carry the error"
        degraded = [e for e in obs.history() if e.type == "agent_loop_degraded"]
        assert degraded
        assert all(not getattr(e, "data", {}).get("terminal") for e in degraded)

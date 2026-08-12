"""ADR-20/21 audit (Session 172) — WorkspaceOrchestrator fallback text must
never embed a raw provider payload.

The outer ``except`` in ``run()`` can catch an ADAPTER exception from
``_synthesise``/``_plan`` (provider-shaped — e.g. ``zen returned 429:
{...}``) or a tool exception re-raised from ``_dispatch_loop``. The bubble
text must carry the canonical friendly/cleaned message, while the raw error
rides ``chunk.error`` so the SSE boundary emits the canonical error card.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.obs import ObsCollector
from core.workspace.orchestrator import WorkspaceOrchestrator

# The exact provider payload the user saw dumped in the bubble.
ZEN_429 = (
    'zen returned 429: {"type":"error","error":{"type":"FreeUsageLimitError",'
    '"message":"Error from provider (Console): Rate limit exceeded. '
    'Please try again later."}}'
)


def _raise_chat(error_text: str):
    """Build an async-generator adapter.chat that raises at iteration time."""

    async def chat(messages, temperature=0.0, **kwargs):
        raise RuntimeError(error_text)
        yield  # pragma: no cover — makes this an async generator

    return chat


async def _run_orchestrator(error_text: str, session_id: str) -> list:
    mock_adapter = MagicMock()
    mock_adapter.chat = _raise_chat(error_text)
    orch = WorkspaceOrchestrator(adapter=mock_adapter)
    return [
        c
        async for c in orch.run(
            message="what is the meaning of life",
            session_id=session_id,
            memory_facts=[],
            obs=ObsCollector(),
        )
    ]


@pytest.mark.asyncio
async def test_orchestrator_fatal_adapter_error_never_leaks_raw_json():
    """A provider-shaped adapter exception in synthesis must not embed the raw
    payload in the bubble text — friendly message in text, raw on chunk.error
    so the SSE boundary emits the canonical error card (Session 172)."""
    chunks = await _run_orchestrator(ZEN_429, "sess-orch-audit")

    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    # Raw provider payload must never reach the bubble text.
    assert "zen returned" not in text.lower()
    assert "FreeUsageLimitError" not in text
    assert "{" not in text
    # The canonical friendly message is embedded instead.
    assert "usage limit" in text.lower()
    # The raw error is forwarded so the SSE boundary emits the error card.
    err_chunks = [c for c in chunks if getattr(c, "error", None)]
    assert err_chunks and ZEN_429 in err_chunks[0].error
    assert any(getattr(c, "done", False) for c in chunks)


@pytest.mark.asyncio
async def test_orchestrator_fatal_tool_exception_stays_cleaned():
    """A generic (non-provider) exception still surfaces — cleaned, not
    swallowed, and never as raw provider JSON (Session 172)."""
    chunks = await _run_orchestrator("boom: disk full", "sess-orch-audit2")

    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "boom" in text.lower()
    err_chunks = [c for c in chunks if getattr(c, "error", None)]
    assert err_chunks and "boom: disk full" in err_chunks[0].error
    assert any(getattr(c, "done", False) for c in chunks)


@pytest.mark.asyncio
async def test_orchestrator_plan_exception_falls_through_to_synthesis_error():
    """A provider-shaped exception during PLANNING is caught by _plan (empty
    tasks) and re-surfaces via the synthesis adapter error — the outer
    normalization still keeps the raw payload out of the text."""
    chunks = await _run_orchestrator(ZEN_429, "sess-orch-audit3")

    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "zen returned" not in text.lower()
    err_chunks = [c for c in chunks if getattr(c, "error", None)]
    assert err_chunks and ZEN_429 in err_chunks[0].error

"""P0 Step 4 (slice 2) — the search_tool_results retrieval tool.

Hermetic: the hybrid index and the session contextvar are monkeypatched, so
these pin the tool's contract (arg parsing, session scoping, formatting, and
the honest no-match / bad-input paths) without a DB or Ollama.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("LOCALMIND_HOME", ".")

import tools.search_tool_results as sr
from storage.tool_result_index import ResultChunk


class _FakeIndex:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls: list[dict] = []

    async def search(self, queries, *, tool_name=None, session_id=None, result_id=None, limit=8):
        self.calls.append(
            {
                "queries": queries,
                "tool_name": tool_name,
                "session_id": session_id,
                "result_id": result_id,
                "limit": limit,
            }
        )
        return list(self._chunks)[:limit]


def _chunk(text, result_id="web_fetch-abc123", ix=0, tool="web_fetch", sources=("bm25", "vec")):
    return ResultChunk(
        chunk_id=ix + 1,
        result_id=result_id,
        session_id="s1",
        tool_name=tool,
        chunk_ix=ix,
        text=text,
        score=1.0,
        sources=tuple(sources),
    )


def _wire(monkeypatch, index, session="s1"):
    monkeypatch.setattr(sr, "get_tool_result_index", lambda: index)
    monkeypatch.setattr(sr, "current_session_id", lambda: session)


@pytest.mark.asyncio
async def test_missing_query_is_invalid_input(monkeypatch):
    _wire(monkeypatch, _FakeIndex([]))
    res = await sr.search_tool_results("{}")
    assert res.success is False and res.error_type == "invalid_input"


@pytest.mark.asyncio
async def test_plain_string_is_used_as_query(monkeypatch):
    idx = _FakeIndex([_chunk("the answer lives here")])
    _wire(monkeypatch, idx)
    res = await sr.search_tool_results("connection pool")
    assert res.success is not False
    assert idx.calls[0]["queries"] == "connection pool"
    assert idx.calls[0]["session_id"] == "s1"  # scoped to the current session


@pytest.mark.asyncio
async def test_no_match_is_honest_success(monkeypatch):
    _wire(monkeypatch, _FakeIndex([]))
    res = await sr.search_tool_results(json.dumps({"query": "nope", "result_id": "x-1"}))
    # "no match" must be success=True so the loop doesn't count it as a failure.
    assert res.success is not False
    assert "No stored tool-result chunks" in res.content
    assert res.metadata["returned"] == 0


@pytest.mark.asyncio
async def test_results_are_formatted_and_scoped(monkeypatch):
    idx = _FakeIndex([_chunk("ROOT CAUSE: the socket timed out", ix=2)])
    _wire(monkeypatch, idx)
    res = await sr.search_tool_results(
        json.dumps({"query": "root cause", "result_id": "web_fetch-abc123", "tool_name": "web_fetch"})
    )
    assert "ROOT CAUSE: the socket timed out" in res.content
    assert "web_fetch-abc123#2" in res.content
    assert res.metadata["returned"] == 1
    call = idx.calls[0]
    assert call["result_id"] == "web_fetch-abc123" and call["tool_name"] == "web_fetch"


@pytest.mark.asyncio
async def test_limit_is_clamped(monkeypatch):
    idx = _FakeIndex([_chunk("c", ix=i) for i in range(50)])
    _wire(monkeypatch, idx)
    await sr.search_tool_results(json.dumps({"query": "c", "limit": 999}))
    assert idx.calls[0]["limit"] == sr._HARD_LIMIT


@pytest.mark.asyncio
async def test_per_chunk_and_total_output_is_bounded(monkeypatch):
    huge = "x" * 50_000
    idx = _FakeIndex([_chunk(huge, ix=i) for i in range(6)])
    _wire(monkeypatch, idx)
    res = await sr.search_tool_results(json.dumps({"query": "x"}))
    # Neither a single chunk nor the whole reply may re-flood the context.
    assert len(res.content) < sr._TOTAL_CHAR_CAP + sr._CHUNK_CHAR_CAP + 2000

"""P0 Step 4 (slice 2) — the agent-loop carried-observation transform.

Pins `_carry_observation`: a LARGE tool result is indexed and carried as a
bounded head + retrieval pointer (and `search_tool_results` is marked loaded);
a small result is returned unchanged (the call site's fallback); an indexing
failure degrades to the fallback (correctness over savings).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("LOCALMIND_HOME", ".")

from core.agent import loop
from storage.tool_result_index import INDEX_THRESHOLD_BYTES

_BIG = "y" * (INDEX_THRESHOLD_BYTES + 500)
_SMALL = "small result"


class _FakeIndex:
    def __init__(self, exc: Exception | None = None, n_chunks: int = 3):
        self.indexed: list[tuple[str, int]] = []
        self._exc = exc
        self._n = n_chunks

    async def index_result(self, content, *, session_id="", tool_name="", result_id=None, force=False):
        if self._exc:
            raise self._exc
        self.indexed.append((tool_name, len(content)))
        return (f"{tool_name or 'tool'}-fakeid", self._n)


@pytest.mark.asyncio
async def test_small_result_returns_fallback_unchanged(monkeypatch):
    idx = _FakeIndex()
    monkeypatch.setattr(loop, "get_tool_result_index", lambda: idx)
    loaded: set[str] = set()
    out = await loop._carry_observation(_SMALL, "shell", "s1", loaded, fallback="FB")
    assert out == "FB"  # under threshold → the call site's existing carried form
    assert idx.indexed == [] and loaded == set()


@pytest.mark.asyncio
async def test_large_result_is_indexed_and_pointerized(monkeypatch):
    idx = _FakeIndex()
    monkeypatch.setattr(loop, "get_tool_result_index", lambda: idx)
    loaded: set[str] = set()
    out = await loop._carry_observation(_BIG, "web_fetch", "s1", loaded, fallback="FB")
    assert out != "FB"
    assert "web_fetch-fakeid" in out
    assert "search_tool_results" in out
    assert "stored — id=" in out
    assert f"{len(_BIG):,}" in out  # names the full size
    # The head is bounded, so the carried form is far smaller than the payload.
    assert len(out) < len(_BIG)
    assert idx.indexed == [("web_fetch", len(_BIG))]
    assert "search_tool_results" in loaded  # schema loaded this run


@pytest.mark.asyncio
async def test_search_tool_results_output_is_never_indexed(monkeypatch):
    """A retrieval result must not be re-indexed (else the model chases nested
    pointers into its own searches)."""
    idx = _FakeIndex()
    monkeypatch.setattr(loop, "get_tool_result_index", lambda: idx)
    loaded: set[str] = set()
    out = await loop._carry_observation(_BIG, "search_tool_results", "s1", loaded, fallback="FB")
    assert out == "FB" and idx.indexed == [] and loaded == set()


@pytest.mark.asyncio
async def test_indexing_failure_degrades_to_fallback(monkeypatch):
    idx = _FakeIndex(exc=RuntimeError("db down"))
    monkeypatch.setattr(loop, "get_tool_result_index", lambda: idx)
    loaded: set[str] = set()
    out = await loop._carry_observation(_BIG, "web_fetch", "s1", loaded, fallback="FB")
    assert out == "FB"  # a failed index must never corrupt/drop the turn
    assert loaded == set()


@pytest.mark.asyncio
async def test_zero_chunks_degrades_to_fallback(monkeypatch):
    idx = _FakeIndex(n_chunks=0)
    monkeypatch.setattr(loop, "get_tool_result_index", lambda: idx)
    loaded: set[str] = set()
    out = await loop._carry_observation(_BIG, "web_fetch", "s1", loaded, fallback="FB")
    assert out == "FB"
    assert loaded == set()

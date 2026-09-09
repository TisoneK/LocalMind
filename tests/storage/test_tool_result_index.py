"""P0 Step 4 (slice 1) — the Tool-Result Index storage engine.

These pin the hybrid FTS5 (porter + trigram) + vec0 store: chunking, keyword /
substring / semantic retrieval, filters, rank fusion, the >5 KB gate, and
clear. They are hermetic — `_embed_async` is monkeypatched so nothing depends on
a running Ollama: the FTS-only tests force embeddings off, and the vec test
supplies a tiny deterministic embedder.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("LOCALMIND_HOME", ".")

import storage.tool_result_index as tri
from storage.tool_result_index import (
    ToolResultIndex,
    _chunk_text,
    _fts_match,
    _result_id,
)

# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_chunk_text_empty_returns_nothing():
    assert _chunk_text("") == []
    assert _chunk_text("   \n  ") == []


def test_chunk_text_heading_aware_splits_on_sections():
    doc = "# Alpha\n" + "a\n" * 5 + "# Beta\n" + "b\n" * 5
    # target=25: each ~18-char section fits alone but the pair (~35) exceeds it,
    # so they land in separate chunks — each starting cleanly at its heading.
    chunks = _chunk_text(doc, target=25)
    assert any(c.startswith("# Alpha") for c in chunks)
    assert any(c.startswith("# Beta") for c in chunks)


def test_chunk_text_packs_small_units_up_to_target():
    doc = "line\n" * 100  # 500 chars, no headings
    chunks = _chunk_text(doc, target=100)
    assert len(chunks) >= 4
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == doc  # lossless


def test_chunk_text_hard_splits_an_oversize_line():
    doc = "x" * 250  # single line longer than target
    chunks = _chunk_text(doc, target=100)
    assert chunks == ["x" * 100, "x" * 100, "x" * 50]


def test_fts_match_neutralises_operators_and_ors_tokens():
    # Bare AND/OR/NEAR and parens in raw text must not become FTS5 operators.
    assert _fts_match("find AND (error)", trigram=False) == '"find" OR "AND" OR "error"'


def test_fts_match_trigram_drops_short_tokens():
    assert _fts_match("of a db", trigram=True) is None  # all < 3 chars
    assert _fts_match("connection", trigram=True) == '"connection"'


def test_result_id_is_stable_for_same_content():
    a = _result_id("s1", "web_search", "hello world")
    b = _result_id("s2", "web_search", "hello world")  # session not in the hash
    assert a == b and a.startswith("web_search-")


# ── Index + search ───────────────────────────────────────────────────────────


@pytest.fixture
def idx(tmp_path, monkeypatch):
    """A fresh index on a temp DB with embeddings forced OFF (FTS-only)."""

    async def _no_embed(_text, _base_url):
        return None

    monkeypatch.setattr(tri, "_embed_async", _no_embed)
    return ToolResultIndex(db_path=str(tmp_path / "localmind.db"))


def _big(marker: str, filler: str = "padding text ", size: int = 6000) -> str:
    """A >5 KB document whose body contains a distinctive marker."""
    body = (filler * (size // len(filler)))
    return f"# Report\n{marker}\n{body}"


@pytest.mark.asyncio
async def test_index_is_gated_on_size(idx):
    small = "too small to index"
    _rid, n = await idx.index_result(small, session_id="s1", tool_name="shell")
    assert n == 0 and idx.count() == 0
    # force overrides the gate
    _rid2, n2 = await idx.index_result(small, session_id="s1", tool_name="shell", force=True)
    assert n2 >= 1 and idx.count() == n2


@pytest.mark.asyncio
async def test_bm25_keyword_search_finds_the_chunk(idx):
    await idx.index_result(
        _big("the ConnectionError happened on the socket"),
        session_id="s1",
        tool_name="web_search",
    )
    hits = await idx.search("ConnectionError")
    assert hits, "keyword should retrieve the indexed chunk"
    assert "ConnectionError" in hits[0].text
    assert "bm25" in hits[0].sources


@pytest.mark.asyncio
async def test_trigram_substring_search(idx):
    await idx.index_result(_big("token 0xDEADBEEF in the dump"), session_id="s1", tool_name="shell")
    # A substring that porter-word search would miss but trigram catches.
    hits = await idx.search("deadbee")
    assert hits and "0xDEADBEEF" in hits[0].text
    assert "trigram" in hits[0].sources


@pytest.mark.asyncio
async def test_filters_scope_by_tool_and_session(idx):
    await idx.index_result(_big("shared marker alpha"), session_id="s1", tool_name="web_search")
    await idx.index_result(_big("shared marker alpha"), session_id="s2", tool_name="shell")
    only_s1 = await idx.search("alpha", session_id="s1")
    assert only_s1 and all(h.session_id == "s1" for h in only_s1)
    only_shell = await idx.search("alpha", tool_name="shell")
    assert only_shell and all(h.tool_name == "shell" for h in only_shell)


@pytest.mark.asyncio
async def test_empty_query_returns_nothing(idx):
    await idx.index_result(_big("something"), session_id="s1", tool_name="shell")
    assert await idx.search("") == []
    assert await idx.search(["  ", ""]) == []


@pytest.mark.asyncio
async def test_clear_empties_the_index(idx):
    await idx.index_result(_big("wipe me"), session_id="s1", tool_name="shell")
    assert idx.count() > 0
    idx.clear()
    assert idx.count() == 0
    assert await idx.search("wipe") == []


@pytest.mark.asyncio
async def test_hybrid_fusion_uses_the_vec_half(tmp_path, monkeypatch):
    """With a deterministic fake embedder, the vec0 half is exercised end to end
    (dim table created lazily, embeddings stored, cosine MATCH ranks the topical
    chunk first) and fusion records 'vec' as a contributing source alongside the
    FTS retrievers."""
    vocab = ["network", "database", "payment", "render"]

    async def _fake_embed(text, _base_url):
        low = (text or "").lower()
        # Non-zero, keyword-weighted vector — distinguishes chunks by topic.
        return [float(low.count(w)) + 0.01 for w in vocab]

    monkeypatch.setattr(tri, "_embed_async", _fake_embed)
    index = ToolResultIndex(db_path=str(tmp_path / "localmind.db"))

    await index.index_result(
        _big("the database connection pool was exhausted overnight"),
        session_id="s1",
        tool_name="shell",
    )
    await index.index_result(
        _big("the payment gateway declined three charges"),
        session_id="s1",
        tool_name="shell",
    )
    # "db" is < 3 chars and not a porter word match for these chunks, so a hit
    # here must come from the semantic (vec) half via the shared 'database' dim.
    hits = await index.search("database")
    assert hits, "vec half should retrieve on the semantic dimension"
    assert any("vec" in h.sources for h in hits)
    assert "database" in hits[0].text


@pytest.mark.asyncio
async def test_embed_input_is_capped_to_the_model_window(tmp_path, monkeypatch):
    """A chunk larger than the embed model's context window must still get a vec
    fingerprint: the embed input is truncated to _EMBED_CHAR_CAP, never the full
    (up to 4 KB) chunk — otherwise Ollama 500s and the chunk drops out of vec."""
    seen_lengths: list[int] = []

    async def _recording_embed(text, _base_url):
        seen_lengths.append(len(text))
        return [1.0, 0.0]  # any non-empty vector

    monkeypatch.setattr(tri, "_embed_async", _recording_embed)
    index = ToolResultIndex(db_path=str(tmp_path / "localmind.db"))
    # One oversize chunk (no headings, single long line → hard-split to 4 KB).
    await index.index_result("Z" * 4096 + " tail", session_id="s1", tool_name="shell", force=True)

    assert seen_lengths, "embeddings should have been attempted"
    assert max(seen_lengths) <= tri._EMBED_CHAR_CAP

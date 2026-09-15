"""Tool-Result Index — hybrid FTS5 (porter + trigram) + vec0 store for large
tool results.  P0 Context Engineering, Step 4 (slice 1: the storage engine).

Why this exists
───────────────
A research-heavy agent turn grows its tool-result history fast (measured
91 → 4228 tokens in one turn). The plan — "Tool-Result Index + Search" —
is to stop carrying big
raw outputs inline: index the result, drop a short stub + a pointer into the
prompt, and let the model pull detail back on demand with a search tool.

This module is the *storage engine* for that pattern. It does NOT touch the
agent loop or register a tool — slice 2 wires `search_tool_results` and the
>5 KB stub/pointer replacement into the loop (that half needs live
verification and is kept separate on purpose).

Design (adapted from Context Mode's `store.ts`, made hybrid)
────────────────────────────────────────────────────────────
- `trc_chunks`   — authoritative rows: text + (result_id, session_id,
                   tool_name, chunk_ix, created_at). Reads + filters + the
                   vec0 rowid join all key off this.
- `trc_fts`      — FTS5 external-content over trc_chunks, `porter unicode61`
                   tokenizer → BM25 word search ("find the ConnectionError").
- `trc_fts_tri`  — FTS5 external-content, `trigram` tokenizer → substring /
                   fuzzy match ("0x7f", partial identifiers).
- `trc_vec`      — sqlite-vec `vec0` over the SAME chunks (LocalMind's existing
                   Ollama embeddings) → semantic recall ("what did I learn
                   about network failures?"). Created lazily on the first
                   embedding; dim recorded in `trc_meta`.

Hybrid because FTS5 alone (Context Mode) can't answer semantic paraphrase and
vec0 alone is weak on exact-string recall. Results from the three retrievers
are merged with Reciprocal Rank Fusion (scale-free — no score normalisation
across BM25 / trigram / cosine).

The vec0 half is best-effort: FTS always indexes; embeddings are added only
when Ollama is reachable, so the index degrades to keyword-only offline (and
in unit tests) instead of failing.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.config import settings
from storage.vector import (
    _embed_async,
    _get_connection,
    _normalise,
    _pack,
)

logger = logging.getLogger(__name__)

# Gate: only large results are worth indexing — below this the pointer +
# search overhead exceeds the context saved (addendum: 5 KB threshold).
_INDEX_THRESHOLD_BYTES = 5 * 1024
# Public alias for the agent loop's stub/pointer pass (slice 2), which gates on
# the SAME size so it only indexes + points at results the store actually keeps.
INDEX_THRESHOLD_BYTES = _INDEX_THRESHOLD_BYTES
# Target chunk size: markdown sections are packed up to this, oversize units
# hard-split at it. ~4 KB ≈ ~1 K tokens — small enough to retrieve precisely,
# large enough to keep a coherent section together.
_CHUNK_TARGET_CHARS = 4096
# Embedding models have a small context window (mxbai-embed-large ≈ 512 tokens);
# a full 4 KB chunk overruns it and Ollama returns 500, dropping that chunk from
# the vec half. FTS keeps the whole chunk, but we embed only a leading slice as
# the chunk's semantic fingerprint so EVERY chunk is vec-covered. A head slice is
# a fair topic proxy — headings/intro lead a section. (Slice-2 candidate: window
# the embedding or size chunks to the embed model instead of truncating.)
_EMBED_CHAR_CAP = 1800
_DEFAULT_SEARCH_LIMIT = 8
# Reciprocal-rank-fusion damping constant (the standard k=60).
_RRF_K = 60

_HEADING_RE = re.compile(r"^#{1,6} ", re.MULTILINE)
# Word tokens for building a safe FTS5 MATCH from arbitrary user text.
_WORD_RE = re.compile(r"[0-9A-Za-z_]+")


@dataclass
class ResultChunk:
    """One retrieved chunk plus where it came from."""

    chunk_id: int
    result_id: str
    session_id: str
    tool_name: str
    chunk_ix: int
    text: str
    score: float = 0.0
    sources: tuple[str, ...] = field(default_factory=tuple)


def _chunk_text(content: str, target: int = _CHUNK_TARGET_CHARS) -> list[str]:
    """Split content into <= target-char chunks.

    Markdown-heading-aware: when the text has headings, sections (heading →
    next heading) are the packing unit, so a chunk never straddles a heading
    boundary unless a single section exceeds the target. Otherwise lines are
    the unit. Small consecutive units coalesce up to the target; any single
    unit larger than the target is hard-split.
    """
    content = content or ""
    if not content.strip():
        return []

    if _HEADING_RE.search(content):
        idxs = [m.start() for m in _HEADING_RE.finditer(content)]
        bounds = idxs + [len(content)]
        units: list[str] = []
        if idxs[0] > 0:  # preamble before the first heading
            units.append(content[: idxs[0]])
        for i, start in enumerate(idxs):
            units.append(content[start : bounds[i + 1]])
    else:
        units = content.splitlines(keepends=True)

    chunks: list[str] = []
    buf: list[str] = []
    size = 0

    def _flush() -> None:
        nonlocal buf, size
        if buf:
            chunks.append("".join(buf))
            buf, size = [], 0

    for unit in units:
        if len(unit) > target:
            _flush()
            for i in range(0, len(unit), target):
                chunks.append(unit[i : i + target])
            continue
        if size + len(unit) > target:
            _flush()
        buf.append(unit)
        size += len(unit)
    _flush()

    return [c for c in chunks if c.strip()]


def _result_id(session_id: str, tool_name: str, content: str) -> str:
    """Stable-ish id for a result: content hash + tool, so re-indexing the same
    output is idempotent-friendly and the pointer can name a concrete id."""
    h = hashlib.sha256(f"{tool_name}\x00{content}".encode()).hexdigest()[:16]
    return f"{tool_name or 'tool'}-{h}"


def _fts_match(query: str, *, trigram: bool) -> str | None:
    """Build a safe FTS5 MATCH expression from arbitrary text.

    Word tokens are extracted and each is wrapped in double quotes (which makes
    FTS5 treat it as a literal string, neutralising operators like AND/OR/NEAR/
    parentheses in user input), then OR-ed. Returns None when nothing usable
    remains — for trigram, tokens shorter than 3 chars can't match, so a query
    with only short tokens yields no trigram search.
    """
    tokens = _WORD_RE.findall(query or "")
    if trigram:
        tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


class ToolResultIndex:
    """Hybrid FTS5 + vec0 index over chunked tool results (see module docstring)."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or settings.localmind_db_path or "./localmind.db"
        self._base_url = settings.ollama_base_url
        self._dim: int | None = None
        self._init_db()

    # ── Setup ────────────────────────────────────────────────────────────────

    def _connect(self):
        return _get_connection(self._db_path)

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trc_chunks (
                id          INTEGER PRIMARY KEY,
                result_id   TEXT NOT NULL,
                session_id  TEXT NOT NULL DEFAULT '',
                tool_name   TEXT NOT NULL DEFAULT '',
                chunk_ix    INTEGER NOT NULL DEFAULT 0,
                text        TEXT NOT NULL,
                created_at  REAL NOT NULL DEFAULT (unixepoch('now'))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS trc_chunks_result ON trc_chunks(result_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS trc_chunks_session ON trc_chunks(session_id)")
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS trc_fts "
            "USING fts5(text, content='trc_chunks', content_rowid='id', "
            "tokenize='porter unicode61')"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS trc_fts_tri "
            "USING fts5(text, content='trc_chunks', content_rowid='id', "
            "tokenize='trigram')"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS trc_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.commit()
        row = conn.execute("SELECT value FROM trc_meta WHERE key='dim'").fetchone()
        if row:
            self._dim = int(row["value"])
            self._ensure_vec(conn, self._dim)

    def _ensure_vec(self, conn, dim: int) -> None:
        """Create the vec0 table at the embedding dimension (idempotent)."""
        if self._dim is None:
            self._dim = dim
            conn.execute(
                "INSERT OR REPLACE INTO trc_meta(key, value) VALUES ('dim', ?)", (str(dim),)
            )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS trc_vec USING vec0(embedding float[{self._dim}])"
        )
        # Commit the implicit transaction Python's sqlite3 opens for the INSERT/
        # CREATE above, so a caller's explicit BEGIN IMMEDIATE doesn't hit
        # "cannot start a transaction within a transaction".
        conn.commit()

    # ── Indexing ─────────────────────────────────────────────────────────────

    async def index_result(
        self,
        content: str,
        *,
        session_id: str = "",
        tool_name: str = "",
        result_id: str | None = None,
        force: bool = False,
    ) -> tuple[str, int]:
        """Chunk + index a tool result.

        Returns (result_id, n_chunks). Small results are skipped unless
        ``force=True`` (returns (result_id or "", 0)). FTS is always populated;
        embeddings are added best-effort when Ollama answers.
        """
        content = content or ""
        if not force and len(content.encode("utf-8")) < _INDEX_THRESHOLD_BYTES:
            return (result_id or "", 0)

        chunks = _chunk_text(content)
        if not chunks:
            return (result_id or "", 0)

        result_id = result_id or _result_id(session_id, tool_name, content)
        # Idempotency (the module's stated intent — "re-indexing the same output
        # is idempotent-friendly"): the loop's per-iteration stub/pointer pass
        # re-encounters the same large result every iteration (iteration_messages
        # is a fresh copy of the persistent history), so index_result is called
        # repeatedly for one output. Without this guard each call re-INSERTs the
        # chunks, multiplying rows and skewing search. If the id already has
        # chunks and we're not forcing, return the existing count untouched.
        if not force:
            existing = self._count_result(result_id)
            if existing:
                return (result_id, existing)

        conn = self._connect()
        inserted: list[tuple[int, str]] = []
        conn.execute("BEGIN IMMEDIATE")
        try:
            for ix, chunk in enumerate(chunks):
                cur = conn.execute(
                    "INSERT INTO trc_chunks(result_id, session_id, tool_name, chunk_ix, text) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (result_id, session_id, tool_name, ix, chunk),
                )
                cid = cur.lastrowid
                # External-content FTS5: mirror by rowid so both tokenizers index
                # the same chunk without a second copy of the text.
                conn.execute("INSERT INTO trc_fts(rowid, text) VALUES (?, ?)", (cid, chunk))
                conn.execute("INSERT INTO trc_fts_tri(rowid, text) VALUES (?, ?)", (cid, chunk))
                inserted.append((cid, chunk))
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

        await self._embed_chunks(inserted)
        return (result_id, len(chunks))

    async def _embed_chunks(self, inserted: list[tuple[int, str]]) -> None:
        """Embed chunks and add them to trc_vec — best-effort (Ollama optional)."""
        vecs: list[tuple[int, list[float]]] = []
        for cid, text in inserted:
            try:
                # Cap the embed input so it fits the embed model's context window
                # (see _EMBED_CHAR_CAP); the full chunk still lives in FTS + the row.
                raw = await _embed_async(text[:_EMBED_CHAR_CAP], self._base_url)
            except Exception as exc:  # noqa: BLE001 — embedding is non-critical
                logger.debug("[trc] embed failed (non-critical): %s", exc)
                raw = None
            if raw:
                vecs.append((cid, _normalise(raw)))
        if not vecs:
            return
        conn = self._connect()
        self._ensure_vec(conn, len(vecs[0][1]))
        conn.execute("BEGIN IMMEDIATE")
        try:
            for cid, vec in vecs:
                conn.execute(
                    "INSERT INTO trc_vec(rowid, embedding) VALUES (?, ?)", (cid, _pack(vec))
                )
            conn.execute("COMMIT")
        except Exception as exc:  # noqa: BLE001 — never fail a turn on the vec write
            logger.debug("[trc] vec write failed (non-critical): %s", exc)
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass

    # ── Search ───────────────────────────────────────────────────────────────

    async def search(
        self,
        queries: str | list[str],
        *,
        tool_name: str | None = None,
        session_id: str | None = None,
        result_id: str | None = None,
        limit: int = _DEFAULT_SEARCH_LIMIT,
    ) -> list[ResultChunk]:
        """Hybrid search over indexed chunks.

        Runs each query through BM25 (porter), trigram, and (when available)
        vec0, fuses the ranked lists with Reciprocal Rank Fusion, and returns
        the top ``limit`` chunks. ``tool_name`` / ``session_id`` / ``result_id``
        scope the results (``result_id`` narrows to one stored result — the
        stub/pointer path names a concrete id). An empty / all-blank query list
        returns [].
        """
        if isinstance(queries, str):
            queries = [queries]
        queries = [q for q in (queries or []) if q and q.strip()]
        if not queries:
            return []

        fused: dict[int, dict] = {}
        for query in queries:
            ranked_lists = [
                ("bm25", self._fts_search(query, "trc_fts", tool_name, session_id, result_id, limit)),
                ("trigram", self._fts_search(query, "trc_fts_tri", tool_name, session_id, result_id, limit)),
                ("vec", await self._vec_search(query, tool_name, session_id, result_id, limit)),
            ]
            for source, ranked in ranked_lists:
                for rank, cid in enumerate(ranked):
                    slot = fused.setdefault(cid, {"score": 0.0, "sources": set()})
                    slot["score"] += 1.0 / (_RRF_K + rank + 1)
                    slot["sources"].add(source)

        if not fused:
            return []
        top = sorted(fused.items(), key=lambda kv: kv[1]["score"], reverse=True)[:limit]
        return self._materialise(top)

    def _fts_search(
        self,
        query: str,
        table: str,
        tool_name: str | None,
        session_id: str | None,
        result_id: str | None,
        limit: int,
    ) -> list[int]:
        """Ranked chunk ids from one FTS5 table (BM25 order), with filters."""
        match = _fts_match(query, trigram=(table == "trc_fts_tri"))
        if not match:
            return []
        sql = (
            f"SELECT t.id FROM {table} f JOIN trc_chunks t ON t.id = f.rowid "
            f"WHERE {table} MATCH ?"
        )
        params: list = [match]
        if tool_name:
            sql += " AND t.tool_name = ?"
            params.append(tool_name)
        if session_id:
            sql += " AND t.session_id = ?"
            params.append(session_id)
        if result_id:
            sql += " AND t.result_id = ?"
            params.append(result_id)
        sql += f" ORDER BY bm25({table}) LIMIT ?"
        params.append(limit)
        try:
            return [r["id"] for r in self._connect().execute(sql, params).fetchall()]
        except Exception as exc:  # noqa: BLE001 — a bad MATCH must not crash search
            logger.debug("[trc] fts search failed (%s): %s", table, exc)
            return []

    async def _vec_search(
        self,
        query: str,
        tool_name: str | None,
        session_id: str | None,
        result_id: str | None,
        limit: int,
    ) -> list[int]:
        """Ranked chunk ids from vec0 (cosine order). Empty when the vec table
        doesn't exist yet or Ollama is unreachable."""
        if self._dim is None:
            return []
        try:
            raw = await _embed_async(query, self._base_url)
        except Exception:
            raw = None
        if not raw:
            return []
        vec = _normalise(raw)
        # Over-fetch, then filter by tool/session/result in Python — vec0's MATCH
        # does not compose cleanly with arbitrary JOIN predicates across versions.
        k = limit * 3 if (tool_name or session_id or result_id) else limit
        try:
            rows = self._connect().execute(
                "SELECT t.id, t.tool_name, t.session_id, t.result_id "
                "FROM trc_vec v JOIN trc_chunks t ON t.id = v.rowid "
                "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
                (_pack(vec), k),
            ).fetchall()
        except Exception as exc:  # noqa: BLE001 — vec table may be absent/empty
            logger.debug("[trc] vec search failed: %s", exc)
            return []
        out: list[int] = []
        for r in rows:
            if tool_name and r["tool_name"] != tool_name:
                continue
            if session_id and r["session_id"] != session_id:
                continue
            if result_id and r["result_id"] != result_id:
                continue
            out.append(r["id"])
            if len(out) >= limit:
                break
        return out

    def _materialise(self, top: list[tuple[int, dict]]) -> list[ResultChunk]:
        conn = self._connect()
        out: list[ResultChunk] = []
        for cid, slot in top:
            row = conn.execute(
                "SELECT id, result_id, session_id, tool_name, chunk_ix, text "
                "FROM trc_chunks WHERE id = ?",
                (cid,),
            ).fetchone()
            if not row:
                continue
            out.append(
                ResultChunk(
                    chunk_id=row["id"],
                    result_id=row["result_id"],
                    session_id=row["session_id"],
                    tool_name=row["tool_name"],
                    chunk_ix=row["chunk_ix"],
                    text=row["text"],
                    score=round(slot["score"], 6),
                    sources=tuple(sorted(slot["sources"])),
                )
            )
        return out

    # ── Housekeeping ─────────────────────────────────────────────────────────

    def count(self) -> int:
        try:
            return self._connect().execute("SELECT COUNT(*) FROM trc_chunks").fetchone()[0]
        except Exception:
            return 0

    def _count_result(self, result_id: str) -> int:
        """Number of chunks already stored for a result_id (idempotency check)."""
        try:
            row = self._connect().execute(
                "SELECT COUNT(*) FROM trc_chunks WHERE result_id = ?", (result_id,)
            ).fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    def clear(self) -> None:
        """Remove every indexed chunk (FTS + vec). Used by tests and, later, by
        session/turn pruning."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM trc_chunks")
            conn.execute("INSERT INTO trc_fts(trc_fts) VALUES ('delete-all')")
            conn.execute("INSERT INTO trc_fts_tri(trc_fts_tri) VALUES ('delete-all')")
            try:
                conn.execute("DELETE FROM trc_vec")
            except Exception:
                pass  # vec table may not exist yet
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[trc] clear failed: %s", exc)


# ── Shared instance + pointer rendering (slice 2 wiring) ─────────────────────

_INDEX_SINGLETON: ToolResultIndex | None = None


def get_tool_result_index() -> ToolResultIndex:
    """Process-wide shared index over the LocalMind db.

    The agent loop (indexing large results) and the ``search_tool_results``
    tool (reading them back) must hit the SAME store; a singleton avoids
    re-running ``_init_db`` on every large result and every search.
    """
    global _INDEX_SINGLETON
    if _INDEX_SINGLETON is None:
        _INDEX_SINGLETON = ToolResultIndex()
    return _INDEX_SINGLETON

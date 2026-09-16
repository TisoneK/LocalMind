"""search_tool_results — read back a large tool result the loop stored.

P0 Context Engineering, Step 4 (slice 2: the retrieval half).

Why this exists
───────────────
A research-heavy turn produces big tool outputs (web_fetch pages, file reads,
shell dumps). Carrying them inline balloons the context (measured 91 → 4228
tokens in one turn). The first slice built the hybrid FTS5+vec0 store
(``storage/tool_result_index.ToolResultIndex``); the agent loop now indexes any
result over the ~5 KB threshold and replaces the inline copy with a short
stub + pointer (``id=<result_id>``). THIS tool is how the model pulls the
detail back on demand instead of re-fetching or working blind.

Contract
────────
- SCOPED to the current session by default (``current_session_id()``), so one
  turn never reads another session's stored results. ``result_id`` narrows to
  one stored result (the stub names it); ``tool_name`` narrows by producer.
- BOUNDED: a handful of the most relevant chunks, each capped — the reply must
  not re-flood the context it was built to shrink.
- NEVER RAISES: every failure degrades to ``ToolResult(success=False)``.

Registered as ``Intent.SEARCH_TOOL_RESULTS`` (on-demand / long-tail: loaded into
the native tool surface only on turns that actually carry a pointer).
"""

from __future__ import annotations

import json
import logging

from core.models import Intent, RiskLevel, ToolResult
from core.session_workspace import current_session_id
from storage.tool_result_index import get_tool_result_index
from tools import register_tool

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 6
_HARD_LIMIT = 12
# Per-chunk char cap in the reply — enough to carry a full stored chunk
# (~4 KB source chunk) while keeping the retrieval bounded. The total stays
# under the loop's ~5 KB index threshold so a retrieval result is never itself
# re-indexed (the loop also exempts this tool by name — belt and suspenders).
_CHUNK_CHAR_CAP = 1500
_TOTAL_CHAR_CAP = 4800


def _clamp(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _parse_args(message: str) -> dict:
    """JSON args, or a plain string treated as the query."""
    text = (message or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"query": text}


async def search_tool_results(message: str) -> ToolResult:
    """
    SEARCH_TOOL_RESULTS dispatch — read back a stored large tool result.

    Args (JSON, or a plain string used as the query):
        query:      what to look for (required) — words, a phrase, or an
                    identifier from the stored result.
        result_id:  restrict to ONE stored result (the id in a pointer stub).
        tool_name:  restrict to results produced by this tool (e.g. web_fetch).
        limit:      max chunks to return (default 6, max 12).
    """
    args = _parse_args(message)
    query = args.get("query") or args.get("q") or ""
    if isinstance(query, list):
        query = " ".join(str(q) for q in query if q)
    query = str(query).strip()
    if not query:
        return ToolResult(
            content=(
                "search_tool_results needs a 'query' (what to look for). "
                "Optionally pass 'result_id' (from a pointer stub) or 'tool_name'."
            ),
            risk=RiskLevel.LOW,
            source="search_tool_results",
            success=False,
            error_type="invalid_input",
            error_message="missing 'query'",
        )

    result_id = str(args.get("result_id") or "").strip() or None
    tool_name = str(args.get("tool_name") or "").strip() or None
    limit = _clamp(args.get("limit"), _DEFAULT_LIMIT, 1, _HARD_LIMIT)
    session_id = current_session_id()

    try:
        chunks = await get_tool_result_index().search(
            query,
            tool_name=tool_name,
            session_id=session_id,
            result_id=result_id,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 — a tool must never raise
        logger.exception("[search_tool_results] search failed")
        return ToolResult(
            content=f"search_tool_results failed unexpectedly: {exc}",
            risk=RiskLevel.LOW,
            source="search_tool_results",
            success=False,
            error_type="internal_error",
            error_message=str(exc),
        )

    if not chunks:
        scope = []
        if result_id:
            scope.append(f"result_id={result_id}")
        if tool_name:
            scope.append(f"tool={tool_name}")
        scope_note = f" ({', '.join(scope)})" if scope else ""
        return ToolResult(
            content=(
                f"No stored tool-result chunks matched '{query}'{scope_note}. "
                "Large results are only indexed once they exceed ~5 KB; a small "
                "result stays inline in the conversation. If you expected a match, "
                "try broader words or drop the result_id/tool_name filter."
            ),
            risk=RiskLevel.LOW,
            source="search_tool_results",
            metadata={"query": query, "results": [], "returned": 0},
            # success=True: "no match" is a valid, honest answer, not a failure
            # (a failed tool trips the loop's failure/fabrication accounting).
        )

    lines: list[str] = [f"Stored tool-result chunks for '{query}' (top {len(chunks)}):"]
    total = 0
    meta_results: list[dict] = []
    for i, ch in enumerate(chunks, 1):
        text = ch.text or ""
        if len(text) > _CHUNK_CHAR_CAP:
            text = text[:_CHUNK_CHAR_CAP].rstrip() + "\n…[chunk truncated]"
        sources = "+".join(ch.sources) if ch.sources else "?"
        header = f"[{i}] {ch.tool_name or 'tool'} · {ch.result_id}#{ch.chunk_ix} · via {sources}"
        block = f"\n{header}\n{text}\n"
        if total + len(block) > _TOTAL_CHAR_CAP and i > 1:
            lines.append(f"\n…[{len(chunks) - i + 1} more chunk(s) omitted — narrow the query or raise limit]")
            break
        total += len(block)
        lines.append(block)
        meta_results.append(
            {
                "result_id": ch.result_id,
                "tool_name": ch.tool_name,
                "chunk_ix": ch.chunk_ix,
                "score": ch.score,
                "sources": list(ch.sources),
            }
        )

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="search_tool_results",
        metadata={"query": query, "returned": len(meta_results), "results": meta_results},
    )


register_tool(
    Intent.SEARCH_TOOL_RESULTS,
    search_tool_results,
    description=(
        "Read back the FULL content of an earlier large tool result that was "
        "stored and replaced with a short stub + 'id=<result_id>' pointer in "
        "this conversation. Use it when a stub tells you output was stored and "
        "you need detail from it — pass the result_id from the stub plus a "
        "'query' for what you need. Do NOT re-run the original tool to see a "
        "result you already have stored."
    ),
    cost=0.0,
    latency_ms=150,
    parallelizable=True,
)

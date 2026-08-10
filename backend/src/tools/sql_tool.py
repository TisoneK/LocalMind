"""
SQL tool — bounded, read-only SQLite querying (B-2026-07-31-10, Data tools slice 2).

Answers "what's in this database?" against local .db/.sqlite files.

Design contract (consistent with find_path/observe/csv/json):
- SECURITY: the file path must pass settings.is_path_allowed. The connection
  is opened with the sqlite URI `mode=ro` — the database is READ-ONLY, so
  even a model-generated `DROP TABLE` / `INSERT` / `UPDATE` fails safely
  ("attempt to write a readonly database") with zero blast radius.
- SINGLE STATEMENT: sqlite3 executes exactly one statement per execute() —
  multi-statement injection is impossible by construction.
- BOUNDED by construction: row cap (default 20, max 50), column display
  truncation — a table with a million rows costs the same handful of tokens
  as a 10-row one.
- GRACEFUL: missing file, not-a-database, write-attempt, empty results all
  return a short explanatory string — never raises.
- Deterministic: stdlib `sqlite3` only, no network, no eval.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

_MAX_ROWS: int = 20
_MAX_ROWS_LIMIT: int = 50
_MAX_COLS: int = 20
_MAX_COLS_LIMIT: int = 50
_CELL_DISPLAY_CHARS: int = 40
_CONNECT_TIMEOUT_SECS: float = 5.0


def _format_rows(rows: list[tuple], column_names: list[str], max_rows: int, max_cols: int) -> str:
    """Render query results as a bounded aligned table (csv_tool's shape)."""
    col_count = min(len(column_names), max_cols)
    names = [column_names[c][:_CELL_DISPLAY_CHARS] for c in range(col_count)]
    widths = [len(n) for n in names]
    for r in rows:
        for c in range(col_count):
            val = str(r[c]) if c < len(r) else ""
            if len(val) > _CELL_DISPLAY_CHARS:
                val = val[:_CELL_DISPLAY_CHARS]
            widths[c] = max(widths[c], len(val))
    lines = [f"{len(rows)} row(s) returned"]
    header = " | ".join(n.ljust(widths[c]) for c, n in enumerate(names))
    lines.append(header.rstrip())
    for r in rows:
        cells = []
        for c in range(col_count):
            val = str(r[c]) if c < len(r) else ""
            if len(val) > _CELL_DISPLAY_CHARS:
                val = val[:_CELL_DISPLAY_CHARS] + "…"
            cells.append(val.ljust(widths[c]))
        lines.append(" | ".join(cells).rstrip())
    if len(column_names) > col_count:
        lines.append(f"… {len(column_names) - col_count} more columns (capped at {max_cols})")
    return "\n".join(lines)


def _sql_query(path: str, query: str, max_rows: int = _MAX_ROWS) -> str:
    """Run a read-only SQLite query. Returns a string, never raises."""
    p = Path(path)
    if not settings.is_path_allowed(p):
        return f"Error: path not allowed: {path}"
    if not query.strip():
        return "Error: empty SQL query — pass a SELECT statement."
    if re.search(r"\battach\b", query, re.IGNORECASE):
        # ATTACH opens OTHER database files on disk — it would bypass the
        # is_path_allowed guard on the main path. Reject it outright.
        return "Error: ATTACH is not allowed — query only the given database file."
    try:
        # mode=ro makes the connection read-only at the SQLite level (writes
        # fail safely). quote() percent-encodes URI-special chars (?/#/space)
        # in the path so a filename like 'data#1.db' resolves correctly.
        conn = sqlite3.connect(
            f"file:{quote(str(p))}?mode=ro",
            uri=True,
            timeout=_CONNECT_TIMEOUT_SECS,
        )
        # B-2026-07-31-10 (Session 132 review): sqlite3 is blocking C code —
        # asyncio.wait_for in the dispatch layer cannot interrupt it mid-call,
        # so a model-generated cartesian join / recursive CTE could hang the
        # loop past every timeout. set_progress_handler aborts the query after
        # N VM opcodes with a clean error (the standard sqlite3 cost bound).
        def _abort_expensive() -> bool:
            raise sqlite3.OperationalError(
                "query too expensive — add a LIMIT or narrow the query"
            )

        conn.set_progress_handler(_abort_expensive, 200_000)
    except sqlite3.Error as exc:
        return f"Error: cannot open {path} as a database — {exc}"
    try:
        cur = conn.cursor()
        cur.execute(query)  # single statement; writes fail on a readonly db
        if cur.description is None:
            # A non-SELECT statement somehow ran (e.g. PRAGMA) — no result set.
            conn.rollback()
            return "Error: query produced no result set — only SELECT-type queries are useful here."
        column_names = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows + 1)
        truncated_rows = len(rows) > max_rows
        if truncated_rows:
            rows = rows[:max_rows]
    except sqlite3.Error as exc:
        return f"Error: query failed — {exc}"
    finally:
        conn.close()

    if not rows:
        return f"({len(column_names)} columns, 0 rows — query returned nothing)"
    max_cols = _MAX_COLS
    out = _format_rows(rows, column_names, max_rows, max_cols)
    if truncated_rows:
        out += f"\n… more rows exist (capped at {max_rows})"
    return out


async def sql_query(message: str) -> ToolResult:
    """SQL dispatch — message is JSON-encoded {path, query, max_rows?} or a bare query."""
    try:
        if message.strip().startswith("{"):
            args = json.loads(message)
            if not isinstance(args, dict):
                raise ValueError("args must be an object")
            path = str(args.get("path", "")).strip()
            query = str(args.get("query", "")).strip()
            max_rows = int(args.get("max_rows", _MAX_ROWS))
        else:
            return ToolResult(
                content=(
                    "Error: SQL tool needs JSON args {path, query, max_rows?} — "
                    "pass a database file path and a SELECT statement."
                ),
                risk=RiskLevel.LOW,
                source="sql",
            )
        if not path or not query:
            return ToolResult(
                content="Error: both path and query are required ({path, query, max_rows?}).",
                risk=RiskLevel.LOW,
                source="sql",
            )
        max_rows = max(1, min(int(max_rows), _MAX_ROWS_LIMIT))
        content = _sql_query(path, query, max_rows=max_rows)
        return ToolResult(
            content=content,
            risk=RiskLevel.LOW,
            source="sql",
            metadata={"offline": True, "readonly": True},
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return ToolResult(
            content=f"Error: could not parse sql arguments — {exc}",
            risk=RiskLevel.LOW,
            source="sql",
        )
    except Exception as exc:  # noqa: BLE001 — last-resort: never crash the loop
        logger.error("[sql] error: %s", exc)
        return ToolResult(
            content=f"SQL error: {exc}",
            risk=RiskLevel.LOW,
            source="sql",
        )


register_tool(
    Intent.SQL,
    sql_query,
    description=(
        "Run a read-only SQLite SELECT against a local .db/.sqlite file (path must be in "
        "allowed folders). Args: {path, query, max_rows?}. The connection is read-only — "
        "writes fail safely. Output is bounded (row cap 20, max 50). Use for 'what's in "
        "this database' / inspect tables without dumping the whole file."
    ),
    cost=0.0,
    latency_ms=50,
    parallelizable=True,
)

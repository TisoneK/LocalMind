"""
CSV tool — bounded, offline CSV file parsing (B-2026-07-31-10, Data tools slice).

Reads a CSV file and returns a compact aligned table — NEVER the raw file.

Design contract (consistent with find_path/observe):
- SECURITY: the file path must pass settings.is_path_allowed (the same
  read-path allowlist find_path and observe use). Rejects anything else
  with a clear message.
- BOUNDED by construction: file size cap (512 KB), row cap (default 20,
  max 50) and column cap (default 20, max 50) — a 100K-row CSV costs the
  same handful of tokens as a 10-row one.
- GRACEFUL: missing file, unreadable file, invalid CSV, empty file all
  return a short explanatory string — never raises.
- Deterministic: stdlib `csv` only, no network, no eval.
"""

from __future__ import annotations

import csv as _csv
import io
import json
import logging
from pathlib import Path

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

_MAX_READ_BYTES: int = 512 * 1024
_DEFAULT_MAX_ROWS: int = 20
_DEFAULT_MAX_COLS: int = 20
_MAX_ROWS_LIMIT: int = 50
_MAX_COLS_LIMIT: int = 50
_CELL_DISPLAY_CHARS: int = 40


def _decode(data: bytes) -> str:
    """Decode with BOM tolerance, falling back to latin-1 (never raises)."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _csv_read(path: str, max_rows: int = _DEFAULT_MAX_ROWS, max_cols: int = _DEFAULT_MAX_COLS) -> str:
    """Parse a CSV file into a bounded aligned table. Returns a string, never raises."""
    p = Path(path)
    if not settings.is_path_allowed(p):
        return f"Error: path not allowed: {path}"
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return f"Error: cannot read {path}: {exc}"
    if len(raw) > _MAX_READ_BYTES:
        return f"Error: file too large ({len(raw)} bytes > {_MAX_READ_BYTES}) — refusing to parse"
    rows = list(_csv.reader(io.StringIO(_decode(raw))))
    if not rows:
        return f"Error: {path} is empty or contains no rows."

    total_rows, total_cols = len(rows), max((len(r) for r in rows), default=0)
    max_rows = max(1, min(int(max_rows), _MAX_ROWS_LIMIT))
    max_cols = max(1, min(int(max_cols), _MAX_COLS_LIMIT))
    shown = rows[:max_rows]
    col_count = min(total_cols, max_cols)

    # Column widths across the shown rows (each cell display-truncated).
    widths: list[int] = []
    for c in range(col_count):
        w = 0
        for r in shown:
            if c < len(r):
                w = max(w, len(str(r[c])[:_CELL_DISPLAY_CHARS]))
        widths.append(w)

    lines = [f"{total_rows} rows × {total_cols} cols"]
    for r in shown:
        cells = []
        for c in range(col_count):
            val = str(r[c]) if c < len(r) else ""
            if len(val) > _CELL_DISPLAY_CHARS:
                val = val[:_CELL_DISPLAY_CHARS] + "…"
            cells.append(val.ljust(widths[c]))
        lines.append(" | ".join(cells).rstrip())
    if total_rows > len(shown):
        lines.append(f"… {total_rows - len(shown)} more rows (capped at {max_rows})")
    if total_cols > col_count:
        lines.append(f"… {total_cols - col_count} more columns (capped at {max_cols})")
    return "\n".join(lines)


async def csv_read(message: str) -> ToolResult:
    """CSV dispatch — message is JSON-encoded {path, max_rows, max_cols} or a bare path."""
    try:
        if message.strip().startswith("{"):
            args = json.loads(message)
            if not isinstance(args, dict):
                raise ValueError("args must be an object")
            path = str(args.get("path", "")).strip()
            max_rows = int(args.get("max_rows", _DEFAULT_MAX_ROWS))
            max_cols = int(args.get("max_cols", _DEFAULT_MAX_COLS))
        else:
            path, max_rows, max_cols = message.strip(), _DEFAULT_MAX_ROWS, _DEFAULT_MAX_COLS
        if not path:
            return ToolResult(
                content="Error: no CSV path given — pass a path to a .csv file.",
                risk=RiskLevel.LOW,
                source="csv",
            )
        content = _csv_read(path, max_rows=max_rows, max_cols=max_cols)
        return ToolResult(
            content=content,
            risk=RiskLevel.LOW,
            source="csv",
            metadata={"offline": True},
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return ToolResult(
            content=f"Error: could not parse csv arguments — {exc}",
            risk=RiskLevel.LOW,
            source="csv",
        )
    except Exception as exc:  # noqa: BLE001 — last-resort: never crash the loop
        logger.error("[csv] error: %s", exc)
        return ToolResult(
            content=f"CSV error: {exc}",
            risk=RiskLevel.LOW,
            source="csv",
        )


register_tool(
    Intent.CSV,
    csv_read,
    description=(
        "Read a CSV file and return a compact bounded table (row cap 20, col cap 20) — "
        "never the raw file. Args: {path, max_rows?, max_cols?}. The path must be inside "
        "allowed folders. Use for 'what's in this CSV' / summarize spreadsheet data "
        "without dumping it into context."
    ),
    cost=0.0,
    latency_ms=50,
    parallelizable=True,
)

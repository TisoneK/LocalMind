"""
JSON tool — bounded, offline JSON parsing & dot-path querying
(B-2026-07-31-10, Data tools slice).

Answers "what's in this JSON?" for either a file (path must be allowed)
or an inline JSON string. Supports a simple dot-path query for drilling
into nested structures: `a.b[0].c`.

Design contract (consistent with find_path/observe/csv):
- SECURITY: file sources must pass settings.is_path_allowed.
- BOUNDED by construction: file size cap (512 KB), item cap for large
  collections (default 20, max 100), cell display truncation — a huge
  JSON file costs the same handful of tokens as a small one.
- GRACEFUL: invalid JSON, missing keys, out-of-range indexes, unreadable
  files all return a short explanatory string — never raises.
- Deterministic: stdlib `json` only, no eval, no network.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

_MAX_READ_BYTES: int = 512 * 1024
_DEFAULT_MAX_ITEMS: int = 20
_MAX_ITEMS_LIMIT: int = 100
_SCALAR_CHARS: int = 120
_PRETTY_CHARS: int = 2000


class _QueryError(ValueError):
    """Raised when a dot-path query cannot be satisfied."""


def _decode(data: bytes) -> str:
    """Decode with BOM tolerance, falling back to latin-1 (never raises)."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _walk(obj: object, query: str) -> object:
    """Follow a dot-path query: a.b[0].c — indexes into lists, keys into dicts."""
    tokens = re.findall(r"[^.\[\]]+|\[\d+\]", query)
    for tok in tokens:
        if tok.startswith("[") and tok.endswith("]"):
            idx = int(tok[1:-1])
            if not isinstance(obj, list):
                raise _QueryError(f"'{tok}' needs a list, but the current value is {type(obj).__name__}")
            if not (0 <= idx < len(obj)):
                raise _QueryError(f"index {idx} out of range (list has {len(obj)} items)")
            obj = obj[idx]
        else:
            if not isinstance(obj, dict):
                raise _QueryError(f"key '{tok}' needs an object, but the current value is {type(obj).__name__}")
            if tok not in obj:
                raise _QueryError(f"key '{tok}' not found")
            obj = obj[tok]
    return obj


def _summarize(value: object) -> str:
    """Compact one-line summary of a JSON value (bounded)."""
    if isinstance(value, dict):
        return f"{{object with {len(value)} key{'s' if len(value) != 1 else ''}}}"
    if isinstance(value, list):
        return f"[{len(value)} items]"
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= _SCALAR_CHARS else text[:_SCALAR_CHARS] + "…"


def _describe(obj: object) -> str:
    if isinstance(obj, dict):
        return f"object with {len(obj)} keys"
    if isinstance(obj, list):
        return f"array of {len(obj)} items"
    return type(obj).__name__


def _format_json(obj: object, max_items: int = _DEFAULT_MAX_ITEMS) -> str:
    """Format a parsed JSON value with hard bounds on size and item count."""
    if isinstance(obj, (dict, list)):
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
        if len(pretty) <= _PRETTY_CHARS:
            return f"{pretty}\n({_describe(obj)})"
        # Large structure → bounded summary instead of a flood.
        lines: list[str] = []
        if isinstance(obj, dict):
            items = list(obj.items())[:max_items]
            for k, v in items:
                lines.append(f"{k}: {_summarize(v)}")
            if len(obj) > len(items):
                lines.append(f"… {len(obj) - len(items)} more keys")
        else:
            for i, v in enumerate(obj[:max_items]):
                lines.append(f"[{i}] {_summarize(v)}")
            if len(obj) > max_items:
                lines.append(f"… {len(obj) - max_items} more items")
        return "\n".join(lines) + f"\n({_describe(obj)})"
    return str(obj)


def _load_source(source: str) -> tuple[str, bool]:
    """Resolve the source to raw JSON text. Returns (text, was_file)."""
    stripped = source.strip()
    if stripped.startswith(("{", "[")):
        return stripped, False  # inline JSON
    p = Path(os.path.expanduser(stripped))
    if os.path.exists(p):
        if not settings.is_path_allowed(p):
            raise _QueryError(f"path not allowed: {source}")
        raw = p.read_bytes()
        if len(raw) > _MAX_READ_BYTES:
            raise _QueryError(f"file too large ({len(raw)} bytes > {_MAX_READ_BYTES})")
        return _decode(raw), True
    # Neither inline JSON nor an existing path — try inline; json.loads
    # will produce a clear error if it's genuinely malformed.
    return stripped, False


def _json_query(source: str, query: str = "", max_items: int = _DEFAULT_MAX_ITEMS) -> str:
    """Parse JSON (file or inline) and optionally drill with a dot-path query."""
    try:
        text, was_file = _load_source(source)
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"Error: not valid JSON — {exc}"
    except OSError as exc:
        return f"Error: cannot read {source}: {exc}"
    except _QueryError as exc:
        return f"Error: {exc}"
    except RecursionError:
        return "Error: JSON too deeply nested to parse"
    if query:
        try:
            obj = _walk(obj, query.strip())
        except _QueryError as exc:
            return f"Error: {exc}"
    max_items = max(1, min(int(max_items), _MAX_ITEMS_LIMIT))
    prefix = f"source: {source}\n" if was_file else ""
    return prefix + _format_json(obj, max_items=max_items)


async def json_query(message: str) -> ToolResult:
    """JSON dispatch — message is JSON-encoded {source, query?, max_items?} or a bare string."""
    try:
        if message.strip().startswith("{"):
            args = json.loads(message)
            if not isinstance(args, dict):
                raise ValueError("args must be an object")
            source = str(args.get("source", "")).strip()
            query = str(args.get("query", "")).strip()
            max_items = int(args.get("max_items", _DEFAULT_MAX_ITEMS))
        else:
            source, query, max_items = message.strip(), "", _DEFAULT_MAX_ITEMS
        if not source:
            return ToolResult(
                content="Error: no JSON given — pass inline JSON or a path to a .json file.",
                risk=RiskLevel.LOW,
                source="json",
            )
        content = _json_query(source, query=query, max_items=max_items)
        return ToolResult(
            content=content,
            risk=RiskLevel.LOW,
            source="json",
            metadata={"offline": True},
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return ToolResult(
            content=f"Error: could not parse json arguments — {exc}",
            risk=RiskLevel.LOW,
            source="json",
        )
    except Exception as exc:  # noqa: BLE001 — last-resort: never crash the loop
        logger.error("[json] error: %s", exc)
        return ToolResult(
            content=f"JSON error: {exc}",
            risk=RiskLevel.LOW,
            source="json",
        )


register_tool(
    Intent.JSON,
    json_query,
    description=(
        "Parse and summarize JSON — from a file path (must be in allowed folders) or an "
        "inline JSON string. Optional dot-path query to drill in: a.b[0].c. Args: "
        "{source, query?, max_items?}. Output is bounded (large collections are "
        "summarized, never dumped). Use for 'what's in this JSON' / config inspection."
    ),
    cost=0.0,
    latency_ms=50,
    parallelizable=True,
)

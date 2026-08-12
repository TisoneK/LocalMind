"""Canonical provider-error normalization (ADR-20).

The user's principle (Session 165): *never expose provider-specific error
payloads directly in the conversation UI.* Whether the provider is Zen,
Anthropic, OpenAI, Ollama, or something new, the user should see what
happened, why it happened, and what they can do next — not an API dump.
The raw provider response belongs in developer/debug details (the `raw`
field, plus server logs), not in the chat.

This module is the ONLY place that understands provider error shapes. It is
pure and deterministic — no I/O, no model calls — so it is fully unit-
testable without a live provider.

Where it sits (see design.md §3): adapters still emit their raw string on
`StreamChunk.error` (every internal consumer — CLI, logs, synthesizer,
memory — keeps working with strings). `normalize_error()` runs once, at the
SSE presentation boundary in `api/routes/chat.py`, and turns the raw string
into the canonical shape the frontend renders:

    {
      "status": "error",
      "source": "model_provider",     # "model_provider" | "internal"
      "provider": "zen",              # parsed from the string; None if unknown
      "code": "rate_limit",           # canonical classification
      "message": "The model provider has temporarily reached its usage limit...",
      "retryable": true,              # drives the UI's primary action
      "raw": "<original provider response>"   # debug surface only
    }
"""

from __future__ import annotations

import json
import re
from typing import Any

# ── Canonical error codes ────────────────────────────────────────────────────
RATE_LIMIT = "rate_limit"
AUTH_ERROR = "auth_error"
PAYMENT_REQUIRED = "payment_required"
MODEL_NOT_FOUND = "model_not_found"
CONTEXT_OVERFLOW = "context_overflow"
TIMEOUT = "timeout"
SERVER_ERROR = "server_error"
NETWORK_ERROR = "network_error"
GENERIC_ERROR = "error"

SOURCE_PROVIDER = "model_provider"
SOURCE_INTERNAL = "internal"

# Friendly, provider-agnostic messages — the user sees one of these (or the
# cleaned raw text for generic errors), never the provider's payload.
_MESSAGES: dict[str, str] = {
    RATE_LIMIT: (
        "The model provider has temporarily reached its usage limit. "
        "Try again in a few minutes or switch to another model."
    ),
    AUTH_ERROR: (
        "The model provider rejected the access credentials. "
        "Check the API key in Settings."
    ),
    PAYMENT_REQUIRED: (
        "The model provider requires payment or a quota top-up before it "
        "can respond."
    ),
    MODEL_NOT_FOUND: (
        "The selected model is not available on this provider. "
        "Pick a different model."
    ),
    CONTEXT_OVERFLOW: (
        "The conversation is too long for the selected model's context "
        "window. Start a new chat or switch to a model with a larger "
        "context."
    ),
    TIMEOUT: "The model provider took too long to respond. Try again.",
    SERVER_ERROR: (
        "The model provider is temporarily unavailable. Try again in a "
        "moment."
    ),
    NETWORK_ERROR: (
        "Couldn't reach the model provider. Check your network connection "
        "and try again."
    ),
}

# Matches the adapters' error format: "{provider} returned {status}: {body}"
# e.g. "zen returned 429: {...}" (openai_compat.py) and
# "Ollama returned 404 for model 'llama3'. ..." (ollama.py).
_PROVIDER_ERROR_RE = re.compile(
    r"^(?P<provider>[A-Za-z0-9_.\-]+)\s+returned\s+(?P<status>\d{3})(?P<rest>.*)$",
    re.DOTALL,
)

# Status-code → (code, retryable) for the codes that are status-defined.
_STATUS_CODES: dict[int, tuple[str, bool]] = {
    429: (RATE_LIMIT, True),
    401: (AUTH_ERROR, False),
    403: (AUTH_ERROR, False),
    402: (PAYMENT_REQUIRED, False),
    404: (MODEL_NOT_FOUND, False),
    408: (TIMEOUT, True),
    500: (SERVER_ERROR, True),
    502: (SERVER_ERROR, True),
    503: (SERVER_ERROR, True),
    504: (TIMEOUT, True),
}

# Content-keyword → code (checked case-insensitively). Ordered by priority:
# a message that contains multiple signals (e.g. "429 rate limit") must land
# on the most specific code.
_KEYWORD_RULES: list[tuple[tuple[str, ...], str, bool]] = [
    (("rate limit", "usage limit", "too many requests", "toomanyrequests",
      "throttl", "freeusagelimiterror"), RATE_LIMIT, True),
    (("invalid api key", "invalid_api_key", "unauthorized", "authentication",
      "forbidden", "permission", "access denied"), AUTH_ERROR, False),
    (("insufficient", "billing", "payment required"), PAYMENT_REQUIRED, False),
    (("model not found", "no such model", "could not be loaded",
      "does not exist", "model '"), MODEL_NOT_FOUND, False),
    (("context length", "context_length", "maximum context", "max context",
      "too many tokens", "token limit", "prompt is too long",
      "exceeds the maximum", "input is too long", "context window",
      "length exceeded"), CONTEXT_OVERFLOW, False),
    (("timeout", "timed out", "timedout"), TIMEOUT, True),
    (("overloaded", "service unavailable", "internal server error",
      "gateway"), SERVER_ERROR, True),
    (("connection", "econnrefused", "network", "unreachable", "ssl", "dns",
      "refused"), NETWORK_ERROR, True),
]


def _as_int(value: Any) -> int | None:
    """Best-effort int conversion (accepts int, str, float)."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _try_json(text: str) -> Any:
    """Best-effort JSON parse of a provider body; None when not JSON."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _dig_message(parsed: Any, fallback: str) -> str:
    """Pull a human message out of a parsed provider body."""
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict):
            type_part = str(err.get("type", "")).strip()
            msg = str(err.get("message", "")).strip()
            combined = f"{type_part} {msg}".strip()
            if combined:
                return combined
        msg = parsed.get("message") or parsed.get("detail") or parsed.get("error")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
    return fallback


def _clean_text(text: str, limit: int = 220) -> str:
    """Human-friendly version of a raw error string — provider prefix and any
    JSON payload reduced to its message, whitespace collapsed, truncated."""
    t = (text or "").strip()
    if not t:
        return ""
    parsed = _try_json(t)
    if parsed is not None:
        t = _dig_message(parsed, t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[: limit - 1].rstrip() + "…"
    return t


def _classify(status: int | None, text: str) -> tuple[str, bool]:
    """Classify a raw provider error into (code, retryable).

    Status codes win when defined for that status; otherwise content
    keywords (case-insensitive) decide; otherwise generic.
    """
    if status is not None and status in _STATUS_CODES:
        return _STATUS_CODES[status]
    lowered = (text or "").lower()
    for patterns, code, retryable in _KEYWORD_RULES:
        if any(p in lowered for p in patterns):
            return code, retryable
    return GENERIC_ERROR, False


def _extract(raw: Any) -> tuple[str | None, int | None, str, Any]:
    """Pull (provider, status, body_text, raw_for_debug) out of any input."""
    if isinstance(raw, dict):
        provider = raw.get("provider")
        status = _as_int(raw.get("status_code") or raw.get("status") or raw.get("http_status"))
        text = str(raw.get("message") or raw.get("detail") or "")
        err = raw.get("error")
        if isinstance(err, dict):
            text = f"{err.get('type', '')} {err.get('message', '')}".strip() or text
        # Re-normalizing an already-canonical dict must keep the ORIGINAL raw
        # (the debug surface), not wrap itself.
        raw_src = raw.get("raw", raw)
        return provider, status, text, raw_src
    if isinstance(raw, Exception):
        return None, None, f"{type(raw).__name__}: {raw}", raw
    text = str(raw)
    match = _PROVIDER_ERROR_RE.match(text)
    if match:
        provider = match.group("provider")
        status = _as_int(match.group("status"))
        body = match.group("rest").lstrip(": ").strip()
        parsed = _try_json(body)
        if parsed is not None:
            body = _dig_message(parsed, body)
        return provider, status, body, text
    return None, None, text, text


def normalize_error(
    raw: Any,
    *,
    source_hint: str | None = None,
) -> dict[str, Any]:
    """Normalize a raw provider/adapter error into the canonical shape.

    `raw` may be the adapter's `{provider} returned {status}: {body}` string,
    a plain string, an already-parsed provider dict, or an exception.

    `source_hint` forces the source when the caller knows the error's domain
    (e.g. `source_hint="internal"` for upload failures) — provider keyword
    classification is skipped so a "connection reset" inside an upload error
    isn't mislabeled as a provider outage.
    """
    provider, status, text, raw_src = _extract(raw)

    if source_hint == SOURCE_INTERNAL:
        return {
            "status": "error",
            "source": SOURCE_INTERNAL,
            "provider": provider,
            "code": GENERIC_ERROR,
            "message": _clean_text(text) or "Something went wrong.",
            "retryable": False,
            "raw": raw_src,
        }

    code, retryable = _classify(status, text)
    if code == GENERIC_ERROR:
        source = SOURCE_INTERNAL
        message = _clean_text(text) or "Something went wrong."
    else:
        source = SOURCE_PROVIDER
        message = _MESSAGES.get(code, "") or _clean_text(text)

    return {
        "status": "error",
        "source": source,
        "provider": provider,
        "code": code,
        "message": message,
        "retryable": retryable,
        "raw": raw_src,
    }


def is_canonical_error(value: Any) -> bool:
    """True when `value` looks like the canonical error object already."""
    return (
        isinstance(value, dict)
        and value.get("status") == "error"
        and bool(value.get("code"))
        and bool(value.get("message"))
    )

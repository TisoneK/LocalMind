"""Canonical provider-error normalization (ADR-20 + ADR-21).

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

ADR-21 (Session 169) makes the classifier genuinely provider-agnostic —
ANY model's error JSON envelope normalizes, not just Zen's:

1. **Structured error-type catalog first.** Providers name their errors in
   the JSON envelope (`error.type` / `error.code`): OpenAI
   `insufficient_quota`, Anthropic `rate_limit_error` / `overloaded_error`,
   Zen `FreeUsageLimitError`, Azure string codes ("429"), … The token is
   the strongest signal — it is consulted BEFORE the HTTP status and the
   prose keywords, because it is explicit semantics that survives across
   providers even when the message text differs. Unknown tokens fall
   through to status → keywords → generic (a new provider degrades
   gracefully instead of mislabeling).
2. **Envelope walking.** Common JSON shapes are dug the same way: top-level
   `error` dict, double-nested `error.error` (proxies/gateways), the
   `errors` plural list, `error` as a plain string (Ollama), top-level
   `code` (Azure). A purely numeric token is treated as the HTTP status.
3. **Provider-shaped errors stay provider.** An error that clearly came
   from a provider envelope (name parsed or status present) keeps
   `source="model_provider"` even when the code is generic — the UI says
   "the model provider", not an anonymous internal error.
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
    # Anthropic's overload status (review fix, Session 169).
    529: (SERVER_ERROR, True),
}

# Provider error-type/code tokens → canonical code (ADR-21). The provider's
# OWN named error type (from `error.type` / `error.code` in the JSON
# envelope) is the strongest classification signal — stronger than the HTTP
# status or prose keywords, because it is explicit semantics that survives
# across providers. Tokens are matched lowercased. Covers the shapes we've
# seen: OpenAI (insufficient_quota / tokens_exceeded / requests /
# context_length_exceeded / invalid_api_key), Anthropic (rate_limit_error /
# overloaded_error / not_found_error / request_too_large / api_error), Zen
# (FreeUsageLimitError), and the common Azure/gateway codes. Unknown tokens
# fall through to status → keywords → generic.
_ERROR_TYPE_RULES: dict[str, tuple[str, bool]] = {
    # rate limits & usage quotas
    "rate_limit_exceeded": (RATE_LIMIT, True),
    "rate_limit_error": (RATE_LIMIT, True),
    "rate_limit_reached": (RATE_LIMIT, True),
    "insufficient_quota": (RATE_LIMIT, True),  # OpenAI 429-class quota
    "quota_exceeded": (RATE_LIMIT, True),
    "requests": (RATE_LIMIT, True),  # OpenAI 429 per-minute request type
    "tokens_exceeded": (RATE_LIMIT, True),  # OpenAI 429 per-minute token type
    "freeusagelimiterror": (RATE_LIMIT, True),  # Zen
    "toomanyrequests": (RATE_LIMIT, True),
    # auth / permissions
    "authentication_error": (AUTH_ERROR, False),
    "invalid_api_key": (AUTH_ERROR, False),
    "invalid_key": (AUTH_ERROR, False),
    "permission_error": (AUTH_ERROR, False),
    "access_denied": (AUTH_ERROR, False),
    "forbidden": (AUTH_ERROR, False),
    # billing
    "billing_error": (PAYMENT_REQUIRED, False),
    "billing_not_active": (PAYMENT_REQUIRED, False),
    "insufficient_balance": (PAYMENT_REQUIRED, False),
    "payment_required": (PAYMENT_REQUIRED, False),
    # model availability
    "model_not_found": (MODEL_NOT_FOUND, False),
    "no_such_model": (MODEL_NOT_FOUND, False),
    "not_found_error": (MODEL_NOT_FOUND, False),
    # context window
    "context_length_exceeded": (CONTEXT_OVERFLOW, False),
    "request_too_large": (CONTEXT_OVERFLOW, False),
    "max_context_length": (CONTEXT_OVERFLOW, False),
    "maximum_context_length_exceeded": (CONTEXT_OVERFLOW, False),
    # timeouts
    "timeout": (TIMEOUT, True),
    "timeout_error": (TIMEOUT, True),
    "request_timeout": (TIMEOUT, True),
    "gateway_timeout": (TIMEOUT, True),
    # server / overload
    "server_error": (SERVER_ERROR, True),
    "api_error": (SERVER_ERROR, True),
    "overloaded_error": (SERVER_ERROR, True),
    "engine_overloaded": (SERVER_ERROR, True),
    "temporary_overload": (SERVER_ERROR, True),
    "internal_error": (SERVER_ERROR, True),
    "service_unavailable": (SERVER_ERROR, True),
    "origin_unavailable": (SERVER_ERROR, True),
    "upstream_error": (SERVER_ERROR, True),
    "invalid_response": (SERVER_ERROR, True),
    # network
    "connection_error": (NETWORK_ERROR, True),
    "connection_closed": (NETWORK_ERROR, True),
    "network_error": (NETWORK_ERROR, True),
    "unreachable": (NETWORK_ERROR, True),
    "dns_error": (NETWORK_ERROR, True),
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


def _walk_error(parsed: Any) -> Any:
    """Return the innermost error payload of a parsed provider body.

    Handles the common envelopes (ADR-21): the top-level ``error`` dict, the
    ``errors`` plural list (first element), double-nested ``error.error``
    (proxies/gateways), and ``error`` as a plain string (Ollama). Non-dict
    input is returned unchanged.
    """
    err = parsed
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if err is None:
            err = parsed.get("errors")
        if isinstance(err, list) and err:
            err = err[0]
    for _ in range(3):
        if not isinstance(err, dict):
            break
        nested = err.get("error")
        if not isinstance(nested, dict):
            break
        err = nested
    return err


def _dig_type(parsed: Any) -> str:
    """Pull a normalized (lowercased) error-type/code token from a body.

    Prefers ``error.type``; when the type is a generic bucket that misses
    the catalog (OpenAI uses ``invalid_request_error`` as the type for many
    errors), falls back to ``error.code`` — OpenAI carries the specific
    subtype there (``context_length_exceeded``, ``invalid_api_key``,
    ``model_not_found``). Top-level ``code`` (Azure) is the last resort.
    """
    err = _walk_error(parsed)
    type_tok = code_tok = ""
    if isinstance(err, dict):
        type_tok = str(err.get("type") or "").strip().lower()
        code_tok = str(err.get("code") or "").strip().lower()
    if not type_tok and not code_tok and isinstance(parsed, dict):
        code_tok = str(parsed.get("code") or "").strip().lower()
    if type_tok in _ERROR_TYPE_RULES:
        return type_tok
    if code_tok:
        return code_tok
    return type_tok


def _dig_message(parsed: Any, fallback: str) -> str:
    """Pull a human message out of a parsed provider body."""
    if not isinstance(parsed, dict):
        return fallback
    err = _walk_error(parsed)
    if isinstance(err, dict):
        type_part = str(err.get("type") or err.get("code") or "").strip()
        msg = str(err.get("message") or "").strip()
        combined = f"{type_part} {msg}".strip()
        if combined:
            return combined
    msg = parsed.get("message") or parsed.get("detail") or parsed.get("error")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    return fallback


def _cap_raw(value: Any, limit: int = 2000) -> Any:
    """Cap string raws so an unbounded direct input can't bloat the SSE
    event; non-strings (dicts from caller-parsed payloads) pass through."""
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 1] + "…"
    return value


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


def _classify(
    status: int | None,
    text: str,
    type_token: str = "",
) -> tuple[str, bool]:
    """Classify a raw provider error into (code, retryable).

    Priority (ADR-21, provider-agnostic): the provider's own structured
    error-type/code token first (explicit semantics), then the HTTP status,
    then content keywords; generic as the last resort.
    """
    if type_token:
        rule = _ERROR_TYPE_RULES.get(type_token)
        if rule:
            return rule
    if status is not None and status in _STATUS_CODES:
        return _STATUS_CODES[status]
    lowered = (text or "").lower()
    for patterns, code, retryable in _KEYWORD_RULES:
        if any(p in lowered for p in patterns):
            return code, retryable
    return GENERIC_ERROR, False


def _extract(raw: Any) -> tuple[str | None, int | None, str, str, Any]:
    """Pull (provider, status, body_text, type_token, raw_for_debug) from any
    input."""
    if isinstance(raw, dict):
        provider = raw.get("provider")
        status = _as_int(
            raw.get("status_code") or raw.get("status") or raw.get("http_status")
        )
        text = str(raw.get("message") or raw.get("detail") or "")
        type_token = _dig_type(raw)
        if not text:
            text = _dig_message(raw, text)
        # Azure-style numeric codes ("429") act as the HTTP status; the
        # token is always cleared so it can't linger into classification.
        num = _as_int(type_token)
        if num is not None and 100 <= num <= 599:
            if status is None:
                status = num
            type_token = ""
        # Re-normalizing an already-canonical dict must keep the ORIGINAL raw
        # (the debug surface), not wrap itself.
        raw_src = raw.get("raw", raw)
        return provider, status, text, type_token, raw_src
    if isinstance(raw, Exception):
        # raw must stay JSON-serializable — the canonical object can reach
        # chat.py's json.dumps. str(raw) keeps the debug surface without the
        # un-serializable exception object (review fix, Session 168).
        return None, None, f"{type(raw).__name__}: {raw}", "", str(raw)
    text = str(raw)
    match = _PROVIDER_ERROR_RE.match(text)
    if match:
        provider = match.group("provider")
        status = _as_int(match.group("status"))
        body = match.group("rest").lstrip(": ").strip()
        type_token = ""
        parsed = _try_json(body)
        if parsed is not None:
            type_token = _dig_type(parsed)
            body = _dig_message(parsed, body)
            num = _as_int(type_token)
            if num is not None and 100 <= num <= 599:
                if status is None:
                    status = num
                type_token = ""
        return provider, status, body, type_token, text
    return None, None, text, "", text


def normalize_error(
    raw: Any,
    *,
    source_hint: str | None = None,
) -> dict[str, Any]:
    """Normalize a raw provider/adapter error into the canonical shape.

    `raw` may be the adapter's `{provider} returned {status}: {body}` string,
    a plain string, an already-parsed provider dict, or an exception. It may
    be ANY provider's error payload — OpenAI, Anthropic, Ollama, Zen, Azure,
    or a future one — the classifier is envelope-agnostic (ADR-21).

    `source_hint` forces the source when the caller knows the error's domain
    (e.g. `source_hint="internal"` for upload failures) — provider keyword
    classification is skipped so a "connection reset" inside an upload error
    isn't mislabeled as a provider outage.

    Already-canonical input is passed through untouched (review fix, Session
    168): re-classifying the FRIENDLY message would round-trip rate_limit/
    context_overflow/network_error (whose messages contain their own
    keywords) but flip auth_error/timeout/server_error/model_not_found to
    generic "error" (source→internal, retryable→false).
    """
    if is_canonical_error(raw):
        return raw

    provider, status, text, type_token, raw_src = _extract(raw)

    if source_hint == SOURCE_INTERNAL:
        return {
            "status": "error",
            "source": SOURCE_INTERNAL,
            "provider": provider,
            "code": GENERIC_ERROR,
            "message": _clean_text(text) or "Something went wrong.",
            "retryable": False,
            "raw": _cap_raw(raw_src),
        }

    code, retryable = _classify(status, text, type_token)
    if code == GENERIC_ERROR:
        # Provider-shaped errors (name parsed or status present) still belong
        # to the provider domain — the UI should say "the model provider",
        # not an anonymous internal error (ADR-21).
        source = (
            SOURCE_PROVIDER if (provider or status is not None) else SOURCE_INTERNAL
        )
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
        "raw": _cap_raw(raw_src),
    }


def is_canonical_error(value: Any) -> bool:
    """True when `value` looks like the canonical error object already."""
    return (
        isinstance(value, dict)
        and value.get("status") == "error"
        and bool(value.get("code"))
        and bool(value.get("message"))
    )

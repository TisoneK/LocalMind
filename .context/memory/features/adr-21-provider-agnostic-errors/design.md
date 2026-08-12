# ADR-21 Design — Provider-Agnostic Error Normalization

**Status:** LOCKED (Session 169 — user: "This isn't just about zen, any
model's response in json should be handled"; chose provider-agnostic
errors). **Ledger:** `.context/memory/features/ledger.md`.

---

## 1. Problem — ADR-20's classifier leaned on Zen's shape

ADR-20 built the canonical error pipeline and verified it live on the Zen
429 payload. But "handle ANY model's error JSON" has four gaps:

| Gap | Today (ADR-20) | Why it breaks other providers |
|---|---|---|
| Error-type/code tokens | folded into prose + keyword-scanned | OpenAI `insufficient_quota` (429-class quota) matched "insufficient" → mislabeled `payment_required`; Anthropic `not_found_error` matched nothing; `api_error`/`overloaded_error`/`request_too_large` missed without their prose |
| Envelope digging | only `error.{type,message}` | misses `error.code` (OpenAI/Anthropic), `errors[]` lists, double-nested `error.error` (proxies), Azure `{"code":"429"}` string codes |
| Adapter truncation | `body[:200]` in `openai_compat.py` (3 sites) | long JSON envelopes cut mid-parse → `_try_json` fails → keyword scan on a mangled prefix |
| Generic source | generic → `source=internal` always | a provider envelope that fails classification shows "internal error" |

## 2. Design — structured signals first, envelope-agnostic digging

The provider's own named error type is **explicit semantics** — it survives
across providers even when the prose differs. So classification priority
becomes:

```
1. error.type / error.code token  → _ERROR_TYPE_RULES catalog
2. HTTP status code               → _STATUS_CODES table (existing)
3. message prose keywords         → _KEYWORD_RULES table (existing)
4. generic (cleaned provider text)
```

### 2.1 Token catalog (`_ERROR_TYPE_RULES`, lowercased)

Rate limit: `rate_limit_exceeded`, `rate_limit_error`, `rate_limit_reached`,
`insufficient_quota` (OpenAI 429-class quota → `rate_limit`, retryable),
`quota_exceeded`, `requests` (OpenAI 429 type), `tokens_exceeded` (OpenAI
429 per-minute tokens), `freeusagelimiterror` (Zen), `toomanyrequests`.

Auth: `authentication_error`, `invalid_api_key`, `invalid_key`,
`permission_error`, `access_denied`, `forbidden`.

Billing: `billing_error`, `billing_not_active`, `insufficient_balance`,
`payment_required`.

Model: `model_not_found`, `no_such_model`, `not_found_error` (Anthropic).

Context: `context_length_exceeded`, `request_too_large` (Anthropic),
`max_context_length`, `maximum_context_length_exceeded`.

Timeout: `timeout`, `timeout_error`, `request_timeout`, `gateway_timeout`.

Server: `server_error`, `api_error`, `overloaded_error` (Anthropic 529),
`engine_overloaded`, `temporary_overload`, `internal_error`,
`service_unavailable`, `origin_unavailable`, `upstream_error`,
`invalid_response`.

Network: `connection_error`, `connection_closed`, `network_error`,
`unreachable`, `dns_error`.

Unknown tokens fall through to status → keywords → generic: a new provider
degrades gracefully instead of mislabeling.

### 2.2 Envelope walking (`_walk_error` / `_dig_type` / `_dig_message`)

One walker handles every shape seen so far (descends at most 3 levels):

- `{"error": {dict}}` — OpenAI / Anthropic / Zen
- `{"type": "error", "error": {dict}}` — Anthropic
- `{"error": {"error": {dict}}}` — double-nested proxies/gateways
- `{"errors": [{...}]}` — plural list, first element
- `{"error": "<string>"}` — Ollama
- `{"code": "429", "message": "..."}` — Azure (top-level code)
- `{"error": {"code": "429", "message": "..."}}` — Azure (nested string code)

`_dig_type` returns `error.type` **or** `error.code` (or top-level `code`),
lowercased. A purely numeric token (Azure `"429"`) is treated as the HTTP
status. `_dig_message` combines `type/code + message` for prose fallback.

### 2.3 Provider-shaped generic errors stay `source=model_provider`

When the input clearly came from a provider (name parsed from
`{provider} returned {status}:` or a dict with `provider`/`status`, or an
HTTP status present) but nothing classifies, `source` stays
`model_provider` with the cleaned provider text as the message — the UI
says "the model provider", not an anonymous internal error. Plain strings
with no provider signal still default to `internal`.

### 2.4 Adapter truncation `[:200]` → `[:1000]`

`openai_compat.py` builds error strings with `body[:200]` (3 sites: stream
open, stream loop, Anthropic). 200 chars cuts most real JSON envelopes.
Bump to `[:1000]` — error bodies only (never success streams); the
normalizer's `_clean_text` still caps the user-facing message at ~220
chars, and `raw` (the debug surface) may now carry the fuller envelope.

## 3. No-regression list (must hold)

- Canonical shape unchanged (`status/source/provider/code/message/retryable/raw`).
- All ADR-20 normalizer tests untouched and green (classification table,
  canonical passthrough, internal-source override, JSON-safe raw, friendly
  messages).
- `chunk.error` remains a string for every non-SSE consumer.
- `source_hint="internal"` (upload failures) still forces internal +
  generic, skipping provider classification.
- Frontend untouched — reuses the existing canonical codes + ErrorMessage card.

## 4. Build order

1. **Session 169** — normalizer: token catalog, envelope walkers, type-first
   classify, provider-shaped source; adapter truncation bump; provider
   matrix tests (OpenAI quota/API-key/context, Anthropic rate-limit/overload/
   not-found/too-large, Ollama string envelopes, Azure string + dict codes,
   double-nested, `errors[]`, unknown-token fallbacks, long-body parse).
2. **Session 170** — full backend regression (1468 green), deepseek-flash
   review, close out + push. Live smoke stays pending on a live provider
   (Zen completions still 429 — same as ADR-19/20).

**Session 169 review fixes (recorded so design/code don't drift):**
- HTTP **529** added to `_STATUS_CODES` → `server_error` (Anthropic's
  overload status; a plain-bodied 529 previously fell to generic).
- `_dig_type` now prefers `error.type` but falls back to `error.code` when
  the type is a generic bucket that misses the catalog — OpenAI carries the
  specific subtype in `code` (`context_length_exceeded`, `invalid_api_key`,
  `model_not_found`) under the `invalid_request_error` type.
- `raw` capped at 2000 chars in the canonical output (unbounded direct
  inputs could bloat the SSE event; `message` was already capped at 220).
- Numeric tokens ("429") are always cleared after status promotion, not
  only when no status was present.
- Known tradeoff: CLI chat/ask print `chunk.error` verbatim and now receive
  up to 1000 chars instead of 200 — bounded, acceptable for a dev tool.

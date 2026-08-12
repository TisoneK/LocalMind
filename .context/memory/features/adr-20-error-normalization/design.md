# ADR-20 Design — Error Normalization + Presentation Layer

**Status:** LOCKED (Session 165 — user briefed the full design; no open
decisions). **Ledger:** `.context/memory/features/ledger.md`.

---

## 1. Problem — raw provider payloads leak into the conversation UI

During the ADR-19 live smoke the chat surfaced, verbatim:

```
zen returned 429: {"type":"error","error":{"type":"FreeUsageLimitError","message":"Error from provider (Console): Rate limit exceeded. Please try again later."}}
```

The user saw an API payload, not an explanation. The principle they set:

> **Never expose provider-specific error payloads directly in the
> conversation UI.** Whether it comes from Zen, Anthropic, OpenAI, Ollama,
> etc., the user should see what happened, why it happened, and what they
> can do next — not an API error dump. The raw provider response belongs in
> developer/debug details, not the chat.

Today there is NO normalization anywhere on the path:

| Layer | Today | Problem |
|---|---|---|
| Adapter | `f"{provider} returned {status}: {body[:200]}"` (`openai_compat.py:969`) | provider-specific; body JSON embedded in a string; truncated at 200 chars |
| Engine | `StreamChunk(error=<string>)` forwarded untouched | — |
| SSE | `{"type":"error","error":"<raw string>"}` (`chat.py:406`, `:526`) | frontend can't classify; raw dump |
| Frontend | `case 'error': content += \`⚠️ ${parsed.error}\`` (`useLocalMind.ts:1056`) | renders the raw string into the bubble |

## 2. What exists today (honest baseline)

- **Adapter errors:** `openai_compat.py:969-972` (non-200 on streaming open),
  `:1540-1545` (non-200 in stream), `:1648-1653` (Anthropic), `ollama.py`
  `:316-326` / `:484-493` (`"Ollama returned {status}: {raw_error}"` + the
  friendly 404 model-missing message). 429s get transparent retry
  (`_send_streaming_with_retry`, up to 3 attempts, `Retry-After` honored).
- **SSE error events:** `chat.py:406` (`chunk.error` — the authoritative
  signal; adapters yield `text=""` on error), `chat.py:526` (uncaught
  exception: also emits a `token` `"⚠️ An error occurred: {exc[:200]}"`),
  `chat.py:687` (upload failure).
- **Frontend:** `useLocalMind.ts:1056` `case 'error'` appends
  `⚠️ {parsed.error}` to the assistant bubble content (partial content is
  preserved and the error appended below it — a deliberate Session ~90 fix);
  `onError` (transport-level) writes a generic string. `ChatMessage.tsx`
  renders content as markdown — so the raw JSON renders as monospace text.
- **Other consumers of `chunk.error` (strings):** CLI chat/ask, title
  generator, reflection mixin, orchestrator, summarizer, memory extractor,
  dispatcher, sub_agent, agent loop — all `logger.warning(..., [:120])`.
  They must NOT see a dict.

## 3. Design — normalize at the presentation boundary only

Two-layer model, exactly per the user's brief:

```
Provider  ──►  Adapter (raw error string)  ──►  Engine (chunk.error, string)
                                                        │
                                    SSE presentation boundary (chat.py)
                                                        │
                                                        ▼
                                          normalize_error(raw)   ← pure, deterministic
                                                        │
                                                        ▼
                              {"type":"error","error": {canonical}}
                                                        │
                                                        ▼
                            Frontend ErrorMessage card (friendly UI)
```

- **`chunk.error` stays a string everywhere.** All internal consumers (logs,
  CLI, synthesizer, memory) are untouched — zero regression surface.
- **Normalization happens once, at the SSE boundary** (`chat.py`), where the
  user-facing contract begins.
- **The raw provider response is retained** in the canonical object's `raw`
  field (and in server logs) for debugging — it just never renders as content.

### 3.1 Canonical shape (`backend/src/core/error_normalizer.py`)

```python
{
  "status": "error",
  "source": "model_provider",        # "model_provider" | "internal"
  "provider": "zen",                 # parsed from the string; None if unknown
  "code": "rate_limit",              # canonical classification (below)
  "message": "The model provider has temporarily reached its usage limit. Try again in a few minutes or switch to another model.",
  "retryable": true,                 # drives the UI's primary action
  "raw": "<original string, kept for logs/debug>"
}
```

### 3.2 Classification table (status-code first, then content keywords)

| Signal | code | retryable | source |
|---|---|---|---|
| HTTP 429 / "rate limit" / "FreeUsageLimitError" / "usage limit" / "too many requests" / "throttl" | `rate_limit` | ✅ | model_provider |
| HTTP 401/403 / "invalid api key" / "unauthorized" / "authentication" / "permission" | `auth_error` | ❌ | model_provider |
| HTTP 402 / "insufficient" / "billing" / "quota" (billing sense) | `payment_required` | ❌ | model_provider |
| HTTP 404 + model / "model not found" / "model '...' could not be loaded" / "does not exist" | `model_not_found` | ❌ | model_provider |
| HTTP 400 + context/token/length / "context_length" / "maximum context" / "too many tokens" / "prompt is too long" | `context_overflow` | ❌ | model_provider |
| HTTP 408/504 / "timeout" / "timed out" | `timeout` | ✅ | model_provider |
| HTTP 5xx / "overloaded" / "service unavailable" / "internal server error" | `server_error` | ✅ | model_provider |
| "connection" / "refused" / "econnrefused" / "network" / "unreachable" / "ssl" | `network_error` | ✅ | model_provider |
| nothing above matches | `error` | ❌ | internal |

Friendly `message` per code (defaults when no provider detail survives):
- `rate_limit` → "The model provider has temporarily reached its usage limit. Try again in a few minutes or switch to another model."
- `auth_error` → "The model provider rejected the access credentials. Check the API key in Settings."
- `payment_required` → "The model provider requires payment or a quota top-up before it can respond."
- `model_not_found` → "The selected model is not available on this provider. Pick a different model."
- `context_overflow` → "The conversation is too long for the selected model's context window. Start a new chat or switch to a model with a larger context."
- `timeout` → "The model provider took too long to respond. Try again."
- `server_error` → "The model provider is temporarily unavailable. Try again in a moment."
- `network_error` → "Couldn't reach the model provider. Check your network connection and try again."
- `error` → the cleaned original (provider prefix stripped, truncated to ~200 chars) — never the raw JSON dump.

**Parsing** (pure string work, no I/O): if the input is a string matching
`^(?P<provider>\w+)\s+returned\s+(?P<status>\d{3}):\s*(?P<body>.*)$`
(openai_compat + ollama format), extract provider + status, then try to
parse `body` as JSON and dig out `error.type` / `error.message` (e.g.
`FreeUsageLimitError`) for keyword classification. Dict inputs are used
directly when already canonical, else classified from their string fields.
Exception inputs use `type(exc).__name__ + str(exc)`.

### 3.3 SSE boundary (`backend/src/api/routes/chat.py`)

- `:406` → `yield _sse({"type": "error", "error": normalize_error(chunk.error)})`
- `:526` exception path → normalize `str(exc)`; ALSO soften the leaked
  `token` line from `"⚠️ An error occurred: {exc[:200]}"` to a generic
  `"⚠️ An error occurred. See the details below."` (the canonical error card
  carries the real message — no raw exception in content).
- `:687` upload failure → normalized with `source="internal"`.

### 3.4 Frontend

- **types** (`frontend/src/types/index.ts`): `ModelError` interface
  (`status/source/provider?/code/message/retryable/raw?`) + `error?: ModelError`
  on `ChatMessage`.
- **hook** (`useLocalMind.ts` `case 'error'`): if `parsed.error` is an object
  → store it as `message.error` (do NOT touch `content`); if it's a string
  (legacy backend) → existing `⚠️` append fallback stays.
- **component** (`frontend/src/components/chat/ErrorMessage.tsx`): friendly
  card — red/amber-tinted rounded panel, warning icon, headline
  ("Unable to get a response"), canonical message, meta row
  (`Provider · Code · Retryable badge`), actions
  (**Try again** → `onRetry`; **Switch model** → dispatch
  `localmind:open-model-selector`), and a collapsed
  `<details>` "Technical details" showing `raw` (the developer/debug surface).
- **wiring** (`ChatMessage.tsx`): render `message.error` card (assistant
  messages) above content. LeftPanel listens for
  `localmind:open-model-selector` and opens the `ModelSelector`.

## 4. Build order (each step deterministic + unit-testable)

1. **Backend normalizer** — `error_normalizer.py` + full classification
   table + friendly messages + tests (`tests/core/test_error_normalizer.py`).
   ✅ Session 165
2. **SSE wiring** — `chat.py` normalization at both error sites + softened
   exception token + API tests updated (`tests/api/test_chat.py`).
   ✅ Session 166
3. **Frontend** — `ModelError` type, hook stores canonical error, `ErrorMessage`
   component + `localmind:open-model-selector` event, `ChatMessage` wiring,
   vitest coverage. ✅ Session 167
4. **Regression + live smoke + close out** — full backend suite 1437 green +
   frontend vitest 105 green, deepseek-flash review (3 fixes: canonical
   passthrough short-circuit, JSON-safe exception `raw`, friendly persisted
   exception text), live smoke — Zen 429 persists for completions but the
   canonical error emission was verified LIVE end-to-end. ✅ Session 168

**Session 168 review fixes (recorded so design/code don't drift):**
- `normalize_error` short-circuits on `is_canonical_error(raw)` — re-
  classifying the FRIENDLY message would round-trip rate_limit/
  context_overflow/network_error but flip auth_error/timeout/server_error/
  model_not_found to generic (source→internal, retryable→false).
- Exception `raw` coerced to `str()` — canonical output must survive
  `json.dumps` (the SSE wire).
- The chat.py exception token now carries the canonical friendly message
  (so `_guarantee_persist_assistant` persists a useful line), while the raw
  exception stays out of content.

## 5. No-regression list (must hold)

- `chunk.error` remains a **string** for every non-SSE consumer (CLI chat/ask
  `console.print`, title_generator, reflection, orchestrator, summarizer,
  memory, dispatcher, sub_agent, agent loop `[:120]` logging).
- Frontend string-error fallback preserved — old backends still render.
- Partial-content + error append behavior preserved for legacy strings.
- `tests/api/test_chat.py:249` error-event assertions updated in place.
- Session 31 "always yield text on the silent-failure path" contract: the
  `token` + `error` + `done` guarantee on the exception path is kept, only
  the leaked raw text is softened.

## 6. Explicitly out of scope (later)

- Normalizing TOOL errors (web_fetch 429, git errors) — they already carry
  friendly messages; this ADR is about model/provider errors.
- Backend-driven retry UX (auto-retry button) — the `retryable` flag is the
  data hook for it; wiring a full retry loop is a later slice.
- Per-provider error catalog (structured codes per provider) — the keyword
  table covers today's providers; extend as providers are added.

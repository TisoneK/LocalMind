# Feature: adr-21-provider-agnostic-errors

Goal: implement **ADR-21** — make the ADR-20 error normalizer genuinely
provider-agnostic: **any model's error JSON envelope** (OpenAI, Anthropic,
Ollama, Zen, Azure, gateways, and future providers) normalizes into the
same canonical error card, whatever the envelope shape.

Trigger (user thread, 2026-08-12, Session 169): *"This isn't just about
zen, any model's response in json should be handled."* ADR-20's normalizer
was verified live on the Zen 429 payload, but it leaned on prose keywords
and the `{provider} returned {status}: {body}` string shape. Gaps for other
providers:

1. **Structured error-type/code tokens** (`error.type` / `error.code` in
   the JSON envelope — OpenAI `insufficient_quota`, Anthropic
   `rate_limit_error` / `overloaded_error` / `not_found_error` /
   `request_too_large`, Zen `FreeUsageLimitError`, Azure string codes)
   weren't consulted as first-class signals — only as keyword text.
2. **Envelope digging** missed `error.code`, the `errors[]` plural list,
   double-nested `error.error` (proxies/gateways), and top-level `code`
   (Azure `{"code": "429"}`).
3. **Adapters truncated bodies at 200 chars** (`[:200]` in
   `openai_compat.py`) so a long JSON envelope was cut mid-JSON and
   couldn't parse at all.
4. A provider-shaped error that failed classification was labeled
   `source=internal` — the UI said "internal error" for something the
   provider actually returned.

**Started:** 2026-08-12 (Session 169)
**Branch:** main
**Status:** P0 IMPLEMENTED (Sessions 169-170): `_ERROR_TYPE_RULES` catalog
(~45 tokens), `_walk_error`/`_dig_type` envelope walking (error dict,
`errors[]`, double-nested, error-as-string, top-level code, numeric-code-as-
status), type-token-first classification order (token → status → keywords →
generic), code-token fallback when the type is a generic bucket (OpenAI
`invalid_request_error` + `code=context_length_exceeded`), provider-shaped
generic errors keep `source=model_provider`, adapter body truncation
`[:200]` → `[:1000]`. Review fixes (Session 169): HTTP 529 → server_error,
`raw` capped at 2000 chars, numeric token always cleared. Full backend
suite **1468 green**, ruff clean, deepseek-flash review passed, everything
pushed.
**Builds on:** ADR-20 (error_normalizer.py + SSE boundary + frontend
ErrorMessage card). Reuses the same canonical codes — **no frontend change
needed** (new handling produces the existing codes the card already renders).
**Session 171 hardening (6eebfaa):** the trivial/conversational fast-path
(`trivial_input.py` Session 153 fallback) embedded the RAW adapter string
into the fallback TEXT (the exact "zen returned 429: {…}" bubble the user
reported), bypassing SSE normalization entirely. Fallback text now embeds
the canonical friendly message; the raw error is forwarded on
`chunk.error` so the SSE boundary emits the canonical error object → the
ErrorMessage card renders; clean text keeps the Session 153 visible-text +
persistence guarantees. Loop.py empty-response fallbacks audited clean.
Live-verified via /api/chat ("hi"): token = friendly sentence, error event
= canonical rate_limit with raw confined to debug. 1469 backend green.
**Session 172 audit (full fallback-text sweep):** every `chunk.error` site
and `{exc}` text construction in backend/src checked. Safe: all error-
forwarding sites ride the SSE `error` event (normalized); logger sites;
chat.py exception/upload paths (already normalized);
`_summarize_trace_for_user`/`_synthesis_failure_fallback`/work report only
surface tool evidence; tool-level `{exc}` content is tool-result territory
(out of ADR-20 scope). ONE leak found + fixed: `workspace/orchestrator.py`
outer except could embed an adapter exception (provider-shaped) raw in the
bubble — now normalized (friendly text + raw on `chunk.error`). 3 new
tests. 1472 backend green.
**No-regression list:** canonical shape unchanged; string inputs, dict
inputs, exception inputs, canonical passthrough, `source_hint=internal`
override all preserved (ADR-20 tests untouched and green); `chunk.error`
remains a string for every non-SSE consumer; adapter error strings still
truncated (now 1000 chars — only error bodies, never success streams).
**Flaw-log rule:** normalizer stays pure + deterministic — the provider
matrix is fully unit-tested without a live model; the live smoke
(`scripts/smoke_gate.py`) is the only provider-dependent step and stays
pending while Zen is rate-limited.

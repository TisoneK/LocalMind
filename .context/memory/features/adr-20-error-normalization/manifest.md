# Feature: adr-20-error-normalization

Goal: implement **ADR-20** — normalize provider/model errors into a canonical,
human-friendly shape at the presentation boundary and render them as a
polished error card in the chat UI, never as raw API payloads.

Trigger (user thread, 2026-08-12, Session 165): during the ADR-19 live smoke
the UI surfaced the raw Zen provider error verbatim —
`zen returned 429: {"type":"error","error":{"type":"FreeUsageLimitError","message":"Error from provider (Console): Rate limit exceeded. Please try again later."}}`
— an API dump in the conversation. The user's principle: **"Never expose
provider-specific error payloads directly in the conversation UI. Whether it
comes from Zen, Anthropic, OpenAI, Ollama — the user should see what happened,
why it happened, and what they can do next. The raw provider response belongs
in developer/debug details, not the chat."**

Today the whole path is raw strings: `openai_compat.py:969-972` builds
`f"{provider} returned {status}: {body[:200]}"` → `StreamChunk(error=...)` →
engine → `chat.py:406` emits `{"type":"error","error":"<raw>"}` →
`useLocalMind.ts:1056` does `⚠️ ${parsed.error}` into the message content.

**Started:** 2026-08-12 (Session 165)
**Branch:** main
**Status:** P0 IMPLEMENTED (Sessions 165-168): error_normalizer.py (`f261ef0`), SSE boundary wiring (`6cd514f`), frontend ErrorMessage card + ModelError type + switch-model event (`ca56845`), review fixes (canonical passthrough + JSON-safe raw + friendly persisted text). Full backend suite **1437 green**, frontend vitest **105 green**, ruff + tsc clean. LIVE SMOKE (Session 168): Zen still 429-limited for chat completions (models endpoint 200, completions rate-limited), BUT the pipeline was live-verified — the exact user-reported error now emits the canonical `rate_limit` object with the friendly message and the raw payload confined to `raw`. Remaining: none for P0; the full successful-turn smoke stays pending on a live provider (same as ADR-19).
**Builds on:** nothing new — sits at the SSE presentation boundary; keeps
`chunk.error` (string) unchanged for all internal consumers (CLI, logs,
synthesizer, memory). Supersedes nothing; complements ADR-18 (TaskState) and
ADR-19 (task-aware context) whose provider-blocked live smokes motivated it.
**No-regression list:** `chunk.error` stays a string everywhere except the SSE
boundary; existing error-string consumers (CLI chat/ask, title_generator,
_reflection_mixin, orchestrator, summarizer, memory, dispatcher, sub_agent,
loop) untouched; frontend string-error fallback (legacy `⚠️` content append)
kept for old backends; `tests/api/test_chat.py` error-event assertions updated
in place (canonical shape).
**Flaw-log rule:** normalizer is pure + deterministic — fully unit-testable
without a live model; the live smoke (reuse `scripts/smoke_gate.py`) is the
only provider-dependent step and stays pending if Zen is still 429-limited.

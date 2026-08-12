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
**Status:** ACTIVE — Session 165: design + backend normalizer + tests.
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

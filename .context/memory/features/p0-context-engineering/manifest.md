# Feature: p0-context-engineering — Minimum Sufficient Context (P0)

**Started:** 2026-09-03 (Session 410) · **Status:** active · **Sessions:** 410, 411, 412, 414, 415, 416+

## What this feature is

The P0 Context Engineering milestone: make LocalMind's parent loop send
**minimum sufficient context** per call instead of dumping available state.
Grounded in two research reports:

- `.context/memory/reviews/2026-09-03-prompt-audit.md` — measured the outgoing
  payload (per-call floor ~3.3K tool schemas + ~2.7K system prompt; tool-result
  history growth 91→4228 tokens in one research turn).
- `.context/memory/reviews/2026-09-04-context-architecture-research.md` (+
  `-addendum.md`) — mature-harness patterns (layered context, provider prefix
  caching, checkpoint compaction, tool scoping, clean internal agents) and the
  8-step Implementation Plan. The addendum (confirmed by the user 2026-09-04)
  is the authoritative plan: hybrid Tool-Result Index + Search (stub + pointer
  + FTS5+vec0), NOT Context Mode's zero-inline.

## Implementation plan (addendum-refined, priority order)

1. **Step 1 — Surface cache data to the UI** (1 session) ← S416 in progress
2. **Step 2 — Byte-stabilize the system prefix** (1-2 sessions)
3. **Step 3 — Memory Retrieval Gate** (1-2 sessions)
4. **Step 4 — Tool-Result Index + Search** (hybrid FTS5+vec0, 2-3 sessions) — NEW from addendum
5. **Step 5 — Checkpoint Compaction** (deterministic TOC, 2-3 sessions)
6. **Step 6 — Context Budget Manager** (2-3 sessions)
7. **Step 7 — Instruction Epoch** (2-3 sessions)
8. **Step 8 — Internal Agent Pattern** (1 session)

## Progress log

- **S410** (`ec5521c`): compactor tighten — keep_last 4→1, stub 600→400.
  Peak history 4228→1749 (59%). Live-verified qwen3.8-flash.
- **S411** (`1bbe2e6`): schema diet — 6 rare tools behind describe_tool
  (~903 tok/call saved). Cumulative tokens 48,790→38,967 (20.1%).
- **S412** (`a1e7c68`): stale tool references fixed + dynamic tier list
  (bug-fix session; prompt diet deferred).
- **S414** (`4cce4f6`): P0 architecture research (no code). Key finding:
  bankofai/qwen3.8-flash DOES pass prompt caching (81.5% hit live); frontend
  shows undiscounted `prompt_tokens_approx` — cache data never reaches UI.
- **S415** (`c0de368`): research addendum — Claude Context Engine taxonomy +
  Context Mode MCP source verification; hybrid recommendation; plan refined to
  8 steps. **User confirmed (2026-09-04 chat): addendum = the plan; hybrid
  architecture approved; start Step 1.**
- **S416** (`05e332f`): **Step 1 DONE** — cache telemetry → UI. Loop usage
  accumulator (`total_*` accumulate; occupancy keys last-call; `llm_calls`),
  turn_complete + /api/metrics + metrics re-emit carry `cached_tokens`/
  `llm_calls`; frontend cached chip (hit %, hidden when unreported) + calls
  chip + context-meter cached share. 14 new tests; LIVE-verified bankofai/
  qwen3.8-flash isolated 8765: SSE total_cached 5120/6790 (75.6% hit).

## Constraints / do-not-regress

- ADR-40 guardrail: live-verify tool SELECTION on a weak model after any
  schema cut.
- ADR-53 Parent-only scope.
- ADR-56/57: Thinker stays; calls streamed+concurrent+gated.
- S206 trivial→zero-provider-call boundary.
- Live-testing bar (workflows/active.md): unit tests insufficient — live
  before/after trace on real provider, isolated port 8765, never 8000.
- bankofai/deepseek-v4-flash is now PAID (balance=0); use hy3 / glm-5.3-flash /
  qwen3.8-flash (free tier on bankofai).

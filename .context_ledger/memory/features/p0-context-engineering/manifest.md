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

1. **Step 1 — Surface cache data to the UI** (1 session) ✅ DONE (S416)
2. **Step 2 — Byte-stabilize the system prefix** (1-2 sessions) ✅ DONE (S418 + S421 folded the CHAT branch)
3. **Step 3 — Memory Retrieval Gate** (1-2 sessions) ✅ DONE (S419)
4. **Step 4 — Tool-Result Index + Search** (hybrid FTS5+vec0, 2-3 sessions) — NEW from addendum ← slice 1 DONE; slice 2 (loop wiring) next
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
- **S416 addendum** (`7b9c039`): user-reported meter bug fixed — the Context
  meter divided session-cumulative prompt by the per-call window (false 100%
  after 4 turns); now measures the LAST call's prompt + same-basis cached
  chip. Live-verified 4-turn trace: 10,977/32,768 = 33%, cached 56%.
  qwen3.8-flash missing from MODEL_CONTEXT_WINDOWS → B-2026-09-04-1.

- **S445** (`6d53f6c3`): agent-intelligence slice adjacent to this feature — the deferred S412 prompt-diet finding was re-aimed by discovery: the giant execution prompt + planner are the PARKED branch (parent turns run the native-bootstrap surface); the live fixes were the serial fast-path consult skip (live 5.5s→1.7s), advisory route/plan wording, honest chat capability. Per-tool-rules-into-descriptions stays a Step-3+ candidate.

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
- **S418** (`05e365c`): **Step 2 DONE** — byte-stable system prefix. NEW
  build_agent_intent_tail renders persona/skill/agent-ctx/plan/routing-hint/
  current-intent AFTER the cacheable prefix (loop injects into turn-context,
  non-native turns); baseline keeps safety (Session-32 contract). 15 new
  stability tests; 147/147 prompt-context suites. HONEST FINDING: the hot
  path (native parent) was already byte-stable — variance lived on the
  delegated/planned branch; A/B on bankofai 81%=81% (block-granular cache).
- **S419** (`38739c5`): **Step 3 DONE** — Memory Retrieval Gate. Scoping
  finding: retrieval was ALREADY per-request, conditional, semantic top-K
  (_MAX_FACTS=6) + relevance-thresholded — the "inject-all dump" was already
  gone. Missing Component-5 piece was a TOKEN budget: added cap_facts_to_budget
  (~500 tok) at agent_runtime._memory_facts. 5 cap tests + 50 memory regression.
- **S421** (`cd7fd48`): **Step 2b DONE** — folded the Intent.CHAT branch into
  the byte-stable baseline+tail split. The chat prefix embedded the boot-cached
  env summary + memory + intent history — busting caching AND sending env TWICE
  per chat turn (the loop's turn_context_parts is unconditional). Prefix is now
  identity + HOW-TO-RESPOND only. Byte-stability test repointed; ruff clean.
- **S446** (`7392173`): **Step 4 slice 1 DONE** — the tool-result index
  storage engine. New storage/tool_result_index.py::ToolResultIndex — hybrid
  FTS5 (porter+trigram, external-content) + vec0 over size-gated (>5 KB),
  heading-aware chunks; hybrid search with Reciprocal Rank Fusion + tool/session
  filters; safe FTS MATCH from arbitrary text. NOT wired to the loop (slice 2).
  Live-verified vs mxbai-embed-large (dim=1024, vec_rows==chunks); fixed a 4 KB
  chunk overrunning the ~512-tok embed window by capping embed input to 1800
  chars. 15 hermetic unit tests. **Slice 2 next:** register the
  search_tool_results agent tool + replace >5 KB tool results with a stub +
  pointer in the loop; live before/after on a research turn (target 91→~500 tok).

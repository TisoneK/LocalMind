# Current Task

**Status:** IDLE — Session 324 (silent Thinker — filter-before-render for the ADR-42 consult) shipped and live-verified.

## Session 324 outcome — the Thinker leak fix

- **Reported (user's transcript + screenshot):** "Thinker's raw internal monologue is leaking into the visible
  transcript" — the ADR-42 Thinker's reasoning rendered into the Thinking block on ALL models because no
  filter-before-render step existed. The model echoed its own Thinker prompt ("You are the Thinker — SILENT and
  READ-ONLY…", "Output: exactly one JSON object"), mused about the JSON structure, and reasoned about loop-internal
  nudges ("The user request is meta: …") — all visible to the user.
- **Root cause (code):** `loop.py` forwarded every `thinking` chunk from `Thinker.consult()` straight to the SSE
  thinking stream (`yield StreamChunk(text="", thinking=_tc.thinking)`). The `_JSON_MARKERS` filter in thinker.py
  only stopped at the JSON tail — the prose prompt-echoes before it still surfaced.
- **Shipped (`db5bfdc`):** (1) `thinker.py` — the consult buffers the model's output internally for parsing only and
  yields NO user-visible chunks (removed the JSON-marker surfacing machinery); (2) `loop.py` — drains the consult
  silently; the render boundary is now explicit. The structured analysis still flows to the agent's context
  (`_thinker_context_block`), to `trace.thinker_analysis` (degraded fallback), and the lifecycle is still reported via
  `agent_thinker_start`/`done` obs events (next_step + facts/ambiguities counts). Tests: silent-contract test in
  `test_thinker.py` + loop-level regression in `test_tool_force_recovery.py` (Thinker reasoning never reaches the
  user's stream even when the consult runs on real evidence).
- **Live-verified (bankofai/deepseek-v4-flash, isolated 8765):** consult RAN (`agent_thinker_start`/`done` at
  iteration 1, next_step drove the mkdir + file_write) yet **0 of 210 user-visible thinking tokens** contained any
  Thinker-prompt or JSON-structure marker. Main agent's genuine thinking still streams (feature).
- **Bankofai clarification (from the transcript's "still wired to bankofai, not dropped" flag):** the provider was
  RENAMED bai → bankofai (Sessions 319-322, user's "drop b.ai" = drop the b.ai DOMAIN, use api.bankofai.io), NOT
  removed. It is intentionally the active provider being tested. No code change; the footer
  "deepseek-v4-flash · bankofai" is correct.
- **Verification:** full backend 2078 passed / 2 skipped / 0 failures; ruff + pre-commit gate (tsc + ruff) clean.

## Next

- **B-2026-08-20-20 (Medium):** deepseek 500-chunk reasoning-then-empty ends turn via provider-error fallback.
- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 on iter=1 → empty bubble.

**Feature:** none (single-session loop fix)
**ADR:** none
**Review:** `.context/memory/reviews/2026-08-20-review-90.md`

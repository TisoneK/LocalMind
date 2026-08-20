# Current Task

**Status:** IDLE — Session 323 (task-anchored recovery nudges + creation-commitment detection) shipped and live-verified.

## Session 323 outcome — the "model feels clever but the agent is limited" fix

- **Target:** user's real parent-turn trace (deepseek-v4-flash via bankofai, "create a new coding project in dev/{name}/"):
  the model planned well but narrated tool intent instead of calling tools; the task-blind tool-talk nudge ("call the
  tool now") bounced it back into `ls`/`Get-ChildItem` re-recon — 2 turns, 8 tool steps, zero files.
- **Shipped (`3880cfc`):**
  1. `_recovery_nudge_tail(loop_messages, trace)` in `loop.py` — appends the user's ORIGINAL request (Session 314
     pattern) plus, when tools already ran this turn, an advancement hint ("do NOT repeat them — call the tool that
     takes the NEXT step") to the three task-blind nudges (tool-talk, forced-tool, empty-response).
  2. Creation-commitment pattern in `_TOOL_TALK_PATTERNS` (`text_tools.py`) — catches "I'll create/write the project
     files…" narration with no tool call (requires creation verb + file-like noun; allows one adjective word).
- **Regression tests:** `tests/core/test_task_anchored_nudges.py` (3) + creation-commitment cases in
  `tests/core/test_dsml_interception.py`.
- **Live-verified (bankofai/deepseek-v4-flash, isolated 8765, 3 traces):** trace 1 — narration → anchored nudge →
  `mkdir` (no re-recon, vs the user's re-recon loop); trace 2 — "Now I'll write the project files" caught by the new
  pattern → real verified `file_write` (pyproject.toml); trace 3 hit the separate deepseek 500-chunk-reasoning-then-empty
  quirk (Session 31/256 territory) → B-2026-08-20-20 backlogged.
- **Verification:** full backend 2077 passed / 2 skipped / 0 failures; ruff clean; pre-commit gate (tsc + ruff) passed.
  Note: the pre-existing `test_parent_recovery_cap.py` import failure (B-2026-08-20-19) no longer reproduces (3 passed).

## Next

- **B-2026-08-20-20 (Medium):** deepseek-v4-flash streamed 500 reasoning chunks then nothing — turn ended with only the
  provider-error fallback message (live trace 3). Investigate converting this case into the empty-reasoning recovery
  instead of the generic provider-error message.
- **B-2026-08-20-10 (High):** MiniMax XML interception conflicts with prose-commitment detector.
- **B-2026-08-20-11 (Medium):** 429 on iter=1 → empty bubble.

**Feature:** none (single-session loop fix)
**ADR:** none
**Review:** `.context/memory/reviews/2026-08-20-review-89.md`

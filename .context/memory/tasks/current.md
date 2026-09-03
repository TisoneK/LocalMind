# Current Task

**Status:** IDLE — Session 409 COMPLETE: ADR-57 slice 2 (Thinker value-gating)
shipped. Post-tool consult now honors its long-documented once-per-turn
contract (`not _thinker_consulted`, finally wired) and the pre-tool consult is
skipped on DIRECT_RETRIEVAL_INTENTS. Measured 3 reflexive Thinker calls on one
research turn; the once-guard drops the redundant re-fires. Verified by 2 new
deterministic tests that FAIL on HEAD and pass on the fix (4→1 starts on a
synthetic 3-tool turn), 1573 core+api green, ruff unchanged, and a live
gemini-2.5-flash trace (post-tool fired once). Commits ae722e4 + 12a97a0,
pushed to main.

**Feature:** none

## Notes for the next session

- **ADR-57 slice 3 = serial→concurrent.** The pre-tool Thinker consult still
  runs SERIAL before the first model call (adds its round-trip to time-to-
  first-action). The next lever is to run it concurrently with the first
  model call, or fold it in. Also: parallel tools + parallel `delegate`
  sub-agents. Map which LLM calls are independent (Open-Q1).
- **Live-test providers (2026-09-03):** bankofai/**deepseek-v4-flash is now
  PAID** (balance=0 errors) — but the free model **hy3** runs on the same
  bankofai provider: `--adapter bankofai --model hy3` (256K ctx, free). Also
  free: glm-5.3-flash, qwen3.8-flash. zai key 401-expired; chutes/cerebras out
  of credit; gemini-2.5-flash works. NOTE: the app settings.json `adapter`
  wins over `LOCALMIND_ADAPTER` env, so the harness writes adapter+model into
  the scratch settings (`--adapter`/`--model`).
- **Honest note:** real web queries classify as parent-intent ANALYZE, so the
  pre-tool intent-skip mostly helps bare direct-intent turns; the post-tool
  once-guard is the effective win. If more pre-tool savings are wanted, the
  clean path is slice 3 (concurrency), not a brittle message-complexity
  classifier (CONV-05/06/11 regression surface).
- Standing: ~41 unattributed full-suite failures + 34-error ruff baseline
  still need a peer pass (S405-407); live-test port 8010 for the user app
  backend (never 8000).

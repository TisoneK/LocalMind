# Current Task

**Status:** IDLE — Session 409 fully closed (addendum 2). ADR-57 slice 2
(Thinker value-gating) shipped in `ae722e4` and the cut-off HEAD-vs-FIX A/B is
resolved WITHOUT new runs: the evidence was `scratch/sse-stream-tg2-base.sse`
vs `tg2-fix.sse` (bankofai/hy3, identical WEB-1 python prompt). Ground truth
from raw SSE grep: BASE 3 tools -> **3 Thinker starts** (iter 0, 2, 3 —
redundant re-fire at 3); FIX 5 tools -> **2 starts** (iter 0, 2) — the
once-guard held across MORE tools. No product code changed in the closeout;
session-log pointers + inefficiency entry committed.

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
- **Evidence discipline (new, from inefficiencies log):** cite the scratch
  sse/results file path for every measurement IN the session log at capture
  time; confirm provider/model from the server's `parent-kernel] ready
  adapter=... model=...` line, not from what the log body assumed.
- **Harness caveat:** `results-*.json` thinker-count under-counts (SSE line
  framing) — raw `grep -o '"agent_thinker_start".*iteration": [0-9]*'` on the
  .sse file is ground truth.
- Standing: ~41 unattributed full-suite failures + 34-error ruff baseline
  still need a peer pass (S405-407); live-test port 8010 for the user app
  backend (never 8000).

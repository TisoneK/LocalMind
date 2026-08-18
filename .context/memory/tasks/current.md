# Current Task

**Status:** Session 295 (MULTIAGENT token/speed optimization) DONE. 2 safe wins
shipped + live-verified; full ranked roadmap backlogged. Suite 1937/0. Pushed.

## Method
3 isolated-context general-purpose subagents investigated in PARALLEL (INPUT
tokens / OUTPUT-runtime tokens / LATENCY); orchestrator captured the live
baseline + serialized implementation + verification. Worked well.

## Baseline (glm-4.5-flash create task)
7 LLM calls / ~26s / 10,176 cumulative tokens — the model did shell ls+echo>+cat
instead of one file_write (L2 steering gap) and each call carried ~6,365 fixed
tokens (tool info sent 3×).

## Shipped (safe, verified)
- `6e6de38`~1 Ollama warmup at real num_ctx → no 13-29s first-turn reload.
- `6e6de38` dropped redundant env "## Available Tools" prose on execute path
  (~279 tok/call).

## Next (ranked roadmap — review-62, B-2026-08-17-8..12)
Each needs a CLEAN before/after live trace (glm-4.5-flash + phi4-mini spot-check),
ADR-40 guardrail:
1. **B-2026-08-17-12 (STEERING, biggest per-task latency win):** parent-path
   (intent=ANALYZE) create→file_write + don't-exploratory-shell/cat steering —
   collapses the baseline's ~4 wasted shell calls to one file_write.
2. **B-2026-08-17-9 (B1, HIGH output tokens):** cap file_read injection
   512KB→~32KB (up to ~120K tokens/large read) + B2 uniform choke-point cap.
3. **B-2026-08-17-11 (C3, biggest per-turn latency):** fold classify+first-action
   3→2 calls — ADR-46-guarded (whitelisted read-only first action only).
4. B-2026-08-17-8 (A2/A4 in-prompt list + scaffold trim); B-2026-08-17-10 (C2
   init/memory overlap).

**Load-bearing, DO NOT touch:** init call (ADR-46 gate), iter-1 synthesis,
Thinker gate (already off for Ollama), slow-provider budgets (ADR-45).

**Feature:** none

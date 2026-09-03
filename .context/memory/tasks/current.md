# Current Task

**Status:** IDLE — P0 Context Engineering step 1 (tool-result history compaction)
delivered (Session 410, commit `ec5521c`). KEEP_LAST_TOOL_RESULTS 4→1 +
STUB_MAX_CHARS 600→400, live-verified on bankofai/qwen3.8-flash: peak
history 4228→1749 (59% reduction on iter 5), research turn 41.8s→37.25s,
no behavioral regression (same 5 iters + 5 web_fetch calls + final answer).
3 new regression tests pin the new defaults. Next: step 2 (tool-schema diet)
per the audit's priority order.

**Feature:** `p0-context-engineering` (preview)

## Notes for the next session

- **P0 step 2 — tool-schema diet** (~-1.5→2K per call): extend ADR-40's
  describe_tool pattern to more of the 18 core tools. The audit measured
  ~3.3K tokens of tool schemas carried on EVERY agent-loop call (18 defs,
  ~185 tokens each). Keep web_search/memory_op/shell; push file_task/browse/
  code_exec variants behind on-demand load. **CONSTRAINT: ADR-40 guardrail**
  — never cut schemas without live-verified tool SELECTION on a weak model
  (z.ai/glm-4.5-flash OR bankofai/qwen3.8-flash). Re-run
  `scripts/live_test_prompt_audit.py --adapter bankofai` before/after — the
  audit harness IS the verification tool for this milestone.
- **P0 step 3 — system-prompt diet** (~-0.8→1K per call): audit the
  agent-phase prompt's sections against observed failure modes; several
  "capability notes" are restated in multiple sections. The system prompt is
  ~2.7K per agent call (8.5KB chars).
- **P0 step 4 — session-level context budgeting** (structural): the six-layer
  model request (core system / current task / required capabilities /
  relevant history / relevant memory / task state) — the user's proposed
  Context Budget Manager as a first-class component.
- **Prompt-audit usage:** set `LOCALMIND_PROMPT_AUDIT=scratch/prompt-audit.jsonl`
  in the harness env; JSONL per model call + `.last-payload.json` full dump;
  `[prompt-audit]` lines appear in the server log. Zero cost when unset.
- **Live-test providers (2026-09-03, re-probed):** bankofai free models =
  **hy3, glm-5.3-flash, qwen3.8-flash** (`--adapter bankofai --model X`);
  everything bigger 403s "Deposit required"; deepseek-v4-flash 429s (paid).
  **gemini-2.5-flash: one full agent turn consumes the per-minute quota** —
  space A/B runs ~5min+. chutes auth OK but $0; zai 401; cerebras 403.
  **Session 410 verified qwen3.8-flash works for the audit harness.**
- **ADR-57 slice 3 (serial->concurrent Thinker) is queued but competes**
  with the P0 milestone; the user's framing says P0 first. The Thinker's
  remaining post-tool consult (~5s) should be re-measured under the token
  lens too.
- **Standing:** ~41 unattributed full-suite failures + 34-error ruff baseline
  still need a peer pass (S405-407); live-test port 8010 for the user app
  backend (never 8000). GitHub Dependabot: 3 vulns on main (2 high, 1 moderate)
  still untriaged — surface on every push.
- **Session 410 environment quirks (logged to inefficiencies/log.md):**
  (1) bankofai transient 400 on replan calls — re-run to confirm transient
  before investigating; (2) backgrounded `nohup ... &` dies immediately in
  this sandbox — run live-tests synchronously with a long timeout; (3) the
  Bash tool resets working directory each call — use `git -C <path>` or
  absolute paths, not `cd && ...`.

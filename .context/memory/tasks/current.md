# Current Task

**Status:** IDLE — P0 Context Engineering step 2 (tool-schema diet) delivered
(Session 411, commit `1bbe2e6`). 6 tools moved from CORE to LONG_TAIL
(git, process, web_research, observe, sysinfo, calculator) — ~903 tok/call
saved. ADR-40 guardrail satisfied: live-verified tool SELECTION on
bankofai/qwen3.8-flash (weak model). Cumulative P0 reduction (S410+S411):
total session tokens 48,790 → 38,967 (20.1%), tools per call 3,332 → 2,386
(28.4%), peak history 4,228 → 1,598 (62.2%). Next: step 3 (system-prompt
diet) per the audit's priority order.

**Feature:** `p0-context-engineering` (preview)

## Notes for the next session

- **P0 step 3 — system-prompt diet** (~-0.8→1K per call): audit the
  agent-phase prompt's sections against observed failure modes; several
  "capability notes" are restated in multiple sections. The system prompt is
  ~2.7K per agent call (8.5KB chars). File: `backend/src/core/agent/prompts.py`
  + `backend/src/core/prompts/base.md` + `backend/src/core/prompts/chat.md`.
  Re-run `scripts/live_test_prompt_audit.py --adapter bankofai` before/after —
  the audit harness IS the verification tool for this milestone.
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
  **S410 + S411 verified qwen3.8-flash works for the audit harness.**
- **ADR-57 slice 3 (serial->concurrent Thinker) is queued but competes**
  with the P0 milestone; the user's framing says P0 first. The Thinker's
  remaining post-tool consult (~5s) should be re-measured under the token
  lens too.
- **Standing:** ~41 unattributed full-suite failures + 32-error ruff baseline
  (S411 auto-fixed 2 I001 errors in test_describe_tool_on_demand.py; was 34)
  still need a peer pass (S405-407); live-test port 8010 for the user app
  backend (never 8000). GitHub Dependabot: **4 vulns on main (3 high, 1
  moderate)** — up from 3 at S410 push; a new vulnerability appeared. Still
  untriaged; surface on every push.
- **Session 410 + 411 environment quirks (logged to inefficiencies/log.md +
  environments.md):** (1) bankofai transient 400 on replan calls — re-run to
  confirm transient before investigating; (2) backgrounded `nohup ... &` dies
  immediately in this sandbox — run live-tests synchronously with a long
  timeout; (3) the Bash tool resets working directory each call — use `git -C
  <path>` or absolute paths, not `cd && ...`.
- **Session 411 variance note:** the first fix-2 run hit the iteration limit
  (6 iters) — looked like a regression but re-running fix-2b succeeded cleanly
  with 5 iters. The ADR-40 guardrail is about tool SELECTION (right tool,
  valid args), not iteration count. When a live-test shows an iteration-count
  increase, re-run to confirm variance before reverting.

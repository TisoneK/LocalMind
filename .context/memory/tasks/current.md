# Current Task

**Status:** IDLE — P0 Context Engineering step 3 (system-prompt diet) delivered
(Session 412, commit `a1e7c68`). Primarily a bug-fix session: corrected 3
stale references from S411 (hardcoded tool list → dynamic; Rule #6
web_research → web_search+web_fetch; Rule #9 browse → accurate on-demand
description). System prompt essentially unchanged (~2,680 tok/call, +6
within noise) — the bigger diet cuts (merging rules, trimming personas)
are deferred to a dedicated session with more live-testing capacity.
Next: step 4 (session-level context budgeting — structural) OR triage
the 4 Dependabot vulns.

**Feature:** `p0-context-engineering` (preview)

## Notes for the next session

- **P0 step 4 — session-level context budgeting** (structural): the six-layer
  model request (core system / current task / required capabilities /
  relevant history / relevant memory / task state) — the user's proposed
  Context Budget Manager as a first-class component. This is the biggest
  structural change in the P0 milestone and needs design work before
  implementation.
- **System-prompt diet (deferred bigger cuts):** merging CRITICAL RULES +
  COMPLETION ENFORCEMENT (redundant follow-through emphasis), trimming
  personas, cutting the "Your values" recap in base.md. These need A/B
  testing across multiple task types (research, coding, conversation) to
  verify no behavioral regression. Files: `backend/src/core/agent/prompts.py`
  + `backend/src/core/prompts/base.md`.
- **Prompt-audit usage:** set `LOCALMIND_PROMPT_AUDIT=scratch/prompt-audit.jsonl`
  in the harness env; JSONL per model call + `.last-payload.json` full dump.
- **Live-test providers:** bankofai free models = hy3, glm-5.3-flash,
  qwen3.8-flash. zai 401; cerebras 403; gemini quota-limited.
  **S410-S412 verified qwen3.8-flash works.**
- **Standing:** ~41 unattributed full-suite failures + 32-error ruff baseline
  (S411 auto-fixed 2; S412 didn't touch ruff baseline) need a peer pass.
  GitHub Dependabot: **4 vulns on main (3 high, 1 moderate)** — untriaged.
- **Cumulative P0 reduction (S410+S411+S412):** total session tokens
  48,790 → ~39,197 (19.7%), tools per call 3,332 → 2,386 (28.4%), peak
  history 4,228 → 1,598-1,709 (60-62%). System prompt unchanged (~2,680
  tok/call) — diet deferred.
- **Environment quirks (logged):** (1) bankofai transient 400 on replan —
  re-run to confirm; (2) bg processes die immediately — run sync; (3) Bash
  tool resets cwd — use `git -C` or absolute paths; (4) iteration-count
  variance — tool selection is the reliable signal, not iter count.

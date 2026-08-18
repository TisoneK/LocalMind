# Current Task

**Status:** DONE — Session 291. LIVE-tested the local (Ollama/phi4-mini) path
end-to-end, fixed the context meter for real, and fixed the 5 long-dismissed
"pre-existing" test failures at root. Full backend suite GREEN (1916 pass, 0
fail). All pushed.

**Shipped:**
- `325fd02` context meter: replaced all num_ctx size-tiering with ONE
  model-agnostic rule (declared window bounded by _DEFAULT_MAX_NUM_CTX=32768 or
  the user override); meter now 16% at 5K (was 64%). Hardened
  _extract_context_length (canonical arch key, excludes rope/original variants).
  Live-verified on real phi4-mini.
- `0606f70` fixed the 5 "pre-existing" fails at root (shell tests lacked the
  shell-enabled precondition; model_router didn't isolate from saved keys).
- Docs: environments.md records Ollama-installed + live-test recipe + phi4-mini
  quirks; changelog corrected; review-59.

**Live-proven root cause (S290 fix confirmed):** phi4-mini emits valid JSON
mode=direct with response:"" (greeting in acknowledgement) → old code escalated
direct-empty-response to execute → 247s hang. Execute is opt-in (ADR-46) + the
salvage recovers the acknowledgement → "Hi" answers direct, 0 tools, ~50s.

**Open next:**
1. B-2026-08-17-3 — format=json for classify: DEMOTED. Live evidence disproved
   the JSON-parse-failure hypothesis (phi4-mini's JSON was valid). Keep only as
   robustness for other models.
2. B-2026-08-17-4 — restore thinkMs/diffData/candidates on reload.
3. ADR-43 Phase 3 (progressive tool-schema disclosure) — now the TOP local-path
   perf lever: phi4-mini's execute loop is slow largely from the tool-schema
   prompt cost (a real tool task >2 min).

**Principles (do not regress):** tool loop is OPT-IN (ADR-46); fix
model/env-agnostically, never "for local" (preferences.md); LIVE-test the local
path (Ollama is installed — environments.md); never dismiss failures as
"pre-existing, not mine".

**Feature:** none

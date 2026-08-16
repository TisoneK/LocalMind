# Current Task

**Status:** idle — Session 251 completed (ADR-40 option B shipped + live-verified).

**Last completed:** Lean tool schemas (ADR-40 option B, B-2026-08-16-1): the 30-tool native catalog went 24,230 → 15,981 chars (~2,062 tok/call saved, 34%) via a new single-source `backend/src/core/agent/tool_schemas.py`; the in-prompt "Available tools" list now renders from the SAME defs (collapse of the 3 copies). Structural parity proven; guardrails kept; 6 new regression tests; full backend suite 1,770 passed (4 pre-existing env-gated shell fails). **Live-verified tool selection on z.ai/glm-4.5-flash (the active weak model) AND cerebras — correct tool (shell) with valid args, no regression.**

**Open next (implementation — its own session):** B-2026-08-16-2 per ADR-40 **option C** — on-demand full-tool-context for the long tail (browse/delegate/sql/csv/json/best_of_n/propose_*/subgoal/skill/diagnostics) using the `skill`-loader pattern (lean always-index + load-a-specific-tool's-full-schema when selected). Keep core tools (shell/file_task/file_write/edit_file/find_path/web_search/web_fetch/code_exec) always-present lean. Live-verify on a weak model + cerebras before claiming the win. ADR-37 follow-ups (B-2026-08-15-10/11/12) also remain open.

**Feature:** none

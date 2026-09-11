# Current Task

**Status:** IN PROGRESS — **Session 469 (Zawadi / glm-5.3-flash, ZCode local,
Windows): B-2026-08-25-4 — model leaks the internal "Worker report" format
into user-facing answers.**

**Task:** fix + live-verify. Root-cause read: `WorkReport.render()`
(`core/agent/models.py`) renders "Worker report — tool execution evidence: …"
as a deterministic USER-facing fallback appended when a tool-bearing answer
quotes no evidence; that appended block persists with the assistant message
and flows VERBATIM back into the model's own context (agent_runtime prompt
tail `history[-8:]`, ParentSession recent_tail, thinker history, memory
distill/resolver, social fast path). The model then mimics the format in
later answers (Session 401 py_count trace — the leak was inside a model token
event, no fallback involved).

**Fix shape:** (1) one canonical strip helper beside the format owner in
`models.py`; (2) strip at every model-facing history feed (the model never
reads the format back); (3) defense-in-depth strip of model-mimicked report
blocks at the loop's full-text emission sites (`_force_final_answer`,
`_rescue_final_answer`, buffered gate-flush), so `needs_report` fires on the
clean answer and the deterministic report stays the ONLY author of that
format. Live before/after per `system/live-testing.md` (bankofai free tier;
per-adapter model pin — qwen3.8-flash answers on this account).

Feature: none

# Current Task

**Status:** done — Session 274: shipped `todo_write` — the agent can now create,
update, and mark the live UI Todos panel (the user's report: "the todos are not
live on the ui by the agent, it cant set them, update nor mark them").

**Delivered (`506f958`, review-51):** the Todos panel was a passive projection of
the LLM's parsed plan (plan-required intents only, not agent-controllable — a
3-step task emitted ZERO todo events live). New first-class `todo_write` CORE tool:
the agent writes the FULL checklist (`todos:[{text,status}]`); the loop's
`_emit_todo_write_events` turns the result into the `todo_cleared`+`todo_created`
obs events the SSE bridge + frontend already render (status carried through so
in_progress shows — no frontend code change needed). A fast, single-purpose helper
that just parses/normalizes/returns, embodying ADR-43's "tools are helpers, not
agents" principle. LIVE-VERIFIED on glm-4.5-flash: agent called it, 0 validation
errors, status progressed pending→in_progress live. 1870 pass; +10 tests.

**Open next / notes:**
1. **Owed real-app visual check:** confirm the panel renders the agent's todos in
   the running app (I verified the SSE event stream + shapes; no frontend code
   changed since it already threads `status`). Also: a stronger model / clearer
   completion beat to exercise mark-`completed` live (mechanism is unit-tested).
2. **Still-open ADR-43 tools work:** B-2026-08-16-5 (L2 right-tool steering:
   exploratory `ls`/`Get-ChildItem` before create → `file_write`, `shell` for
   discovery → `find_path`; + L3 the redundant post-write read-back). Note: the
   find_path-over-ls guardrail already exists in prompts.py:736; the create-task
   "list then write" nudge at prompts.py:739 is the one to reconsider.
3. Carried: ADR-37 follow-ups B-2026-08-15-10/11/12; review-42 `classify_failure`
   cleanup; owed live Windows re-run of the S264 recipe task; unbounded
   `reasoning_effort` default. B-2026-08-16-4 (bound shell output) closed — already
   implemented (S272).

**Feature:** none

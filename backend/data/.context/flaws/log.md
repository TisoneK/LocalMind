# Flaws Log (append-only — what went wrong + what was learned)

The feedback loop. Every time something fails, log it here. If the
same failure happens twice, the flaw log wasn't consulted or the fix
wasn't applied — that's a process failure.

---
## 2026-07-26 — Silent failure at boundaries (early-development pattern)

- **Pattern:** nearly every bug found in early development was silent
  failure at a boundary — between sessions, between tools and
  generation, between reasoning and display, between adapters and
  unsupported params.
- **Root cause:** the pipeline was single-shot (classify → tool →
  generate → done) with no persistent state, no plan, no error
  surfacing at boundaries.
- **What was learned:** unit tests with clean inputs give false
  confidence. The bugs live at boundaries that unit tests don't
  exercise. E2e behavioral tests (session lifecycle, adapter contracts,
  tool failure paths) are needed to catch boundary bugs.
- **Fix applied:** the persistent-learning design (workflow constraints + failure memory).
  The `.context/` system + `workflows/` directory give the agent
  boundaries to reason within, and the learning step feeds back so
  the same failure doesn't recur.

---
## 2026-07-27 — UI dead air

- **Pattern:** the UI sat dead ("Thinking...") with no output while the
  engine worked. The user saw no progress, no plan, no indication of
  what was happening.
- **Root cause:** the todo API was a stub, the orchestrator's planner
  wrote to a scratch dir the UI never saw, and WEB_SEARCH was excluded
  from the orchestrator path.
- **What was learned:** the user needs to see what the agent is doing.
  A dead UI is worse than a slow UI — the user can't tell if it's
  working or hung. The todo plan system gives the UI
  real content to display.
- **Fix applied:** engine `_emit_todo_plan()` creates a per-intent
  plan and emits SSE events. The UI now shows the plan immediately.

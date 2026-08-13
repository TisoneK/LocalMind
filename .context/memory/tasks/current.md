# Current Task

- **Session:** 179 (2026-08-12)
- **Feature:** adr-19-task-aware-context
- **Task:** ADR-19 P1-P3 (context hierarchy, decision ledger, value scoring) — complete.
- **Done (176-179):**
  - **176** (`1ddf965`): ADR-18 P3 — delegation streaming/UX. `ChildObsProxy`
    forwards only tool_call/tool_status from sub-agents (tagged by agent
    name; child CHAT intent/metrics can't clobber parent UI);
    `delegation_started/completed` lifecycle events render as a running
    tool-step card; obs threaded through all dispatch sites; SSE bridge
    forwards the agent tag. Full backend **1503 green**.
  - **177** (`5f4f8a8`): ADR-19 P1 — context hierarchy + level-aware
    retrieval. Facts tagged with memory_level (turn/session/project/
    long_term); `level_priorities()` per task type; `store(level=)`,
    `compose(levels=)`, `retrieve_for_task()`; near-free level-aware
    re-retrieval after the pre-started parallel recall (embedding is
    LRU-cached per text). 18 tests. Full backend **1521 green**.
  - **178** (`c348633`): ADR-19 P2 — cross-session decision ledger.
    `decision_ledger` table (no FK to sessions — decisions outlive the
    session), record_decision (7-day near-dup suppression, 180-day prune),
    task-filtered recall_decisions, summarizer `decision_sink` write path,
    engine read path into memory_facts. 15 tests. Full backend **1536 green**.
  - **179** (`e2caafb`): ADR-19 P3 — LLM value scoring OPT-IN
    (LOCALMIND_LLM_VALUE_SCORING, default off). `score_messages()`
    bounded call (8s/40-msg/400-char; any failure → deterministic
    fallback); summarizer compresses the lowest-value slice instead of
    the oldest 50%; 8+ message pre-gate. 14 tests. Full backend
    **1550 green**.
- **ADR-19 is now complete (P0-P3).** Live smoke remains Zen-429 blocked
  per the flaw log (retry when a provider recovers or Ollama is
  installed); P1 is deterministic, P2/P3 fake-adapter tested.
- **Next:** per the user's "build pending ADRs one after the other" — the
  standing target remains ADR-8 agent-centric routing (Phases 2-4:
  build_context wiring, agent-initiated delegation, task-type classifier);
  ADR-20/21 are complete (error normalization). Confirm next ADR to pick
  up, or run the live smoke when a provider is available.

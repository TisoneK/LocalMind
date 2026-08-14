# Session 201 — Parent-agent runtime migration

## Request
Remove the request-time pipeline rather than mapping around it, and build LocalMind's own complete parent-agent execution flow. Codebuff/Freebuff were references only, not product names or agents.

## Implementation

- Deleted `backend/src/core/engine/_pipeline.py`.
- Added `backend/src/core/agent_runtime.py` and made `core.engine.Engine` an import-compatible alias of `AgentRuntime`.
- Added `backend/src/agents/parent/` with `ParentAgent`, parent context contract, full parent tool allowlist, and acceptance-gate stop condition.
- Moved request execution into `ParentAgent → BaseAgent.run() → shared AgentLoop`; the runtime retains lifecycle services only.
- Preserved persistence, memory retrieval, attachments, session CWD, safety blocks, stage/tool timings, failure memory, reflection, metrics, abort, steering, and terminal/session integration.
- Removed the request-time dispatcher/graph/direct branches and updated routing/prompt language so caller hints cannot bypass parent planning.
- Added/updated runtime and structural tests; updated architecture and changelog.

## Important correction

The parent agent is LocalMind's own `ParentAgent`. “Buffy” and “Codebuff/Freebuff” are reference implementations and research sources only; no Buffy-named product agent was introduced.

## Validation

`sh scripts/ci-check.sh` passed after the final edits:

- 1742 backend tests passed
- 2 tests skipped by contract for removed deterministic engine shortcuts
- Ruff clean
- frontend TypeScript clean
- ESLint 0 errors / 64 existing warnings

No real-model credentials were present for a new live smoke in this session; that limitation is recorded in review-6.

## Follow-up

A real-model smoke should exercise a normal parent tool call and a parent-initiated delegation task. Parallel mutation workspace safety and bounded parent-facing child results remain separate ADR-8 follow-ups.

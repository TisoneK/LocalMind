# Session 221 — addressed greeting routing notes

## Trigger

The user provided a LocalMind transcript showing `Hey LM` taking 36.3 seconds with `parent`, `Context Build 8.0s`, and `Generate 26.1s`, plus separate usage-limit/provider-unavailable conversations. The question was whether the agent loop was broken or whether LocalMind was actually making model calls.

## Trace

`AgentRuntime._process_unlocked()` checks `is_trivial_input()` before constructing the parent adapter. Pure social messages use canned replies with zero provider calls. `Hey LM` was not a match because `_GREETINGS` contained `hey+` as an anchored whole-message pattern, so the request continued through `build_context()` and `ParentAgent.run()`. The `Generate` timing therefore represented a real provider generation path, not a missing LLM call.

Terminal provider errors were traced separately. Direct conversational questions make one `adapter.chat()` call. Substantive parent turns use the planning/model loop. ADR-32's `TerminalProviderError` and runtime `chunk.error` forwarding prevent terminal pre-generation errors from being swallowed into a later generic fallback or another parent iteration. The existing focused tests cover 401/402/403, exhausted quota 429, transient 429 behavior, and runtime propagation.

## Change

Added an addressed-greeting pattern for `hi|hello|hey|heya` followed by `lm|localmind`. Added detector coverage and parameterized runtime coverage proving `Hi`, `Hey LM`, and `Hello LocalMind` do not acquire an adapter or enter `ParentAgent.run()`.

## Validation

Backend CI: 1,776 passed / 2 skipped. Focused suite: 124 passed. Frontend: 178 passed. TypeScript/build/Ruff passed. ESLint: 0 errors / 64 existing warnings. No live provider smoke due unavailable credentials.

## Follow-up interpretation

The remaining latency shown for real questions is provider/model latency, not evidence that the loop skipped the LLM. The UI should make direct-chat versus parent-agent execution mode more explicit in a future observability slice, but that is separate from this confirmed routing bug.

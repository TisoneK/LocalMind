# Current Task

**Status:** partial-done — Session 279: B-2026-08-16-10 (as-completed streaming for
parallel tool batches) IMPLEMENTED; as-completed ordering NOT live-verified.

**Delivered (`cf38bc0`, review-55):** the MultiToolCallResult path dispatched
concurrently but blocked on `asyncio.gather` and emitted all done-events together.
Now a per-task `_dispatch_and_emit` emits each tool's done/failed event as it
finishes; `asyncio.as_completed` + a yield-after-each flushes it to the user; the
model-context assembly is rebuilt in INPUT order. Also fixed a latent stale-`_inp`
args bug (every parallel tool's card showed the last call's args). Full suite 1875
pass, no regression.

**KEY FINDING (honest):** the user's models DON'T emit native parallel tool_calls.
glm-4.5-flash serialized; gemini-2.5-flash looped the `delegate_parallel` TOOL 4×
(invalid_input). So parallelism happens via delegate_parallel, not native batches —
B-10's native path rarely activates, and its as-completed ordering could NOT be
live-verified (the path never triggered). Not claiming "verified".

**Open next / notes:**
1. **B-2026-08-16-11 (from the finding):** (a) apply as-completed streaming to the
   delegate_parallel path (where parallelism actually happens); (b) audit
   delegate_parallel's arg schema — gemini couldn't satisfy it (4× invalid_input).
2. Owed: a focused loop-integration test driving MultiToolCallResult with two
   different-latency tools (heavy harness — deferred).
3. Carried: real-app visual checks (todo panel S274; narration on a content model);
   B-9 (create→FILE_WRITE, reasoning-driven); Windows re-run of S264 recipe.
   Closed: B-4 (S272), B-7 (S276), B-5/L3 (S277).

**Feature:** none

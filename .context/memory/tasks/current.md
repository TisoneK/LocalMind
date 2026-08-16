# Current Task

**Status:** done — Session 266: fixed the "leave a chat and come back, everything's
gone" bug class (context count, Actions pills, Thinking blocks, Error blocks).
Root cause was a persistence gap: the `messages` table stored only role/content,
so thinking/error/tool_calls/metrics were transient frontend state. Each assistant
message now persists all four; the history endpoint returns them (error normalized
at the boundary per ADR-20) and the frontend restores them on reload — including
`_seedSessionStats` rebuilding the cumulative context counter. Error turns now
persist at all (previously nothing). Commits `06ff072` `6d9f503` `fc34dbf` pushed
to main. Backend 1827 pass (4 pre-existing shell failures), frontend 226 pass,
tsc/build clean.

**Open next / notes:** unchanged from before — ADR-37 follow-ups
B-2026-08-15-10/11/12, review-42's `classify_failure` cleanup, owed live Windows
re-run of the Session 264 recipe task, unbounded `reasoning_effort` default.

**Feature:** none

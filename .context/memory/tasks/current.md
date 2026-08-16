# Current Task

**Status:** done — Session 267: made the Agents tab and Observe data persistent.
Two different persistence classes fixed: (1) the Agents tab run tree + phase
strip were frontend-only live state (cleared on every session switch, never
reloaded) — the runtime now rebuilds them server-side from the request's obs
events (`core/agent_workspace.py`, mirroring the frontend's delegation/evidence/
tool-attach logic) and persists them with the assistant message; the history
endpoint returns `agentRuns`/`agentPhases` and `useChat` restores the last
turn's tree. (2) Observe data lived in an in-memory engine dict that died on
backend restart — a new per-session `observations` table (merged metrics +
snapshot summary) is written at turn end and the observability endpoint falls
back to it on a cache miss. Commits `37f06ca` `732b6c6` `fe07d40` pushed to
main. Backend 1845 pass (4 pre-existing shell failures), frontend 229 pass,
tsc/build clean.

**Open next / notes:** unchanged from before — ADR-37 follow-ups
B-2026-08-15-10/11/12, review-42's `classify_failure` cleanup, owed live Windows
re-run of the Session 264 recipe task, unbounded `reasoning_effort` default.

**Feature:** none

# Current Task

**Status:** done — Session 271: small follow-up to Session 269 — the web_search
tool result now opens with `Search results via **<engine>** (N results):`
(DuckDuckGo / Bing / SearXNG / Brave), so the model (tool evidence) and the
user (Actions card output) both see which engine answered — previously only
`metadata.successful_provider` had it. Commit `b5ac1db` pushed. Backend 1858
pass (4 pre-existing shell failures), 18 web_search tests pass.

**Concurrency note:** a parallel research session (Claude Code, Session 270 —
ADR-43 tools optimization, context-only, marked done) committed in this same
checkout atop my commit; my push carried both commits and local == remote at
`2101935` with my `b5ac1db` intact. Its record is in sessions.md/SUMMARY.md.

**Open next / notes:** unchanged from before — ADR-37 follow-ups
B-2026-08-15-10/11/12, review-42's `classify_failure` cleanup, owed live Windows
re-run of the Session 264 recipe task, unbounded `reasoning_effort` default.
New: the research session's B-2026-08-16-4/5/6 (tools optimization — L1: bound
`shell` output first) is the next implementation candidate.

**Feature:** none

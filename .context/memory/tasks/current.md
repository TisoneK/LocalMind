# Current Task

**Status:** done — Session 268: fixed the web search tool. Root cause (verified
live): the SearXNG tier was dead — `searx.be` answers HTTP 200 with an Anubis
anti-bot HTML page, so every request raised a JSONDecodeError (the generic
except's `"json" in str(exc)` check never matched because str(JSONDecodeError)
drops the class name, leaking the raw parser error to the user). A live scan of
9 public instances found them ALL rate-limited/blocked/behind anti-bot; DDG
works, masking the dead tier until DDG is also blocked. Fix: SearXNG now walks
a fallback chain (configured `SEARXNG_URL`, comma-separated supported, first;
curated public fallbacks after; capped at 3 attempts), detects non-JSON
challenge pages via Content-Type, catches `json.JSONDecodeError` explicitly,
and DDG uses `asyncio.get_running_loop()` (deprecation). Commit `19a00d8`
pushed. Backend 1852 pass (4 pre-existing shell failures), 7 new web_search
tests.

**Open next / notes:** unchanged from before — ADR-37 follow-ups
B-2026-08-15-10/11/12, review-42's `classify_failure` cleanup, owed live Windows
re-run of the Session 264 recipe task, unbounded `reasoning_effort` default.
New: curated SearXNG fallbacks will churn too (already rate-limited today) —
a user-pinned private instance is the durable second-tier answer.

**Feature:** none

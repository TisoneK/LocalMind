# Current Task

**Status:** done — Session 269: added scraped Bing as the reliable no-key second
free tier for web search (follow-up to 268 — the SearXNG fallback chain churns
because public instances get rate-limited/blocked within days). DDG, Bing, and
SearXNG now race in parallel (first with results wins, others cancelled); Brave
remains the keyed premium fallback. Bing's `li.b_algo` organic blocks are
parsed, its `/ck/a` redirect URLs decoded back to the real destination
(html.unescape first, then `base64.b64decode(altchars=b'-_', validate=True)` —
`urlsafe_b64decode` lacks validate), and challenge/captcha pages detected.
Pinning `mkt=en-US&setlang=en` fixed garbage results in the first live test.
Commit `f721b9f` pushed. Backend 1858 pass (4 pre-existing shell failures), 6
new web_search tests.

**Open next / notes:** unchanged from before — ADR-37 follow-ups
B-2026-08-15-10/11/12, review-42's `classify_failure` cleanup, owed live Windows
re-run of the Session 264 recipe task, unbounded `reasoning_effort` default.
New: Bing scraping is ToS-gray and its HTML structure could change (`b_algo`
has been stable for years); a keyed API (Serper/Tavily) is the most durable
option if scraping ever breaks.

**Feature:** none

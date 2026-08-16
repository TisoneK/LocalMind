# Current Task

**Status:** done — Session 270 (RESEARCH, no product code): created the tools-
optimization research context, framed as **phase 3** of the sequential program
(agent loop → thinker backbone → **tools**).

**Delivered (`ADR-43` + `review-50` + `B-2026-08-16-4/5/6`):** the untouched cost
axis after ADR-40. A tool costs twice — INPUT (its schema in the `tools` param,
~68% solved by ADR-40) and RUNTIME (output-context tokens + latency). This
research is the RUNTIME axis, chiefly **output-context**. Disease in miniature:
`find_path` returns a bounded catalog; `shell` (shell.py:760) returns the ENTIRE
raw stdout uncapped — the helper-vs-raw-pipe asymmetry, and the fuel behind the
S262 "context too long" failure. Principle (user's): *tools are helpers, not
agents* — bounded, single-purpose, summary-sized output. Levers: L1 bound output
(start `shell`) · L2 right-tool steering (discovery→`find_path`, create→
`file_write`) · L3 drop the redundant read-back (duplicates the loop's own verify;
hit S264) · L4 uniform bounded observation contract.

**Open next / notes:**
1. **Implement the research:** B-2026-08-16-4 (bound `shell` output — biggest,
   safest win) → B-5 (steering + drop read-back) → B-6 (observation contract).
   Each phase needs a before/after live trace on z.ai/glm-4.5-flash (output
   tokens down, task still completes). Never touch port 8000; never print keys.
2. Carried from S269: ADR-37 follow-ups B-2026-08-15-10/11/12; review-42's
   `classify_failure` cleanup; **owed live Windows re-run of the Session 264
   recipe task**; unbounded `reasoning_effort` default (S262).
3. Working tree has S269's uncommitted `web_search.py` + test edits — not part of
   this research session; left untouched.

**Feature:** none

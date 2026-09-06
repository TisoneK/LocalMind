# Current Task

**Status:** IDLE — Session 429 closed. **Core updated 0.9.1 → 0.14.0**
(`38d58c0`, update + verify green; source verified before updating per the
S426 lesson — the 0.13.1 corruption was already repaired upstream). Two
package flaws found + logged: the `.ps1` update path skips the 0.13.0 zone
migration (history/, archive/, history.conf, agents/GROUP — installed
manually per the sh-port commands), and `context-mem lint` false-positives
on the root AGENTS.md digest. AGENTS.md digest + kickoff .cmd invocations
refreshed from the new templates; duplicate Super Z / GLM-5.2 registry row
merged (`context-mem check` now passes). **New session-start habit: core
0.14.0's Windows invocation is the `.cmd` launchers** (e.g.
`.context/core/bin/context-sync.cmd status`) — no execution-policy setup.

**Feature:** none

## Notes for the next session

- **IN FLIGHT (do not disturb):** S427 (memory-evidence: memory_intent.py,
  agent_runtime.py, trivial_input.py, memory_resolver.py) — product commit
  `ed8dcf2` landed mid-session; closeout may follow. S428 (thinker-concurrent,
  ADR-57 slice 2: loop.py, thinker.py, thinker tests, CHANGELOG.md) — own
  worktree `../LocalMind-zcode-s428`. Check `collaboration/events/` before
  touching either scope.
- **Future product commits now face two new gates (core 0.10/0.11):**
  `context-mem lint` fails any staged product line citing ADR-N, bug IDs, or
  `.context/` paths — rephrase docstrings to stand alone (one-way linkage);
  `context-mem check` (runs at exit) fails on duplicate registry keys —
  ai-models.md and environments.md are update-in-place: EDIT rows, never
  append duplicates.
- **Session history rotation (core 0.13.0):** sessions.md is the CURRENT
  GROUP's registry (group_size=20 in workflows/history.conf). When it feels
  heavy, `context-history close --confirm` consolidates into
  `.context/history/group-001.md` and starts a fresh group — promote open
  threads to durable files first (close refuses without --confirm and prints
  the checklist). LocalMind's sessions.md has ~430 legacy lines: the first
  close will sweep them all into group-001.
- **Durable-log pruning (core 0.12.0):** `context-mem prune --list` names
  explicitly-RESOLVED entries eligible to move verbatim into
  `flaws/archive.md` / `inefficiencies/archive.md` — worth one bookkeeping
  session soon (flaws 686 lines / inefficiencies 1228 lines).
- **S426 follow-ups (latency roadmap):** fix #3 = cache-prefix stability (39%
  cached — per-iteration prompt assembly + tool-schema prefix in loop.py;
  COORDINATE with S428's loop.py claim); metrics honesty (surface
  `total_prompt_tokens`); init+Thinker skip for simple turns (architectural,
  ADR-53-compliant).
- **Live-test providers (unchanged):** bankofai free = hy3 / glm-5.3-flash /
  qwen3.8-flash; deepseek-v4-flash NOT free (400 credit); gemini-2.5-flash
  eats quota; zai 401. One port per concurrent agent (8765, 8766, …).
  bankofai had a routing-postgres outage — wait minutes, re-run.
- **Standing P0 queue (unchanged):** Step 4 (tool-result FTS5+vec0 index +
  search), Step 5 (Context Budget Manager), Steps 6-8; Step 3 live
  prompt-audit owed.
- **Deferred:** B-2026-09-05-1..3 file-reading items; B-2026-09-05-4 backend
  baseline peer pass (~37F Windows drift); frontend eslint drift (9E/84W)
  still fails the exit gate on main.
- **Tooling:** commit messages via `git commit -F <file>`; python heredocs
  must not contain backslash paths; large HTTP bodies: save to file first.
  Live-test servers: plain Popen — never DETACHED_PROCESS with piped stdout
  on Windows (S423). Capture full pytest output to a file before filtering.
  **Stash-based baseline capture is banned (S426) — prefer a read-only
  worktree.** Session resumption: check `git log`/`status` before re-running
  an interrupted commit chain (S429).

# Current Task

**Status:** IDLE — Sessions 425–427 closed (their records live in
`agents/sessions.md` + `sessions/SUMMARY.md`; S427 shipped
evidence-grounded memory writes, live-verified). **Session 429 closed (two rounds):
core updated 0.9.1 → 0.16.0** (`38d58c0` — source repo verified against
its own manifest BEFORE updating, per the S426 lesson; the 0.13.1
corruption had already been repaired upstream). Two package flaws found +
logged: the `.ps1` update path skips the 0.13.0 zone migration
(history/, archive/, history.conf, agents/GROUP — installed manually per
the sh-port commands; RESOLVED upstream the same day by 0.16.0 — the .ps1
update now backfills all zones in one run via `migrate --backfill-only`,
exercised live in round 2), and `context-mem lint` false-positives on the
root AGENTS.md digest (still open). AGENTS.md digest + kickoff `.cmd`
invocations refreshed from the new templates; `memory/agents/roster.md`
installed (0.15.0 named-persona roster — current-group team board; S429's
row: Ada | S429); duplicate Super Z / GLM-5.2 registry row merged
(`context-mem check` passes). **S428 (thinker-concurrent) may still be in
flight** in worktree `../LocalMind-zcode-s428` (branch
`collab/localmind-thinker-concurrent/...`) — check the event trail before
touching loop.py/thinker/CHANGELOG.md.

**Feature:** none

## Notes for the next session

- **NEW (core 0.14.0 session-start + exit habits):** Windows invocations
  are now the `.cmd` launchers — e.g. `.context/core/bin/context-sync.cmd
  verify|status`, `context-mem.cmd check`, `context-mem.cmd lint`,
  `context-gates.cmd run pre-commit` — no `pwsh -File` or
  execution-policy setup needed. At exit, `context-mem check` runs (flag:
  duplicate registry keys — ai-models.md and environments.md are
  UPDATE-IN-PLACE: EDIT rows, never append duplicates). Future product
  commits must pass `context-mem lint`: no ADR-N / bug-ID / `.context/`
  path citations in staged product lines — rephrase docstrings to stand
  alone (one-way linkage; known false positive: root AGENTS.md itself).
- **Session history rotation (core 0.13.0):** sessions.md is now the
  CURRENT GROUP's registry (group_size=20 in
  `workflows/history.conf`; zones installed by S429). `context-history
  close --confirm` consolidates into `.context/history/group-001.md` and
  starts a fresh group — promote open threads to durable files first
  (close refuses without `--confirm` and prints the checklist). The first
  close will sweep all ~430 legacy lines into group-001.
- **Durable-log pruning (core 0.12.0):** `context-mem prune --list` names
  explicitly-RESOLVED entries eligible to move verbatim into
  `flaws/archive.md` / `inefficiencies/archive.md` — worth one bookkeeping
  session soon (flaws ~686 lines / inefficiencies ~1260 lines).
- **Memory follow-ups (S427, small):** (1) the resolution call's provider
  usage is not folded into the turn's provider_usage accounting (minor
  observability gap); (2) S356's "Got it — I'll keep that in mind." on
  legacy-path write FAILURE is still a soft fake-confirm — owner call
  whether to make it honest; (3) the resolution prompt could also consider
  PRIOR stored memories as evidence (currently conversation-only).
- **The thinking principle (S427 discussion, owner-articulated):** LocalMind
  was restrained from thinking, and the restraint bit where reasoning IS the
  mechanism — reference resolution. The fix re-placed the gate by
  shape-of-input (self-contained vs referential) instead of turn class.
  Worth an ADR when generalized beyond memory (e.g. other deterministic
  fast paths that skip reasoning).
- **ADR-57 slice 2 (concurrent consults) is the frequency lever.** Consults
  are still value-gated (failure / ≥2 sources, once/turn) — the latency fix
  stands. Streaming made them visible; concurrency would let them fire after
  every tool without wall-clock cost. Map the data dependencies first
  (ADR-57 Open-Q1). Do NOT re-add every-tool serial consults (S420-era
  2-minute turns). **S428 is implementing this — coordinate.**
- **S426 follow-ups (the latency roadmap, prioritized):** fix #3 =
  cache-prefix stability (39% cached — per-iteration prompt assembly +
  tool-schema prefix in loop.py — S425's loop.py claim is now RELEASED,
  safe to touch; coordinate with S428); metrics honesty (panel shows
  last-call prompt + undercounts llm_calls — surface
  `total_prompt_tokens`); init+Thinker skip for obviously-simple turns
  (architectural, ADR-53-compliant).
- **Watch the consult prose on live passes:** qwen3.8-flash occasionally
  restates the request ("The user is Tisone and wants me to...") — prompt-
  level, not structural.
- **Port discipline (S425 + S426, twice-burned):** one port per concurrent
  agent (8765, 8766, …) — shared-8765 kill_port collisions cost S426 ~25 min
  and cost S425 one INVALID after-run (a stale server answers health checks
  and the client silently measures OLD code). Before trusting any trace:
  verify the port was free, and grep the server log for "already in use" + a
  fresh "parent-kernel] ready" line. Candidate fix: add the check to
  `scripts/live_test_cybercafe.py` boot_server. **Also (S427): stage the
  scratch-home settings with ABSOLUTE paths — a relative `cp` under drifted
  cwd silently created `backend/scratch/` and cost a wasted live run.**
- **context-collab.ps1:** use `--refs`, not `--re` (the alias breaks pwsh
  parameter binding).
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash /
  qwen3.8-flash; **deepseek-v4-flash is NOT free on this account** (400
  "credit insufficient balance=0" — live-testing.md's "fast AND free" is
  stale here); gemini-2.5-flash eats per-minute quota; zai 401; chutes/
  cerebras $0. bankofai also had a provider-side outage (their routing
  postgres "too many clients", ~03:45–04:15 on 2026-09-06 — all models incl.
  paid hung a 5-token probe) — wait minutes, re-run; probe minimally before
  scheduling live traces.
- **Experiential Labs was REVERTED per owner directive (B-2026-09-06-1,
  ADR-58 amended)** — do NOT re-add without reading that backlog entry;
  restore = `git revert 645b5c4` + the owed smoke test.
- **Standing P0 queue:** Step 4 (tool-result FTS5+vec0 index + search), Step 5
  (Context Budget Manager), Steps 6-8; Step 3 live prompt-audit owed.
- **Frontend eslint drift (S422): 9 errors + 84 warnings vs --max-warnings 71
  — the exit gate FAILS as-is on main.** Needs the deferred peer pass.
- **B-2026-09-05-4:** the ~23-failure Windows backend baseline needs the peer
  pass (find_path KeyError family + permission-gate asserts look like one
  shared fixture cause). Deferred file-reading items B-2026-09-05-1..3 remain.
- **Windows gates quirk:** gates.conf/ci-check.sh assume the macOS venv layout
  (`bin/`) — on this box use `backend/.venv/Scripts/*`; run exit-gate CI as
  components.
- **Tooling:** commit messages via `git commit -F <file>`; python heredocs via
  the Bash tool must not contain backslash paths (use forward slashes). Large
  HTTP bodies: save to a file FIRST, then parse (S424). Live servers: plain
  Popen — never DETACHED_PROCESS with piped stdout on Windows (S423). Capture
  full pytest output to a file before filtering — `tail` on a pipe loses the
  FAILED list. **Stash-based baseline capture: `git stash list` must be EMPTY
  before the after-run (S426 mislabeled a trace set this way — prefer a
  read-only worktree). Session resumption: check `git log`/`status` before
  re-running an interrupted commit chain (S429).**

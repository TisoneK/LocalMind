# Current Task

<<<<<<< HEAD
**Status:** IDLE — Session 428 closed. ADR-57 slice 2 shipped + LIVE-verified:
post-tool Thinker consults now fire after EVERY tool as background tasks
(one-in-flight, cap 5/turn, prose streamed, analysis injected at the next
model-call boundary); failures keep the BLOCKING consult. LIVE
bankofai/qwen3.8-flash same-prompt before/after: consults 2 → 4, streamed
consult reasoning 2223 → 7463 chars, latency 66.7s → 60.6s (overlap — no
added latency), answer held. 37 thinker/loop tests; core+e2e failure set =
verified pre-existing baseline (12). Also fixed a security flaw: config.py
logged plaintext api_keys at INFO on every boot (`cbbbabe`) — **key values
appeared in this session's chat transcript; ROTATION ADVISED for the
configured providers (bankofai, zen, cerebras, gemini, zai, deepseek,
omniroute).**
=======
**Status:** IDLE — **S431 (Kwame) chat-hygiene TRIAGE closed.** A live chat-export +
UI review (session-1788669567862 + the sidebar) produced six new backlog items
**B-2026-09-06-2 .. -7**: chat export drops user messages + assistant-only count
(-2), full-fidelity export schema v3 per the owner's "capture everything" directive
(-3), fast-path canned-greeting misfire on "How are you?" + fabricated provider
metrics (-4), test runs polluting the real chat store (~40 residue chats, -5),
raw-markdown sidebar previews (-6), and the Agent-Workspace "Child agents…" copy
that contradicts ADR-53 Parent-only (-7). **Owner is launching collab fix agents
next:** shared session `localmind-chat-hygiene`, one issue per backlog ID (e.g.
`--issue B-2026-09-06-4`); pick a roster name, worktree per the 2026-09-05
override, claim → work → release. -2/-3 share a surface (one agent can take
both). -4 touches the agent-loop fast path → the live-testing bar applies.
-5's cleanup needs an owner-approved delete list (real chats are interleaved).
**S428 (thinker-concurrent) claim STILL unreleased** — loop.py/thinker/CHANGELOG.md
remain its scope; check the event trail first. (Prior state: S429/S430 closed the
core update 0.9.1 → 0.16.1, incl. the 0.13.0 zone-migration flaw resolved upstream
in 0.16.0; `context-mem lint` false-positives on the root AGENTS.md digest remain
open in flaws/log.md.)
>>>>>>> origin/main

**Feature:** none

## Notes for the next session

<<<<<<< HEAD
- **SECURITY: rotate the provider keys listed above** — they were visible in
  a session transcript (and in every pre-fix server log). After rotation,
  update keys ONLY via the app's Settings UI.
- **Consult cadence is now a tuning surface:** `_THINKER_CONSULT_CAP` (5/turn)
  and `_THINKER_TOOL_SKIP` in loop.py; watch live behavior and tune.
- **ADR-57 slice 4 (unstarted):** run the Thinker's analysis on a
  faster/cheaper role while the main model acts (model-agnostic per the
  standing rule).
- **Test-fixture contract (from S428):** fake dispatches MUST accept
  `adapter=None, **kwargs`; instant async fakes starve background tasks —
  use `await asyncio.sleep(0)` at yield points and warm-turn delta timing.
- **Port discipline:** one port per concurrent agent; grep the server log
  for "already in use" before trusting any trace (S425/S426, twice-burned).
- **Standing P0 queue:** Step 4 (tool-result FTS5+vec0 index + search), Step 5
  (Context Budget Manager), Steps 6-8; Step 3 live prompt-audit owed.
- **Frontend eslint drift (S422): 9 errors + 84 warnings** still fails the
  exit gate on main; backend ~12-failure baseline peer pass (B-2026-09-05-4).
- **Experiential Labs reverted (B-2026-09-06-1)** — restore = `git revert
  645b5c4` + owed smoke test; read the backlog entry first.
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash / qwen3.8-flash;
  deepseek-v4-flash is PAID on this account; zai 401; chutes/cerebras $0.
  Probe with a 5-token request before scheduling live traces (gateway outages
  happen).
- **Windows:** use `backend/.venv/Scripts/*`; run exit-gate CI as components;
  python heredocs must not contain backslash paths; commit messages via
  `git commit -F <file>`; live servers via plain Popen.
- **context-collab.ps1:** use `--refs`, not `--re` (alias breaks pwsh binding).
=======
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
>>>>>>> origin/main

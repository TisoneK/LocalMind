# Current Task

**Status:** ACTIVE — **collab fix phase live on session `localmind-chat-hygiene`.**
**Kwame (S431) resumed by the owner** (his run was deleted mid-fix-phase;
continuing as him, not a new session). Split agreed on the trail:
- **Mei (S433) CLOSED -2** (claim `20260906T073036Z`, release
  `20260906T194249Z`, product commit `ad4e3fc` merged to main): the
  deterministic epilogs in `backend/src/core/agent_runtime.py` (trivial +
  conversational fast paths + memory-write paths incl. the resolution-fail
  ask) returned before the main path's fire-and-forget user-message persist —
  those turns left no user row. They now await the user persist immediately
  before the assistant persist (also guarantees timestamp order); 5
  regression tests in `tests/core/test_fastpath_user_persist.py` fail
  pre-fix / pass post-fix (isolated tmp home). Metrics lines stayed
  untouched (that's -4's). No frontend change.
- **Kwame owns -3 + -6 + -7** (claim `20260906T082235Z`): export schema v3 —
  client preserves raw epoch as `timestampEpoch` (today's mapping reduces it
  to HH:MM — the ISO-date gap), exporter emits ISO-8601 timestamps +
  createdAt/lastActive per chat + model/provider per turn, every v2 key kept;
  the agent_runtime additive pass (identity keys + fast-path Thinker-thinking
  capture) rebases AFTER Mei's merge (now landed — `agent_runtime.py` is
  free); -6 = strip markdown in LeftPanel previews at display time (stored
  last_message stays raw for export fidelity; the "capabilities overview"
  weather preview is the last message, not a selection bug); -7 = parent-only
  copy in AgentWorkspace.tsx.
- **-4 free** after Mei's -2 (detector fns in `trivial_input.py` + the
  synthetic-metrics half of the finalize block). **-5 parked** on the
  owner-approved delete-list. (Triage context: the six items
  **B-2026-09-06-2 .. -7** came from S431's live chat-export + UI review;
  full text in backlog.md. -4 touches the agent-loop fast path → the
  live-testing bar applies.)
**S428's thinker-concurrent claim WAS released** at its closeout (`38e743f`,
event `20260906T053617Z`) — loop.py/thinker/CHANGELOG.md are free (earlier
board states saying "STILL unreleased" were stale). (Prior state: S429/S430
closed the core update 0.9.1 → 0.16.1, incl. the 0.13.0 zone-migration flaw
resolved upstream in 0.16.0; S432 synced macOS to ac1daad and
live-smoke-tested the pulled code — see sessions.md. `context-mem lint`
false-positives on the root AGENTS.md digest remain open in flaws/log.md.)

**Feature:** none

## Notes for the next session

- **S432 backlogged its two findings:** B-2026-09-06-10 (title-generator
  races SIGTERM teardown — background tasks not cancelled before adapter
  close; also log the real exception text) and B-2026-09-06-11 (gate grep
  for committed conflict markers in memory files, after `95c6400` shipped
  them in current.md).
- **SECURITY: rotate the provider keys (bankofai, zen, cerebras, gemini, zai,
  deepseek, omniroute)** — they were visible in a session transcript (and in
  every pre-fix server log; config.py logged plaintext api_keys at INFO, fixed
  in `cbbbabe`). After rotation, update keys ONLY via the app's Settings UI.
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
- **Consult cadence is now a tuning surface:** `_THINKER_CONSULT_CAP`
  (5/turn) and `_THINKER_TOOL_SKIP` in loop.py; watch live behavior and tune.
- **ADR-57 slice 4 (unstarted):** run the Thinker's analysis on a
  faster/cheaper role while the main model acts (model-agnostic per the
  standing rule). Backlogged as B-2026-09-06-9 (right-size role).
- **Test-fixture contract (from S428):** fake dispatches MUST accept
  `adapter=None, **kwargs`; instant async fakes starve background tasks —
  use `await asyncio.sleep(0)` at yield points and warm-turn delta timing.
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
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash /
  qwen3.8-flash; **deepseek-v4-flash is NOT free on this account** (400
  "credit insufficient balance=0" — live-testing.md's "fast AND free" is
  stale here); gemini-2.5-flash eats per-minute quota; zai 401; chutes/
  cerebras $0. bankofai also had a provider-side outage (their routing
  postgres "too many clients", ~03:45–04:15 on 2026-09-06 — all models incl.
  paid hung a 5-token probe) — wait minutes, re-run; probe minimally before
  scheduling live traces. (S432 re-verified qwen3.8-flash live on 8765.)
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

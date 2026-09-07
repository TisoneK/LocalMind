# Current Task

**Status:** ACTIVE — Session 436 (Noah / ZCode local, glm-5.3-flash, Windows).
Part 1 LANDED (`fbffcac`, pushed): **selected-text right-click menus on the chat
surface** — transcript (Copy selection / Copy message / Select all) + input
(Cut / Copy / Paste / Select all): 20 new vitest tests, full frontend 416/416 green,
tsc clean, eslint 0 errors on the touched files.

Part 2 (new chat-message target): **export chat feature — offer users the
option to EITHER copy the export data to the clipboard (in both available
formats, Markdown and JSON) OR save it as a file (existing download)**.
Plan: a pure `copySessionsToClipboard()` in the export util (mirrors
`exportSessions`, with an injected clipboard writer),, a second dropdown
"Copy" button next to "Export" in LeftPanel's bulk-action row, wired
through WorkspaceLayout; vitest coverage in both suites. Frontend-only —
no agent-loop/tool/provider surface, so the live-MODEL bar does not apply.



**Feature:** none

**S437 (Amina / ZCode local, concurrent with S436 on this box — separate
worktree, collab session `localmind-store-hygiene`) DONE:** shipped the
conftest-isolation half of the chat-store pollution item — `tests/conftest.py`
now stages a fresh temp `LOCALMIND_HOME` at import time whenever the incoming
value is unset or IS the real default home (commit `759e67a`, guard test
fails pre-fix); corrected `test_engine_conversational_followup_uses_direct_chat_context`
(same commit — it had been passing only on leaked residue) and made
TestWindowSource hermetic with a dummy provider key (`ed770d6` — it had been
reading the user's real bankofai key from the app home). Verified: real store
1159→1159 messages / 87→87 sessions across targeted + two full non-e2e runs;
final failure set = 22, all the documented `tests/tools` family. REMAINING
(owner-gated, B-2026-09-06-5): delete the ~65 residue chats — delete-list at
`scratch/residue-delete-list-s437.json` (rule: every session id NOT starting
with `session-`). New backlog: B-2026-09-07-1 (fast-path turns persist no
workspace artifacts → Agent Workspace resets on reload), B-2026-09-07-2
(fast-path Thinker consult is serialized before the answer → latency).


**S435 (this macOS checkout, single-agent — distinct from the chat-hygiene
collab above) DONE + pushed:** B-2026-08-24-17 Terminal panel redesign
(`4b50d72`) + a rider fix `fix(scripts): make check-conflict-markers.sh
POSIX-sh compatible` (`aa8ef68`) — Mei's S434 script used bash `< <(...)`
process substitution but gates.conf runs it via `sh`, so pre-commit could not
run on macOS. No overlap with Kwame's still-unmerged -6/-7.

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

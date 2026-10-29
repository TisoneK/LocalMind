# Inefficiency Log (append-only — real friction only)

Append a block **only when something actually slowed you down** — a clean
session appends nothing (its `agents/sessions.md` entry is the record;
"none this session" blocks are noise, not history). But when something
bit you, the block is mandatory and honest: friction you absorb silently
is friction the next agent hits blind.

Most inefficiencies are project-local (an environment quirk, a one-off
cost) and stay here. When one is actually **protocol-level** — the core
workflow itself made you slower and every project would hit it — mark it
`Upstream: candidate`. `ledger-sync harvest` collects those (and open
`flaws/`) into the package for an upstream fix. Unmarked entries are
never harvested.

Append-only, but compactable — the log never grows without bound:

- **Resolved entries move verbatim** to cold storage: once an entry is
  explicitly marked `RESOLVED` / `superseded` / fixed, cut it unchanged
  into `archive.md` in this directory so startup reads only the live
  entries. Age alone never makes an entry eligible.
- **Repeats roll up:** when 3+ entries describe the same recurring thing
  (same failing tool, same root cause), append ONE consolidated
  `Recurring` entry — the pattern, how many times, the current
  workaround — and move the individual entries verbatim into
  `archive.md`. The live log keeps the pattern, not the repeats.

`ledger-mem prune` reports log sizes, archive-eligible entries (`--list`
names them), and roll-up candidates.

<!-- TEMPLATE — copy below the last entry:
---
## YYYY-MM-DD — <agent> / <model>
- **Problem:** <what went wrong or was slower than it should be>
- **Cost:** <rough time/effort wasted>
- **Cause:** <root cause if known>
- **Workaround / fix:** <what worked, or "unresolved">
- **Prevent next time:** <protocol/context change that would have avoided it>
- **Upstream:** candidate  ← add this line ONLY for protocol-level friction
  worth a core fix; omit entirely for project-local friction.
-->

---
## 2026-09-21 — none this session (Mosi / S001)

No project-code or environment friction worth a trap: the engine's extraction needed only mechanical moves,
and the isolated 8765 harness behaved (boot healthy in a few seconds, real probes 0-5 ms, clean shutdown).
The one tool-layer trap re-hit was the long-standing one — a compound shell command whose `cd` and redirected
log path disagreed, so the first `grep` looked for a log that was written elsewhere; splitting the command
and using absolute paths (the pattern already in the log) is the fix.

---
## 2026-10-26 — Dara / deepseek-flash (S003)
- **Problem:** A background Thinker consult started after a turn's LAST
  successful tool call ran completely silent: its prose queued on
  `_BackgroundConsult` and was discarded when the final answer ended the
  turn. The drain points existed only at iteration heads and tool
  boundaries, and the terminal turn has neither.
- **Cost:** roughly an hour of diagnosis, including instrumenting the loop
  and comparing against a clean HEAD worktree to separate "my change broke
  it" from "this shape was never covered".
- **Cause:** the final-answer path consumes the model stream without any
  consult drain; on top of that, the test's mock `adapter.chat` is shared by
  the planner (`intent="chat"`), the forced-final-answer rescue (no intent)
  and the Thinker (`intent="analyze"`), so a naive mock answers the wrong
  caller and hides the real contract.
- **Workaround / fix:** drain the in-flight consult once the final-answer
  stream loop ends, before the buffered answer is committed (analysis is
  still absorbed for a possible replan); the test now filters on
  `intent == "analyze"`, terminates its prose paragraph, and yields a few
  `sleep(0)` ticks so a background task can run on the Windows event loop.
- **Prevent next time:** whenever a stream feature is hooked into the agent
  loop, cover the "last action was a tool" shape — iteration-head-only hooks
  silently skip the terminal turn — and give shared-method mocks an explicit
  caller discriminator instead of relying on call order.

---
## 2026-10-26 — Dara / deepseek-flash (S003) — dev stack attaches Electron to a foreign server on :3000
- **Problem:** `npm start` died with "Timed out waiting for http://localhost:3000" while
  Vite had printed `ready` on that port. The owner's bobly-tide backend already held
  `0.0.0.0:3000`/`[::]:3000`; on Windows Vite's bind still succeeds alongside a wildcard
  listener (SO_REUSEADDR) — even with `strictPort: true` — so Vite reported ready while
  connections to :3000 reached bobly-tide's 404. `wait-on` then polled the wrong server.
- **Cost:** ~30 minutes of reproduction (Vite on a spare port, HEAD vs GET, listener
  inspection, process tree).
- **Cause:** port collision with an unrelated local service plus a permissive Windows
  bind; readiness was checked by port, not by server identity.
- **Workaround / fix:** owner-directed — stopped bobly-tide's process tree
  (`cmd → tsx → node src/main.ts`), freeing :3000; `npm start` then reached Electron and
  the UI rendered. Moving LocalMind to 5173 with a Vite-only probe
  (`/@vite/client`) was prepared and reverted by owner preference.
- **Prevent next time:** when Vite says ready but Electron times out, check the port's
  owner (`netstat -ano`) before touching the frontend; a port alone cannot prove the
  responding app is Vite on Windows.

## 2026-10-26 — Ezra / GLM (Z.ai) (S004) — palette ids are validated by two independent lists

- **Observation:** the frontend (`THEME_IDS` in `useTheme.ts`) and the backend
  (`valid_themes` in `api/routes/config.py`) each keep their own copy of the
  valid palette ids. The backend list missing the then-default id shipped
  silently: every attempt to save the default palette from Settings got a 400
  that the UI swallowed, so a one-line default rendered as "working" until
  someone actually tried to save it.
- **Prevent next time:** when touching either list, touch both in the same
  change — `tests/api/test_config_adapter.py` now POSTs every built-in id the
  frontend offers, which closes the loop for today; a frontend-side mirror
  test would catch the reverse direction.
- **Also observed while verifying the build on Linux:** the root
  `npm run build` cannot pass on this sandbox — the electron workspace's
  `electron-builder --publish never` aborts for missing Linux packaging
  metadata (author email / homepage / `.deb` maintainer; last touched by the
  dependabot batch `f393bea2`). Pre-existing and Windows-invisible (sessions
  build the frontend workspace); noted so a future Linux-CI effort knows
  where to start.
---
## 2026-10-27 — Kai / GLM (Z.ai) (S005)

- **Friction:** a fresh backend venv built with this machine's default `python` (3.14) collects no tests — pip resolves a cp313 `pydantic_core` build inside the cp314 venv, and `import pydantic_core` fails with `ModuleNotFoundError`, stopping every pytest collection.
- **Cost:** first pytest read was a clean-looking exit 2 with no obvious fix; ~5 minutes to diagnose to the ABI mismatch, then a full venv rebuild.
- **Workaround:** always create the dev venv with `py -3.13 -m venv backend/.venv` — 3.13 is what the resolved wheels target; 3.14 is the machine default.

---

## 2026-10-27 — Amani / GLM (Z.ai) (S006)

- **Friction:** `web_fetch` cannot tell a JavaScript-rendered data page from real content — meteoblue's static HTML is language lists, promos and other cities' temperatures, yet the tool returns success with ~10K chars of it, and the loop counts that as evidence. Two of the five iterations in the Kitengela weather trace went to fetching and re-querying that chrome. Live-probed the obvious extraction heuristics and they are unsalvageable: sentence-density flags wttr.in (the best source — JSON has no long sentences) and passes meteoblue (its news blurb is real prose).
- **Cost:** the trust damage is now closed at the answer layer (the acceptance gate's evidence-grounding criterion — invented figures are caught and named), but the wasted iterations are not: the loop still pays for the dead fetch before the gate fires.
- **Workaround/status:** acquisition-level routing to the browser tool parked as `P-2026-10-27-1` (needs a safe quality signal, not a heuristic); figure-attribution follow-up is `B-2026-10-27-1`. Backlog sits at its cap — new rows went to Medium with the warning accepted.

---

## 2026-10-28 — Zuri / GLM (Z.ai) (S008)

- **Friction:** restore-boot env losses keep recurring per sandbox: this one started with `sqlite_vec` missing from the backend venv (full suite unrunnable until reinstalled) and NO frontend `node_modules` at all (vitest could not start; a bare `npx tsc` then pulled the bogus registry package `tsc@2.0.4` instead of TypeScript). The S006 line repaired the same class of loss earlier today.
- **Cost:** ~10 minutes of env repair before any verification could run; the `tsc` name collision is a silent trap (npm warns but proceeds).
- **Workaround/status:** known-good repair sequence recorded — `/home/z/.venv/bin/pip install sqlite-vec duckduckgo_search` for the backend, and `npm ci` from `frontend/` (the repo is an npm workspace, so bins land in the repo-root `node_modules` — call them by absolute path, and use `node_modules/.bin/tsc`, never bare `npx tsc`). Structural fix (a boot-time env doctor) parked; not worth a build session on its own.

---

## 2026-10-29 — Nadia / unknown model id (S031)

- **Friction:** every live-test harness here starts its fake provider on a thread inside the harness process and then calls `kill_port(FAKE_PORT)` on the way out. `ThreadingHTTPServer.shutdown()` stops the loop but does not close the listening socket, so netstat still shows the harness's own PID bound to that port and the sweep taskkills the harness — silently, with no traceback, AFTER its PASS line has printed. The proof reads as passed while the shell reports exit 1: `live_test_provider_death_honesty.py`, `live_test_identity_injection.py` and `live_test_provenance_symmetry.py` all print PASS and all exit 1 today for exactly this reason.
- **Cost:** one confusing diagnosis round ("it printed PASS, why did the command fail?") before the mechanism was visible; a script whose exit code is meaningless is a script CI cannot gate on.
- **Workaround/status:** `scripts/live_test_done_rules.py` (new) calls `fake.server_close()` before its port sweep, so its exit code is trustworthy. The three older harnesses still carry the flaw — one-line fix each for whoever is next in them; not touched here because they were read-only regression evidence for this session's change.
- **Resolved — 2026-10-29, Soren (S032):** the three older harnesses now carry the reference teardown (`shutdown() → server_close() → kill_port(PORT)`, the dropped `kill_port(FAKE_PORT)` matching `done_rules`). Mechanism verified env-agnostically — after `shutdown()` a modelled sweep hits the harness's own pid, after `server_close()` it hits nothing — so the exit code survives on both PASS and FAIL paths. Fixed in a dedicated isolated worktree; the real booted end-to-end confirmation is a Windows session's to do (on POSIX `kill_port` is a `pkill -f LOCALMIND_PORT=` no-op, so the failure never manifests there). Report: `office/reviews/2026-10-29-review-s032-harness-exitcode.md`.

---

## 2026-10-29 — Soren / Opus 4.8 (S032)

- **Friction:** a fresh git worktree on this machine has no `node_modules` (root `node_modules` is empty everywhere, not just the worktree) and no backend venv, yet the pre-commit gate runs `tsc -b --noEmit` and `ruff` unconditionally. A scripts-only + ledger change (zero frontend files) was blocked by a frontend compiler gate it could not even run.
- **Cost:** an environment bring-up (`npm install`, ~one background run) was needed purely to satisfy a gate orthogonal to the change; a backend venv had to be borrowed by symlink from the sibling checkout for `ruff` to resolve.
- **Workaround/status:** symlinked the sibling checkout's `backend/.venv` for `ruff`, ran `npm install` (Electron binary skipped) to let `tsc` resolve, then the full pre-commit gate passed green and the commit went through normally — no guard skip. Behavioural note for worktree sessions: budget a node/venv bring-up before the first commit even for a non-frontend change, or keep the gate scoped to changed surfaces (S006 part 4 hit the same wall and documented it as a standing gap).

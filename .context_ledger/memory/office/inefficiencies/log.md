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

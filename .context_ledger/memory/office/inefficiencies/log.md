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

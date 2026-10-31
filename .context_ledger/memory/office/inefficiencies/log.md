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
## 2026-10-31 — Kofi / unknown (harness states no model ID)
- **Problem:** The first run of the repaired `scripts/reset_vector_db.py --yes` printed "Dropping vector tables… done." and then crashed re-embedding fact 1 with the SAME `Dimension mismatch (Expected 768 … received 1024)`. The DB was left half-reset and the script had to be run a second time.
- **Cost:** One extra full reset run plus a diagnosis detour (~10 min).
- **Cause:** `_drop_vector_tables` ran `DROP TABLE vector_embeddings` on a plain `sqlite3` connection with the sqlite-vec module not loaded, so the DROP raised "no such module: vec0" — and `except Exception: pass` swallowed it. The old 768 table survived; the later `CREATE VIRTUAL TABLE IF NOT EXISTS … float[1024]` therefore kept 768, and the first INSERT hit the same mismatch. The script's "done" message was unconditional.
- **Workaround / fix:** Load the extension on the drop connection, stop swallowing the drop error, and verify the created DDL contains `float[<probed dim>]` before re-embedding. Regression test `test_drop_really_removes_the_vec_table`.
- **Prevent next time:** A repair/migration tool must verify its own post-conditions (here: the table is gone, then the new table's dim matches) instead of trusting an unconditional success print. Any `except Exception: pass` around a destructive SQL statement is a latent false success.
- **Upstream:** no

---
## 2026-10-31 — Kofi / unknown (harness states no model ID)
- **Problem:** Ran `sh .context_ledger/memory/workflows/gates.conf`, intending only to read the file — it executed the gate registry itself (`pre-commit|sh scripts/run-in.sh frontend npx tsc …` becomes a real pipeline), running a frontend type-check and hanging until the command was killed (~2 min, left a background task).
- **Cost:** ~2 minutes plus a background-task cleanup.
- **Cause:** `gates.conf` is data (a `gate|command` registry), but it is syntactically executable shell. Reading and executing were conflated in the same command line.
- **Workaround / fix:** Read the file with the Read tool (never `sh` it). Gates are run via `ledger-gates run pre-commit`, not by executing the config.
- **Prevent next time:** Treat every `*.conf` as data; only `core/bin/*` scripts are executable.
- **Upstream:** no

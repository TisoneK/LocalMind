# Session 14 notes — Buffy (S014) — the typed memory write path

Companion to the report
(`office/reviews/2026-09-17-review-s14-memory-write-path.md`) and the
`agents/sessions.md` entry. This file keeps what the report summarizes:
the live protocol, the exact evidence, and the parts that did not go
smoothly. `scratch/` is gitignored, so the artifacts that matter are
copied under `evidence/` beside this file.

## What the row asked for

Backlog head `B-2026-09-15-3` (typed memory schema in the write path)
plus `B-2026-09-15-4` (the reliability mechanics it gated) — treated as
one surface, because "what a write accepts", "what identity the row
gets", and "what the app may claim afterwards" are the same decision.

## Live protocol

- Isolated backend on port 8766 with a scratch home
  (`LOCALMIND_HOME=scratch/live-memory-write-path/tracehome`), provider
  `zai` / `glm-4.5-flash` via the real classifier path (`/api/chat`
  SSE), never mocked.
- Four turns, replayed identically from a worktree at the previous
  revision (`LocalMind-before`, detached at `74817201`): store a live
  value (public IP + ISP), store a preference, restate it, delete it by
  the short id the UI prints.
- Harness: `scripts/live_test_memory_write_path.py` (product-adjacent
  live trace, committed as `5ed4a22a`).

## Before / after, same four turns

| check | before | after |
|---|---|---|
| "remember my public IP … and my ISP …" | stored | refused in plain words, 0 such rows |
| the same preference stated twice | 2 rows | 1 row |
| durability tags on the stored row | none | `memory_key`, `memory_kind=preference`, `memory_freshness=static` |
| delete by the short id the screen shows | 404, row stayed | deleted, list empty |
| the model's listing call | persisted the word "list" | `**Stored memory (1 facts):** - #98802f19 …` |

Raw evidence: `evidence/results-before.json`,
`evidence/results-after-list.json`, `evidence/sse-before-turn1_live_value.sse`
(the refused live value, before), `evidence/sse-after-list-turn4_list.sse`
(the id-bearing listing, after), `evidence/bare-list-before-after.txt`
(the deterministic tool-level before/after on the bare operation word).

## The two bugs found live

1. **The model's listing call was stored as a memory.** `memory_op` was
   called with `operation=list`; the dispatcher handed the tool the bare
   word, it missed the listing pattern and fell through to the store
   path. Deterministic before/after at the tool boundary (see
   `bare-list-before-after.txt`): before wrote `['list']` and answered
   `Remembered: *list*`; after writes nothing and returns the listing.
2. **Deleting never worked on a store without a vector table.** The
   delete touched `vector_embeddings` unconditionally; a fact stored
   while the embedder is unavailable has no vector row, and on that
   store the table may not exist at all, so every delete failed while
   callers reported "couldn't find that fact". Fixed at the source —
   removing the vector row is best-effort, the fact row is what goes.

## Verification boundary (what is *not* proven)

- The key heuristic collapses re-statements that share a named subject
  or leading content words. With the embedder down (no semantic dedup) a
  genuinely re-worded paraphrase still creates a second row.
- The freshness tags have no consumer yet — nothing re-derives a `boot`
  fact at startup.
- Stores may still hold junk rows written by bug 1 before today.

## Process notes (owned in the logs, kept here for detail)

- **Flaw (flaws log):** check-in was on time, but `tasks/current.md` and
  the collaboration claim were written only at wrap-up, so the in-flight
  scope was invisible for most of the session. Suggested mechanical
  nudge: `ledger-gates checkpoint` failing while the roster row is live,
  `current.md` is idle, and the codename has no open claim.
- **Inefficiencies (log):** `code_search` is dead on this box (bundled
  ripgrep missing) → `grep -rn` fallback; the live harness died on
  `UnicodeEncodeError` (cp1252 console) after spending provider calls →
  `PYTHONIOENCODING=utf-8`; the 3094-test backend suite exceeds the
  600 s command ceiling, so full-suite runs go to a file and are read
  back.
- **Baseline noise, not regression:** the full-suite failures
  `test_sql_tool.py::test_rejects_disallowed_path`,
  `test_sql_tool.py::test_not_a_database`,
  `test_propose_edit.py::test_propose_str_replace_permission_gate`
  reproduce at the pre-change revision `74817201` (temp-dir sandbox on
  this box), verified by running the three node IDs in the before
  worktree.

# Parking Lot (deferred knowledge — not a queue)

The backlog is a work queue you act on; this file is the knowledge base
you **don't** act on yet. Research findings, open design questions,
advisory "should we…?" items, deferred work, and someday ideas live here
so the backlog stays a queue an agent can actually work from. Nothing
here is urgent, nothing here is capped, and nothing here blocks a gate.
The record of a finding is its own row plus the commit / session entry
that produced it; git history keeps every row, so promoting or dropping
one loses nothing.

**One rule keeps the two files honest: a parking-lot row is not a task.**
If an item becomes actionable — it now has a clear next step and someone
to take it — **promote** it: cut the row here, add an actionable row to
`backlog.md` (a fresh `B-` ID, one line, pointing back at this row's `P-`
ID if the context matters), and leave it here only as a one-line
"→ promoted to B-… " stub if you want the breadcrumb. An item that turns
out to be wrong or moot is just deleted — history remembers it.

Every row gets a stable **ID** — `P-<added YYYY-MM-DD>-<n>`, n = that
date's next sequence in the file — and a **Summary** cell with enough
context that a future session can pick it up cold. Keep status
qualifiers in the text ("advisory", "needs a decision", "blocked on X",
"deferred by owner"). There is **no cap** here and **no priority** —
items are grouped by *kind*, because the whole point is that these are
not competing for the top of a queue.

This file belongs to the **current office**. When the office closes, the
parking lot is **not** re-seeded wholesale: the closing session promotes
what is now actionable into the new backlog and records the rest in the
permanent record (`history/office-<NNN>.md`, "Open threads"). A cold
idea earns its way into the next office by becoming work, not by being
copied.

Full spec: `.context_ledger/core/schemas/ledger-schema.md` →
"The parking lot".

## Findings

What we learned that isn't work yet — observations, measurements, root
causes, "the current design does X because Y".

| ID | Summary |
|----|---------|

## Open questions

Advisory questions, decisions still up for grabs, "should we…?" — a
question is not a task until it has an owner and a next step (then it
becomes a backlog row or an ADR in `plans/decisions.md`).

| ID | Summary |
|----|---------|

## Deferred work

Real tasks, consciously parked — not now, but keepable. This is where a
backlog row goes when the cap forces a prune and the item still matters:
out of the queue, not into the void.

Rows parked 2026-10-26 (S002, Harness-skin session) purely by the backlogcap — id, priority and status unchanged; nothing about them was decided:

| ID | Summary |
|----|---------|
| B-2026-09-21-13 | Skill-gap detection: diagnose repeated failure CATEGORIES and self-generate backlog rows (promotes lessons into named capability gaps). Shape to be settled at design time. |
| B-2026-09-21-18 | Memory junk-row sweep: find rows whose whole content is an operation word (`list`, `store`, `recall`, `forget`, `facts`, `memory`) written by the bare-operation bug, report them, delete only on approval; `scripts/janitor.py` is the natural home. |
| B-2026-09-21-19 | Ledger-vocabulary strip remainder: ~540 citation lines left in `tests/` (~384), `docs/` (~95) and live-test script headers (~50) — the runtime surface is already clean. Method and exact state: `history/office-002/reviews/2026-09-16-review-s5-vocab-strip.md`; hand-strip per line, never a blind script. |
| B-2026-09-21-20 | Two dead-code decisions with evidence already gathered: `core/filters.py`'s `is_code_output` flag is never read in `_filter_tool_injection`'s body, so code output gets the same filtering as everything else despite the docstring (implement the skip or remove the flag); `api/routes/terminal.py`'s `TerminalSessionBridge` is fully built but never called — wire `execute_in_session` into the agent's tool dispatch or remove the class. Detail: `history/office-002/reviews/2026-09-19-review-s021-dead-code-scan.md`. |
| B-2026-09-21-22 | Persist per-phase thinking segments so reloaded chats keep the split — store `{text, ms, afterTools}` in message metadata next to `thinking` (only live turns are split today). |
| B-2026-09-21-23 | Frontend test health: 9 context-menu tests fail under jsdom (the Radix menu opens once per file); cause already narrowed — fix or document with the cause. |
| B-2026-09-21-24 | Provider model-switch policy: provider model switches only affect the picker — decide whether hidden models must also be refused by the agent/router, and live-test the add/hide/default/delete flows on a real provider (only the DeepSeek view was clicked through). |

Rows opened 2026-10-27 (S006, evidence-grounding session) as deferred design questions:

| P-2026-10-27-1 | Guided handoff to the browser tool for JavaScript-rendered data pages: the Kitengela trace burned 2 of 5 iterations fetching a page whose forecast is client-rendered — the static extract is navigation chrome, the tool honestly reports success, and no static-extraction heuristic separates it from real content (probed and rejected: wttr.in JSON has no long sentences, meteoblue's news blurb does — both discriminations fail). A safe acquisition-level signal (content-type, DOM shell signature, or a cheap model read) could route data-looking fetches of JS-heavy hosts to the browser tool. The answer-time grounding gate now stops the trust damage; this is about the wasted iterations. Context: `office/reviews/2026-10-27-review-s6-evidence-grounding.md`. |

## Someday

Loose ideas with no owner and no hook yet. The lowest-pressure shelf.

| ID | Summary |
|----|---------|

<!-- TEMPLATE — add one row to the matching section:
| P-<YYYY-MM-DD>-<n> | <enough context that a future session can pick
      this up cold — status qualifiers in the text; promote to the
      backlog when it becomes actionable> |
-->

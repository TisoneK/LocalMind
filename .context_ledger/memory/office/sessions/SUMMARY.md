# Session Summary (compressed history — entries are removable)

One compact entry per session, newest at the bottom. Unlike
`agents/sessions.md` (the formal registry, append-only forever), this
file is a **working summary**: entries may be removed when a session is
no longer useful, and older detail is expected to compress over time.

The purpose is **continuity, not archival completeness**. A future agent
should understand at a glance what important work happened recently,
what significant decisions were made, and where to find detail if needed.

Entries are separated by `---` so agents can parse them as discrete
records.

<!-- TEMPLATE — copy below the last entry:
---
- **YYYY-MM-DD — Session N** — <agent> / <model> — <one-line outcome>.
  <Key decision or discovery, if any.>
  Detail: .context_ledger/memory/office/sessions/YYYY-MM-DD-N/notes.md (or \"summary only\").
-->

<!-- GC GUIDANCE (not part of the template — remove this comment before committing):
- Keep all entries from the last ~10 sessions.
- Older entries: distill key facts into the durable logs (decisions,
  inefficiencies, backlog) if they haven't been promoted already, then
  remove the summary line. The compact entry in agents/sessions.md is
  the permanent record that the session happened.
- Never let SUMMARY.md become another giant history file — if it exceeds
  ~40 lines, it's time to compress.
- A removed summary line MUST have a corresponding permanent entry in
  agents/sessions.md — never delete the only record of a session.
-->

---
- **2026-09-14 — Session 3** — Njeri / qwen3.8-flash — context sync done: vendored core migrated 1.0.6 → 1.1.1 (roster Status columns, entrance check-in, door-triggered office close); kickoff.md + AGENTS.md regenerated with facts refilled. No product work.
  Detail: .context_ledger/memory/office/reviews/2026-09-14-review-s3-sync.md

- **2026-09-15 — Session 4** — Zuri / qwen3.8-flash — context-usage breakdown shipped: clickable occupancy meter shows per-category shares of the last model call (system prompt / tool schemas / history / tool results / ...), scaled to the provider total; live-verified on zai (bankofai quota-exhausted — owner action). Core synced 1.1.1→1.1.3. Discovered B-2026-09-15-1 (1438 legacy ledger-citation hits in product comments; Baraka/S005 took the sweep).
  Detail: .context_ledger/memory/office/reviews/2026-09-15-review-s4-breakdown.md

- **2026-09-16 — Session 5** — Baraka / qwen3.8-flash — ledger-vocabulary sweep of the product runtime surface: ~2,650 citation lines rewritten by hand into plain words (backend, frontend, scripts, migrations, app data, CHANGELOG; 2 test files renamed); ~540 remain in tests/docs/scripts per the updated backlog row. Exit-gate pytest failures bisected to pre-exist on main (documented Windows flaky family).
  Detail: .context_ledger/memory/office/reviews/2026-09-16-review-s5-vocab-strip.md

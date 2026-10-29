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
- **2026-10-29 — Session 10** — Nadia / unknown model id — done-rules extension (§U item 4): provider death became a named contract state (DEGRADED_ANSWER) with its delivery composed in the contract, unanswered calls now leave recorded unknown-outcome results behind a pairing invariant, and the parent completion floor spends the bounded replan budget (19 replans → 2 on a single failed call).
  Live wire proof: scripts/live_test_done_rules.py.
  Detail: .context_ledger/memory/office/reviews/2026-10-29-review-s031-done-rules.md
- **2026-10-29 — Session 11** — Kiano / claude-opus-4-8 — permission modes + durability barriers (§U item 5, rows H + J): three named file-effect modes (read_only / workspace_write / full) pinned per session and durable, enforced at one shared seam across both tool-execution paths, fail-closed, with a model-invisible audit that doubles as a write-ahead journal (allowed call pending→done; a crash-left pending → unknown on store open, never re-executed); full lifts the workspace path boundary.
  Live proof: scripts/live_test_permission_durability.py (real server; read_only denies, workspace allows+journals, pin survives restart, interrupted→unknown). Front-end selector also shipped (b9f42aca): Settings → Agent → "File access (this chat)", verified in the real app.
  Detail: .context_ledger/memory/office/reviews/2026-10-29-review-s032-permission-durability.md

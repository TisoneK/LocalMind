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
- **2026-10-31 — Session 1** — Kofi / unknown (harness states no model ID) — fixed the dimension mismatch that silently stopped memory writes; table DDL is now the startup ground truth and the reset script no longer reports false matches.
  Root cause: startup compared the embedder only against `vector_meta.dim`, while sqlite-vec enforces the frozen vec0 table dim; the reset tool repeated the meta-only check and its swallowed DROP left the stale table in place.
  Detail: .context_ledger/memory/office/reviews/2026-10-31-review.md

---
- **2026-11-01 — Session 12** — Imani / GLM (Z.ai sandbox) — prompt structure shipped (B-2026-10-31-25: G3 + G2 + 4-layer layout + rule dedupe, 6361656a).
  Named-section registry with enforced order slots and a TURN-only cache guard; all three prompt branches assembled in the 4-layer User Objective Primacy order; staged cuts by section name; injected ledger per named section; shared rules library. 18 registry tests, suites green (failure set identical to the pre-existing environment baseline), live prompt-audit harness PASS (staged call 9274→5887 chars, rules kept).
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 12).

---
- **2026-11-01 — Session 13** — Jelani / GLM (Z.ai sandbox) — prompt system packaged as `core/agent/prompt/` (f4fb3245): engine / name catalog / staging / rules / per-surface section families / dispatcher / planner / pipeline, one import surface, flat modules retired.
  Zero behavior change — live 8765 harness reproduces the exact pre-split renders (9,274 → 5,887 staged, constraints kept); 3886 backend tests, tsc/eslint clean. Sandbox note: no backend/.venv — exit-gate checks run directly; sqlite-vec wheel was missing (38 env failures → green after install).
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 13).

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

---
- **2026-11-01 — Session 14** — Kesi / GLM (Z.ai sandbox) — the durable per-turn execution trace shipped (B-2026-11-01-26, bcef13de).
  Every turn's event stream persists verbatim (turn_traces store, retention + cascade), adapter-level model-call stamps on every path (submit/first-byte/last-byte, usage, payload size+hash), path_selected incl. negative decisions, context-assembly + stage_skipped events, context_breakdown + post_answer_lanes persisted, trace list/replay API + Trace tab, export traceRef.
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 14).

---
- **2026-11-01 — Session 15** — Zola / GLM (Z.ai sandbox) — the B-2026-10-31-25 program completed: per-turn relevance budget (e5615d7a), honest tokens-per-second (88f2f3e0), the mid-flight settle net (55dafff8), the auxiliary-call contract (6ae28323), the triads doc (869155d4).
  The budget scopes the STATIC prefix by classified intent under a hard byte-prefix constraint (contiguous-suffix cuts only; the capability index leads guidance after the re-slot; the decision rides the trace as `relevance_budget`). tokensPerSecond now divides by the recorded decode window (first-token wait + decode window on the record; the wall-clock fallback named `turn_wall_clock`). A turn that dies mid-flight settles its in-flight tool calls as unknown-outcome (one reconcile net at run()'s exit, covering all nine dispatch sites). The summary checkpoint runs on an exact-skeleton contract with fail-closed validation — a cut checkpoint never replaces history. G4 verified live (greeting gate: one provider call, zero replans, no false card); G8 delivered as docs/prompt-architecture.md. Backend 3,957 / frontend 678 / tsc clean; all three 8765 live harnesses PASS. Backlog: B-2026-10-31-25 closed (G7 → B-2026-11-01-27).
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 15).

---
- **2026-11-01 — Session 16** — Amara / GLM (Z.ai sandbox) — Continuous Goal Pursuit: investigation + cross-turn continuity build (e7d72c97).
  The owner's seven continuity questions answered from code (smoking gun: the never-implemented `_pending_clarification` scaffold); the external reference's long-work machinery verified from source (idle-driven continuation is the decisive piece LocalMind lacks — C4 = B-13's remainder). Shipped: the durable open-question record (migration 015) — a question-ending turn records it, a short non-social reply is consumed as its ANSWER (reroute lane `open_question_reply`, `open_question` TURN section at 1095, both forced-clarify exits stand down), substantive replies supersede, social gestures preserve; the session's active goal renders on ordinary turns (`carried_objective` at 1020 + the fast-path line). Backend 3,840 / frontend 678 / tsc clean; the new 19-check 8765 harness PASS (incl. the stand-down against a genuinely driven clarify decision) and the three standing harnesses re-run clean.
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 16); review: `office/reviews/2026-11-01-continuous-goal-pursuit-investigation.md`.

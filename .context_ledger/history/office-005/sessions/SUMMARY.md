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



---
- **2026-11-02 — Session 23** (numbered in the office-004 lineage; the fresh office restarted its counter — this is the first product session of office-005) — Zuri / GLM (Z.ai sandbox) — the Planner lane: the real todo list reaches the production path (B-2026-11-02-1's wiring gap closed; B-2026-11-02-2's revision + drift judge landed).
  The owner's export showed `syn-0` tool-echo todos + consult JSON rehearsing in the visible thinking. Root cause: S020's plan branch is gated on `not skip_planning` — dead on the production path since August. Shipped: the runtime draws the `{todo, outcome}` plan by model before the loop (fail-open lane; social/open-question/goal/sequence step aside), outcomes seed the gate's criteria, the gate's replan retires/adds rows with a `todo_revised` diff + the objective-fidelity lane at the close, and the consult's fenced rehearsal is stripped from thinking. 4,060 backend / 132 e2e / 678 frontend; the new live harness ALL PASS + 11 standing harnesses + eval 13/13 clean; five count-routed harness fakes migrated to content-routing.
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 23); review: `office/reviews/2026-11-02-review-s023-planner-lane.md`.

---
- **2026-11-02 — Session 1 (follow-up 1)** — Tobias / unknown (harness states no model ID) — pulled the Planner lane (8dbac565) and verified it: 36 targeted backend tests, 10 TodoList tests, tsc clean, `live_test_planner_lane.py` ALL PASS.
  The production plan path is finally live (the `skip_planning=True` dead branch), with adaptive revision, the objective-fidelity judge, and the Thinker rehearsal suppressed.
  Detail: .context_ledger/memory/office/reviews/2026-11-02-review.md

---
- **2026-11-03 — Session 24** — Sanaa / GLM (Z.ai sandbox) — the model's own plan rewrite: a mid-turn todo_write now DIFFS the live panel (B-2026-11-02-2 CLOSED).
  Resumed S024's in-flight claim (the owner's "Continue with the backlogs"); verified the uncommitted rewrite live per the bar, which exposed three things the unit suite could not see: chat.py's main drain bridged every todo event TWICE (Session-27 + Session-359 sites — double-emitted, double-persisted; one bridge per event now), and two fake-provider routing traps now documented in the new harness (the todo_write observation echoes the plan rows verbatim; the consult's findings inject as a system-role message — route on assistant tool_calls + payload `tools` presence, and on each handler's OWN request body). Shipped: the todo_write diff (retire/add/update on stable ids, closed rows never churn, todo_revised once per rewrite, retired closed to cursor + sweep), revised steps carrying outcomes (model expected_outcome → the acceptance contract; the gate replan asks per-step done-when, backward-compatible), and todo_write excluded from the gate's evidence. 4,078 backend (15 new pins) / 132 e2e / 678 frontend / ruff clean; NEW live_test_todo_rewrite.py ALL PASS (RW1–RW5) + 8 standing harnesses + eval 13/13; the three real-provider harnesses remain the environment note (A/B-verified not a regression).
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 24); review: `office/reviews/2026-11-03-review-s024-todo-model-rewrite.md`.

---
- **2026-11-03 — Session 25** — Jengo / GLM (Z.ai sandbox) — the markdown render pipeline: the owner's "the UI does not format the output in style eg tables etc its just text" diagnosed on the wire and fixed at the root.
  First thing: S024's ledger close was sitting UNCOMMITTED in the tree (the prior session died between edit and commit — the owner's "why do you keep crashing before finishing") — committed as 2897b0f6 before the claim. Then the evidence-first probe (`live_test_markdown_render.py`): the frontend renderer WORKS (react-markdown + remark-gfm + themed tables) and the transport is CLEAN (well-formed + GLM-degraded markdown crosses SSE and history byte-exact) — the ROOT CAUSE was the response_formatting section existing ONLY on the scoped-agent registry while the parent warm-kernel and chat surfaces (where the turns users ask for tables on actually go) carried none. Fix: one shared contract text (`prompt/sections/formatting.py`) at the shared slot 405 on ALL THREE surfaces (after the tool index so the SOCIAL contiguous-suffix cut can never drop it from a conversational turn) + the GFM pipe-table line; the renderer gained two conservative repair passes (full-width ｜/dash normalization scoped to leading-pipe rows, missing-delimiter-row insertion that never re-delimits a real table). 8 + 10 + 5 new pins; backend 3,955 + e2e 132 / frontend 693 / ruff clean; harness ALL PASS (MD1–MD5) + 8 standing harnesses + eval 13/13. Found live and filed: B-2026-11-03-1 (the zero-tool forced-replan storm — 20 provider calls measured). Real-provider run of the harness remains the owner's-box follow-up.
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 25); review: `office/reviews/2026-11-03-review-s025-markdown-render-pipeline.md`.

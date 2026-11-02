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

---
- **2026-11-01 — Session 17** — Nia / GLM (Z.ai sandbox) — G7 request derivation + C4 idle continuation (d47519de): the prompt/context program COMPLETE, the goal-pursuit program's decisive piece built.
  G7: the durable trace now carries content-free composition + fingerprint stamps (STATIC registry composition + prefix sha on the budget event; the TURN message's exact section texts + rendered sha on the injected-items ledger; per-call input-selection stage + system chars/sha on the assembly events), and `core/agent/trace_derive.py` re-derives each loop call's payload from the record + the prompt package's contracts with named verdicts (exact char arithmetic, budget drop-set suffix contract, render order vs the SECTION_SLOTS catalog, stage validity, sha reuse, byte-for-byte TURN rebuild — opaque surfaces named honestly); `?derive=1` on the trace replay; the prompt-audit lines link to trace calls by fingerprint (sha = byte-proof). C4: `core/goal_idle.py` picks an armed deep dive back up after the transport dies — background engine rounds under reservation-then-admission, own traces, fail-closed on crash, the same durable cap blocker — with human resume (`extend_rounds`) / pause endpoints and the safety contract untouched (activation stays process-local). Fixed live: native `update_goal`/`get_goal` calls were flattened unparseable — the model could never mutate a goal. Backend 3,997 / ruff clean; six harnesses PASS (two new: derivation 19/19, goal-idle 17/17 — the connection dropped mid-deep-dive and the deep dive continued to its cap with no new request; the resume ran exactly to the extended cap).
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 17).

---
- **2026-11-02 — Session 18** — Ayo / GLM (Z.ai sandbox) — the standing eval harness (B-2026-10-31-23): 13 scenarios × the audit's six metrics against the live app — and its first run caught two real product defects.
  The suite (`scripts/eval_suite.py` + `eval_scenarios.py`): the audit's ten scenarios + the absorbed §1.1 (perspective polarity) and §1.2 (reflective/no-meta-tools) cases + the continuity integration case (offer → open-question record → bare "yes" → reroute → the offered tool EXECUTES → record consumed — the C5 offer-is-DONE shape Nia handed into the row, scored end to end). Structural checks gate in both provider modes, defect-signature exclusions always gate, `--provider real` runs the app's real settings with keys never read (refuses fast when absent — the real-provider scoring run stays the standing follow-up); results = JSON (backlog re-prioritization) + markdown report + per-turn SSE artifacts + a provider debug log. FIRST FULL RUN found: every native calculator call died TWICE (the name/intent mismatch — SHELL fallback + the allowed-tool fence comparing intent values against tool-name sets), both fixed, the fence now names its set on the log record, and READ_ONLY_TOOLS gained offline arithmetic. Backend 3,997 (needs `ulimit -n 4096` in this sandbox) / 8 new fence tests / ruff clean; all six 8765 harnesses PASS; eval suite 13/13 (completion 1.0, tool success 4/4, recovery 1/1, 0 unnecessary questions).
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 18).

---
- **2026-11-02 — Session 19** — Zuri / GLM (Z.ai sandbox) — the owner's port-flexibility report built end to end (03ebcf3e): the dev stack now moves instead of crashing when another app holds a port.
  `npm start` runs `scripts/dev-full.js`, which resolves ports BEFORE spawning (free → use; healthy LocalMind → reuse via a watcher slot, never a second instance; foreign app → next free port with a loud notice; `LOCALMIND_PORT_STRICT=1` → the old fail-fast, naming the occupant). The choice propagates by env (`LOCALMIND_PORT` / `LOCALMIND_HOST` / `LOCALMIND_FRONTEND_PORT`) to Vite (strictPort + explicit IPv4 bind; the config's leftover 5173 unified to the stack's 3000), the proxy target, Electron (env URLs + packaged-mode resolve before the window loads), the backend bind and CORS. `core/ports.py` is the single testable home for the occupancy rules; `server.py`'s exit-42 guard now names WHO holds the port. Fixed en route: the one fetch bypassing the shared relative API base, and the hung-connect probe hole (a `socket.setTimeout` probe reads a non-accepting listener as FREE — hard timer race in both JS copies). Live: five resolution scenarios, fallback (backend 8001, proxy + CORS green), reuse + watchdog teardown, both guard messages, default `npm run dev:full` path. Backend 4,020 / frontend 678 / tsc + ruff clean.
  Detail: .context_ledger/memory/office/agents/sessions.md (Session 19).

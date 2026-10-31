# Office 003 — accomplishments record (permanent)

- Opened: 2026-09-21
- Closed: 2026-10-31
- Sessions: 21

The frozen office lives at history/office-003/ until it is zipped into
archive/office-003.tar.gz. This record stays in history/ forever — even after
the tarball is garbage-collected, the office is never forgotten. Not read at
session start; deliberate lookback only.

## Accomplished

- **Identity context injection (roadmap §U item 2):** stated facts boot-cache,
  labeled provenance, an unconditional declared-absent block; settings fields +
  `POST /api/settings/identity` hot-apply; injection on all four chat surfaces
  (bootstrap, per-turn env, fast path, history fallback — the last previously
  had NO user context); zone-named aware clock; acceptance-gate identity class.
- **Provenance & audit symmetry (roadmap §U item 3):** retry-attempt ledger
  (`{attempt, error, waited_ms}` on the tool record end to end, incl. the
  parallel path), typed injected-items ledger (exact rendered text + producer,
  one `context_injected` event per surface, persisted and restored on reload),
  degraded provider-death phase in the strip, frontend outcome truth (errored
  reply ⇒ failed turn, plan pill "· didn't finish", attempt-ledger expansion).
- **Done-rules extension (roadmap §U item 4):** provider death is a contract
  state (`DEGRADED_ANSWER`) with its delivery composed in the contract;
  unanswered calls leave recorded unknown-outcome results behind a pairing
  invariant (batch no longer loses siblings); the parent completion floor
  spends the bounded replan budget. Independent second review: **PASS with
  findings, release stands.**
- **Trajectory view → projection of the record:** one deterministic reducer
  (`frontend/src/lib/localmind/turnProjection.ts` + `md5.ts`) replaces the live
  imperative accumulator in `useLocalMind.ts`, so the run tree and phase strip
  derive identically live and on reload; a cross-language contract test pins
  both ports to a fixture generated from the real backend; `has_content` now
  requires real work (a direct turn no longer keeps a run node a reload can't).
- **Permission modes + durability barriers (roadmap §U item 5, rows H/J):**
  three named file-effect modes (`read_only` / `workspace_write` / `full`,
  fail-closed on unresolved), session-pinned and restart-durable
  (`session_permissions`), a `permission_audit` write-ahead journal
  (pending → done/failed, interrupted rows reconciled to `unknown`), one shared
  enforcement seam across both tool-execution paths, `full` lifts the workspace
  boundary, API + Settings → Agent → "File access (this chat)" selector shipped
  and live-verified.
- **Live-test harness exit-code fix:** the three older harnesses now
  `server_close()` the in-process fake provider before the port sweep, so a
  PASS no longer exits non-zero on Windows.
- **Re-identity:** palettes renamed, Graphite Blue the default in dark mode.
- **Office hygiene:** core migrated/verified at 2.2.1, `ledger-guard` hooks
  installed, flaw/inefficiency logs kept for the stale-tip collision family and
  live-harness fake-provider races.

## Decisions still in force

- The full carried ADR set (ADR-1..71, frozen at
  `history/office-002/plans/decisions.md`) plus the binding guardrails in
  `memory/workflows/active.md`: ADR-34 event order; `Hi`→zero-provider-call
  boundary; thinking-aware timeouts; ADR-40 live-verify tool SELECTION on a
  flash-tier model + cerebras before any schema cut; ADR-41 z.ai thinking ON
  (never re-add a thinking-disable for GLM); the provider-stall watchdog
  fall-through; Parent-only scope.
- ADR-62..66a thinking infrastructure; ADR-66b turn bus (per-provider
  concurrency budget before widening parallel lanes); ADR-67 refuse only on a
  verified fact and name it plus the confirming flag; ADR-68 no canned plans;
  ADR-69 failover layer silent, announced, bounded, never a silent local→cloud
  fallback; ADR-70 commands/installs are user settings; ADR-71 the state engine
  is built beside Classic and owns its state.
- ADR-72 (written this office): the state engine is environment-agnostic and
  owns its architecture; LocalMind is only its first adapter. The engine
  package has no import of LocalMind (enforced by a boundary test); everything
  host-specific lives in an adapter; ways a run can end are injectable
  `TerminalCondition`s; no `SearchStrategy` until a second strategy exists.
- Working agreements: the live-testing bar is MANDATORY for loop/tool/adapter
  changes; cure the disease, not single prompts; model- and env-agnostic fixes;
  never port 8000 (isolated 8765 + `LOCALMIND_HOME`); no secrets in tracked
  files; push after each commit; project code and `.context_ledger/` committed
  separately.

## Open threads

Re-seeded into the new office's backlog (actionable, with a next step):
state-explorer UI + engine selector; state-engine slice 2 (execute behind the
ADR-67 flag, second `Environment`, beam > 1, persisted state); benchmark the
state engine against Classic; confirmable-refusal rollout (ADR-67); turn-bus
follow-ons; provider-failover follow-ups; Windows test portability + exit-gate
reliability; Windows verification of the state engine; learning transfer
(recall persisted lessons at decision time); anti-sycophancy guard; memory
edit-path tolerance (`PATCH /api/memory/{id}` vs the plain-text fallback); the
"conversation too long" false positive; goal-rounds continuation/resume beyond
the open SSE request; turn economy for verification-heavy tasks;
association-level grounding judge; feedback-turn routing; a repo-root pytest
config for the async-isolation flake; routing the flat chat tool-pills through
the trajectory projection; mode-gating mixed-intent effecting tools
(git/process/browse); settings/architecture tidy; LocalMind becoming a
consumer of the standalone `ti-matrix` engine.

Recorded here but not queued (parking-lot material): guided handoff to the
browser tool for JavaScript-rendered pages (P-2026-10-27-1); pre-action recall
of stable facts before identity/location/preference answers; multi-step
planning routing at tier-3 triage; skill-gap detection; memory junk-row sweep;
ledger-vocabulary strip remainder; the two dead-code decisions
(`filters.py`'s `is_code_output`, `terminal.py`'s `TerminalSessionBridge`);
per-phase thinking-segment persistence; frontend context-menu test health;
provider model-switch policy; the harness-skin information architecture; the
`B-2026-09-21-13..25` deferred set.

Live-test harness finding for the next owner: fake providers keyed on absolute
request position race the product's out-of-band provider calls (title
refinement, conversation-state/init classification) — content-key the fakes or
drain scheduled work between probes. The no-evidence death wording in
`loop.py` also still sits outside the turn contract (its matching contract
shapes are unreachable).

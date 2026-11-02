# 2026-11-02 — S022 (Kenji) — "Fix all": the Arsenal-export findings

**Task:** the owner's `Fix all` on the 2026-11-02 chat-export analysis
(session-1793600092469, "Arsenal yesterday result") — the six consolidated
findings, minus what S020 (Todo Planning & Hierarchical Execution, f76cabff)
and S021-in-flight (adaptive plan revision + objective-fidelity judge,
B-2026-11-02-2) already own.

## What shipped

| # | Finding (owner's table) | Fix | Commits |
|---|---|---|---|
| P5 (Critical) | Objective→execution translation — the investigation turn's evidence was `system_search "recent 1 10"` → `Filter: name~'1 10'`, an unrelated file scan | `system_search` args stay structured end to end (`_extract_tool_input` branch, same class as the goal-tools live fix); the plain-string heuristic maps digit tokens to limit/window bounds, never a name filter (except genuine numeric filenames on a files search) | 605a3bf3 |
| P1 (High) | Capability awareness — "I don't have access to live sports results… shall I look that up?" one turn before web_search answered | results/result/yesterday/fixtures/standings/leaderboard force the parent loop (backend keyword list + the declared keep-in-sync frontend mirror); the capability-honesty spine names the internet and live/current information explicitly (the model had generalized its never-claim-no-access rule from the filesystem to nothing else) | be92cd4c |
| P2 (Critical) | Evidence-based self-evaluation — the agent claimed it "had not actually used the search tool" one turn after web_search delivered the result | the free `transcript_focus` slot (1110) now carries an execution record: last 6 tool calls of the session's recent turns (tool / honest outcome / input / output heads), built by the runtime from the persisted tool-call timeline, rendered into every loop turn | e893aced |
| P4 (High) | Execution lifecycle & latency — answer visible, turn still held; the 82.6s turn | the completion judge runs thinking-off (per-call adapter override) with a 5s bound (was 8s thinking-on, timing out routinely — the export's `unjudged` at 8.0s twice per turn); the post-turn services (fact extraction + reflection, 90s budget) are DETACHED from the transport — done propagates, the SSE closes, the bookkeeping finishes in a retained background task (`drain_post_turn_services` = test + graceful-shutdown seam) | e893aced |
| P6 (High) | Provider resilience — "current provider is z.ai but it shifted to bankofai, meaning its rotating and thats a very bad design" | the implicit failover tail ("every other enabled provider that has a key") is RETIRED — the only fallback is the connection's explicit `fallback_to`, running the destination's configured model; the switch records `{from, code, to}`; the turn's persisted identity stamps report the adapter that ACTUALLY served (`last_served_by`/`served_model`) + the failover note — provider=zai on a BankOfAI-answered turn is structurally impossible now | e893aced |

(P3 — conversation statements becoming Todos — shipped by Jabari S020's
`{todo, outcome}` classify contract; the drift judge is Amara S021's
B-2026-11-02-2, in flight. The output-integrity half of the owner's finding
5 — raw evidence dumped as a final answer when synthesis is interrupted — is
partially covered by the existing provider-death honesty path
(`agent_loop_degraded` + evidence preservation, tested by
`tests/core/test_provider_death_evidence.py`); the deeper synthesis-recovery
shape remains with the completion-judge program.)

## Design decisions worth the record

- **The judge stays an LLM lane, not a phrase list.** Its module docstring's
  reason for existing is that phrase lists miss novel wordings; the fix cuts
  its COST (thinking-off + 5s), not its reach. ADR-41's thinking-ON ruling
  governs the answer path; a one-word verdict lane is the legitimate
  thinking-off case (the empty-after-reasoning recovery precedent).
- **The detachment keeps the withhold guarantee intact.** The acceptance gate
  still runs pre-done ON PURPOSE — on buffered turns it decides whether the
  iteration's text is the answer; that is the S332 duplicate-answer contract.
  What left the transport is the 90s bookkeeping class. The judge's nudge, a
  gate replan, and the honest-stop report remain the "outstanding work"
  surfaces the owner asked for; S020's todo lifecycle carries the rest.
- **Failover became explicit-only by owner ruling.** The implicit tail was
  documented designed behavior (CHANGELOG 2026-08-31, Nadia S002's
  invalid_request→failover); the owner's 2026-11-02 Deterministic Provider
  Management table supersedes it. A user who WANTS cross-provider fallback
  sets `fallback_to` — and gets an honest, recorded switch.

## Verification (the bar, reported honestly)

- **Unit:** backend 3,915 passed / 2 skipped / 0 failed (20 new export-fix
  pins + the failover suite rewritten to the deterministic contract); e2e
  132 passed; ruff clean on all touched paths; frontend client suite 21
  passed + tsc clean (two stubs updated: the judge's call now carries
  `thinking_override="off"`, so strict test adapters accept kwargs).
- **LIVE (deterministic fake provider — no key in this sandbox; the
  real-provider run stays the standing follow-up, as recorded by Ayo S018):**
  new standing harness `scripts/live_test_arsenal_fixes.py` ALL PASS —
  P5 structured args survive dispatch (no `name~'1 10'` filter, the recent
  op ran with its bounds), P6 persisted stamps report the actual server
  (fakeprov/ps-flash) with no rotation, P4 provider calls arrive AFTER the
  SSE closed (services detached), P2 the explain-yourself turn's context
  carries `Execution record … system_search [done]`.
- **Standing harnesses re-run clean:** prompt-structure PASS, greeting-gate
  PASS (exit-1 is the sandbox teardown broken-pipe quirk — the assertion
  line passed), turn-trace PASS, eval suite 13/13 (rate 1.0, 0 unnecessary
  questions across 12 gated turns — the P1 live face).
- **Assumed / not exercised live:** a real failover switch (needs two real
  keyed providers — the adapter path is unit-tested end to end including the
  switch record; the stamp reads are live-verified without a switch); the
  judge's pending-verdict nudge on a real pending reply (the fake provider
  answers neither DONE nor PENDING — the lane is unit-tested and its
  fast/cheap behavior is live-visible: verdict at ~250ms).

## Process notes

- Check-in collision: the board moved from S018 to S021 while I read it —
  Zuri S019 (port flexibility) and Jabari S020 (Todo Planning) landed, and
  Amara S021 is building B-2026-11-02-2. Re-based the check-in as S022 and
  scoped "Fix all" to the findings they do NOT own. Also corrected the prior
  conversation summary's claim of port-flex commit `03ebcf3e` — no such
  commit existed at check-in time; Zuri's landed work is what shipped it.
- The sandbox needed `pip install sqlite-vec` + `pip install -e 'backend[dev]'`
  again (the known recurring loss); `ulimit -n 4096` for the suite; the
  stale-harness-server leak struck once (killed by PID from `ss`).

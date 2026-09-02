# Current Task

**Status:** IDLE — Session 408 COMPLETE: ADR-57 slice 1 implemented and
shipped (recovers the cut-off predecessor session that had pushed the doc
corrections but left its implementation uncommitted). Post-tool final answers
now stream live (gated: no criteria, post-tool, non-high-stakes last tool;
pending-hold catches mid-stream tool-call markers; prefix-aware flush dedupe
protects the S332 guarantee). Live-verified before/after on bankofai
(1-token burst at 32.8s of a 34.3s turn → 125 streamed token events) and zai
(88 events, clean gates). Pre-existing S332-B head-drop on the mid-stream
path found and fixed in the same pass. Commits 2d9b733, 6bc5437, a42d901 —
all pushed to main.

**Feature:** none

## Notes for the next session

- **ADR-57 slice 2 = Thinker gating.** The Session 408 baseline trace shows
  **3 reflexive agent_thinker_start/done calls on ONE research turn** — the
  concrete number slice 2 exists to cut. Gate the Thinker to fire on
  failure/multi-source, not after every tool; keep it streamed.
- First-loop rejection mechanic (model-emitted done → rejection path) is
  wired but was never exercised live in 408 — trace it before relying on it.
- Tool-talk recovery after a streamed head leaves an orphan fragment
  (cosmetic); frontend supersede mechanism is ADR-57 Open-Q4.
- Standing: ~41 unattributed full-suite failures + the 34-error ruff
  baseline still need a peer pass (S405-407 note); live-test authorized
  per-item, port 8010 for the user-facing test backend (never 8000).

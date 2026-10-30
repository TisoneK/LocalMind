# Review — S032 Rafael — trajectory view → projection of the record

**Date:** 2026-10-29 · **Agent:** Rafael (S032) · **Model:** Opus 4.8 (claude-opus-4-8)
**Scope:** `docs/reference-harness-gap-inventory.md` rows **B + G** — the architecture
invariant *"the trajectory view is a pure projection of the durable log, so the UI can
neither show what was never recorded nor hide what was."* One of three parallel worktree
sessions split from one handoff (siblings: durability+permissions, harness exit-code).

## The defect (root cause)
The agent trajectory — run tree + phase strip — was reconstructed **twice** from the same
obs-event stream:

1. **Backend**, at persist time: `agent_workspace.build_run_tree` / `build_agent_phases`
   project `ObsCollector.history()` → the `messages.agent_runs` / `agent_phases` columns the
   UI renders **on reload**. Deterministic ids.
2. **Frontend**, live: `useLocalMind.ts` **accumulated** the same events imperatively into
   `agentRuns` / `agentPhases` as they streamed. Non-deterministic ids
   (`buildAgentPhase` used `Math.random()`), lost list payloads (the `_as_list` note in
   agent_workspace.py), and a hand-maintained mirror of the backend logic (that module's own
   docstring: "mirrors the frontend logic").

Two code paths, kept in sync by hand, that diverged — so the live view was an accumulator,
not a projection, and could disagree with what a reload showed.

## The fix
- **One projection reducer**, `frontend/src/lib/localmind/turnProjection.ts` — a faithful,
  deterministic port of `build_run_tree` / `build_agent_phases` / `_tool_call_dict` /
  `collect_injected_items` (plus `md5.ts` to reproduce the tool-id hash byte-for-byte). The
  live stream now feeds its recorded obs events to this one reducer (`applyTrajectory` in
  `useLocalMind.ts`), replacing the imperative accumulation of run tree / phase strip /
  acknowledgement / injected items. The flat chat tool-pills (`message.toolCalls`) stay on
  the existing live path — see Follow-ups.
- **A cross-language contract test** (`turnProjection.contract.test.ts` +
  `tests/core/test_trajectory_projection_contract.py`) pins both ports to ONE generated
  expected artifact (`tests/fixtures/trajectory_projection.*.json`, written from the REAL
  backend by `scripts/gen_trajectory_expected.py`). Change one projection and one side goes
  red until they agree — the divergence can't silently return.
- **A real divergence the live test surfaced and I fixed:** a direct-answer turn streams an
  `agent_loop_start` (→ a "working" lifecycle phase), but the backend's direct/fast persist
  paths store `agent_runs=None` while the success path's `has_content` guard **counted**
  lifecycle phases — so the one path that ran the guard kept a run node a reload could not.
  Aligned `has_content` (backend + the frontend projection) to require real work — a tool,
  evidence, a child, a **decision-strip** phase, or an error — not lifecycle-only narration.
  Now every persist path and the live view agree: a direct chat turn shows no run node
  anywhere.
- Small faithful improvements folded in: `_tool_call_dict` now carries the retry ledger
  (gap §G "retried attempts retained and visible"); the turn title is sanitized identically
  on both sides (`cleanTitle`).

## Verification
- Frontend: **660/660** vitest green (incl. the new md5, projection, and contract suites);
  `tsc -b` and `eslint` clean. Two pre-existing hook tests updated to the real dual-channel
  stream (the projection reads the raw `obs_event` copy the backend always yields alongside
  the bridged top-level tool_call) and to the content-guard semantics.
- Backend: the trajectory contract (7/7) + the workspace/sessions consumers (133) green;
  `ruff check backend/src` clean. Full-suite run recorded in the session entry.
- **Live, in the running app** (`scripts/live_test_trajectory_projection.py`): a real agent
  turn on the isolated 8765 stack + scratch HOME — the trajectory the UI builds live from
  the streamed obs record equals the persisted/reloaded tree (run tree + phase strip match
  structurally) and a replay is stable. **PASS** with the deterministic fake provider (the
  tool/lifecycle/phase run-tree path, real loop-emitted events) **and** `--real deepseek`
  (the real adapter/model path; its turns answered directly, so the real-model tool path is
  covered by the fake run + the contract fixtures, not a live real-model tool call).

## Follow-ups (filed to backlog)
- The flat chat tool-pills (`message.toolCalls`) and the reload path's `_collect_tool_calls`
  still use the per-tool shape divergence (live friendly label/preview vs persisted raw);
  unify them under the projection too. Advances B-2026-09-21-21 (the useChat SSE-switch →
  reducer extraction).
- The parent run's wall-clock duration is ~0 on both live and reload (both stamp
  `startedAt`≈`completedAt` at projection time) — a pre-existing `build_workspace_artifacts`
  limitation, now simply consistent; pass real turn timestamps if a duration is wanted.
- When durability+permissions lands an append-only event log, reload can replay IT through
  `turnProjection.ts` for a single-reducer path end to end.

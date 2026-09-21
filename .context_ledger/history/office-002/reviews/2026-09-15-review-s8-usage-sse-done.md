# Review — S008 (Imani): provider_usage into the SSE `done` event

**Date:** 2026-09-15 · **Agent:** Imani (S008) · **Model:** qwen3.8-flash
**Platform:** Windows 11 (10.0.26200 x64), Lameck checkout, isolated worktree
`../LocalMind-s008` · **Role:** engineer (product) · **Core:** 1.1.3
**Backlog:** B-2026-09-11-1 (High) · **Product commit:** `7bd41196` (main)

## 1. The gap

The agent loop accumulates per-call provider usage on the final chunk
(`StreamChunk(done=True, usage=...)`), but the SSE bridge in
`backend/src/api/routes/chat.py` built a bare `{"type": "done"}` and dropped
it. Consequence: per-turn token cost was unmeasurable from the wire, so the
benchmark's token-efficiency half (`_usage_tokens` → `usage_tokens`) recorded
`null` for every test even though the harness plumbing was ready. The
backlog's second half — the conversational fast-path emitting
`provider_usage={}` — had already been fixed by `bcc383ce` (verified via
`git log -L` on the fast-path branch); the sole remaining gap was the bridge.

## 2. The fix (behavior-only, narrow)

`_event_stream`'s `chunk.done` branch now forwards `chunk.usage` as
`provider_usage` on the done payload **when non-empty**. The contract is
honest-zero: an empty mapping (canned fallback, memory op, error path,
upload-error generator) stays omitted — the field is never fabricated on a
turn that made no provider call. Two new tests in `tests/api/test_chat.py`
pin both shapes (usage forwarded; field omitted on a no-call turn), reusing
the existing `_parse_sse` / Engine-process-patch patterns.

## 3. Verification

- **Unit:** 133 passed (`test_chat.py` + `test_fastpath_synthetic_metrics.py`
  + `test_trivial_input.py`) — the synthetic-metrics and trivial-input suites
  guard the honest-zero contract the fix preserves.
- **Pre-commit gate:** green (tsc, ruff, conflict-markers, backlog-dups) —
  with the Windows `sh`-on-PATH prerequisite (see §5).
- **Integration gate:** green (incl. `npm run build`).
- **LIVE (isolated port 8765, scratch LOCALMIND_HOME, bankofai/mimo-v2.5):**
  before (main) = bare `{"type": "done"}` on both a fast-path turn (`hello`,
  0 tools) and a tool-loop turn (`listdir`, 4 tools) — `usage: null`;
  after (worktree) = `{"type": "done", "provider_usage": {...}}` on both:
  fast-path `{prompt_tokens:270, completion_tokens:178, total_tokens:448}`,
  tool-loop the `total_*` accumulation set (`total_prompt_tokens:4869`,
  `total_completion_tokens:174`, `total_cached_tokens:2048`, `llm_calls:1`).
  Evidence: `scratch/sse-s008-{before,after}-*.sse`,
  `scratch/results-s008-{before,after}.json`.
- **Backlog acceptance (benchmark subset):** `lm_benchmark.py --tests CAT1-1`
  on the fixed tree → the TOKEN EFFICIENCY section reports
  `input 313 / output 173 / total 486` (was `null`) — `usage_tokens`
  populates end-to-end through the harness's own `_usage_tokens`.

## 4. Coordination

Not solo — Baraka (S005) live in the main tree (tree-wide ledger-vocab
comment sweep, uncommitted `loop.py`), Tega (S009) and Jabari (S010) checked
in mid-session. Worked the full collab path per the project override: own
worktree, `note` (flagged the chat.py/agent_runtime.py overlap with Baraka's
sweep — my diff is behavior-only, no comment rewrites, trivial rebase) +
`claim` + `release` events, additive-only roster edit, never `git add -A`.
`loop.py` never touched/claimed. Two push races resolved by rebase, zero
collisions (disjoint paths). Integrated to main via the refspec
(`git push origin HEAD:main`) since the main checkout is Baraka's workspace.

## 5. Friction logged

- **flaws/log.md:** the gates' `sh scripts/...` lines have no teeth on a bare
  Windows PATH (`ledger-gates.cmd` → "sh not recognized"; prepend Git's bin).
  Open — the launcher should state/apply the prerequisite.
- **inefficiencies/log.md:** Windows console traps — cp1252 stdout crashed
  the benchmark's non-ASCII summary line (set Python IO encoding to UTF-8);
  `git commit -m` with embedded `{"..."}` broke PS parsing (use `git commit -F`).

## 6. Open items after this session

None from B-2026-09-11-1 (closed). Carried in the office: Baraka's tree-wide
sweep (B-2026-09-15-1), Tega's reload fields (B-2026-08-17-4), Jabari's
embedding fallback (B-2026-08-20-12), and the backlog's remaining rows.
Owner note: bankofai worked this session (not quota-exhausted as S4 reported
2026-09-15) — the primary live-test provider is usable again.

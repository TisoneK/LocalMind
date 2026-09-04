# Current Task

**Status:** IDLE — Session 416 closed. P0 Context Engineering **Step 1
(surface cache data to the UI) shipped** in `05e332f` and live-verified on
bankofai/qwen3.8-flash (isolated 8765): `turn_complete` now carries
`cached_tokens`/`llm_calls` + accumulating `total_*` usage; the stats bar
shows a cached chip (hit %) and a calls chip; the context meter shows the
cached share. 14 new tests; report in
`.context/memory/reviews/2026-09-04-review.md`.

**Feature:** `p0-context-engineering` (preview) — Step 1 complete; Steps 2-8 open

## Notes for the next session

- **Next: Step 2 — byte-stabilize the system prefix** (addendum plan).
  Audit `build_agent_system_prompt` for intent-varying sections (persona,
  safety, skill fragment); split a durable byte-stable baseline from the
  intent tail; put the cache breakpoint at the baseline end. Live-verify
  cache hit rate on intent-switching turns.
- **Enabler already on the wire:** `total_prompt_tokens`/`llm_calls` ride
  `turn_complete.provider_usage` — an "equivalent work across N calls"
  display (addendum Component 4) needs no new backend plumbing.
- **Caveat:** bankofai omits cache telemetry on some calls (trace-b: 0
  cached) — the UI hides the chip when unreported; don't treat a 0 as a
  regression. The chat.py `metrics` re-emit didn't fire in traces (dead on
  the parent path; turn_complete + /api/metrics are the real channels).
- **Environment:** Windows box — no pytest-timeout plugin (drop `--timeout`);
  Git Bash mangles `$VAR`-path redirects in compound commands (use the
  `scratch/s416/trace.sh` baked-path script pattern); frontend vitest flakes
  under parallel local load (stash-baseline flaked 9 vs 1-2 on the changed
  tree — verify failures in isolation).
- **Standing:** ~36 pre-existing Windows backend failures + 32-34-error ruff
  baseline still need the deferred peer pass.

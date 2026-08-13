# Current Task

- **Session:** 193 (2026-08-13, complete)
- **Feature:** adr-8-agent-centric-routing (Phase 4 track 2 — deterministic file-ops)
- **Task:** Build the deterministic file-ops execution layer — the other half of
  the root fix for the "find my CV and read it" failure (chosen by user after
  Session 192's loop bound).
- **Done (193):**
  - New `core/file_ops.py`: detect_read_request + pick_best_match +
    execute_file_ops (find→pick→read as code, same is_path_allowed boundary
    as file_task) + deterministic formatters.
  - `tools/find_path.py`: metadata["paths"] structured output.
  - `thinking_dispatcher.py`: file_ops primary_domain on read-chained find
    plans + new direct-read branch (read/show/open/summarize my X) with
    guards (listing/path-ish/non-file/investigation/debug/doc-noun whitelist).
  - `engine/_pipeline.py` 2c fast-path: deterministic chain, ONE synthesis
    call, deterministic evidence fallback when model empty/errors, tool-fence
    honored, blocked-read surfaced.
  - Full backend **1706 green**, ruff clean, frontend tsc + 137 vitest green.
- **Next:** ADR-8 Phase 4 track 1 (task-type classifier) or Phase 2 (wire
  build_context into BaseAgent.run) — both need real-model testing per the
  flaw log. Phase 4 track 2 established the blueprint: primary_domain → engine
  routes deterministically with zero LLM.

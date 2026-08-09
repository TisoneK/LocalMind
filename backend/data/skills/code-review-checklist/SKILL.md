---
name: code-review-checklist
description: What to check when reviewing a code change in this repo before calling it done.
---

# Code review checklist

## Correctness

- Does the change do what it claims, and only that? (no scope creep)
- Are edge cases handled: empty input, missing keys, path outside allowed
  folders, tool results that fail mid-way?
- Did the author verify with the actual validation commands (pytest, ruff,
  `tsc -b`, `vitest`) rather than eyeballing?

## Safety gates (LocalMind-specific)

- File-writing tools: is the `is_path_allowed` / permission gate present and
  shared (via `prepare_edit` / `resolve_write_path`), not duplicated?
- Per-run registries (proposals, subgoals): are they contextvars-based with a
  `reset_*()` at the top of `AgentLoop.run()` so nothing leaks across runs?
- New meta-tool Intents: are they excluded from the routing-map coverage test
  in `tests/agents/test_selection.py`?

## Style

- Ruff-clean (non-E501), matches surrounding conventions, imports sorted.
- Reuses existing helpers instead of duplicating logic.
- Tests updated in the same commit (counts, new Intents, wiring).

## Context protocol

- If the change touches `.context/memory/`, append-only files were appended,
  not rewritten; the session was logged and pushed.

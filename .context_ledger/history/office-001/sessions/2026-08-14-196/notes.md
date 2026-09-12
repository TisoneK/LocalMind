# Session 196 notes — Freebuff/Codebuff orchestration review

## Evidence levels

Official Codebuff docs and published agent definitions are authoritative for the agent contract. The Freebuff repository README is authoritative for product-level claims such as specialized agents and isolated Desktop parallel workspaces. Reverse-engineering/proxy search results mention hosted `/api/v1/agent-runs`, `codebuff_metadata`, and `ancestorRunIds`, but no official source reviewed documents those endpoints. They are explicitly excluded from LocalMind requirements.

## Exact official examples captured

- `spawn_agents` takes `{ agents: [{ agent_type, prompt?, params? }] }` and runs entries in parallel.
- `spawnableAgents` is an allowlist of agent IDs.
- `includeMessageHistory` defaults false; agents opt in when needed.
- `outputMode` supports `last_message`, `all_messages`, and `structured_output`; `outputSchema` can validate structured output.
- Generator yields: tool-call objects, `'STEP'`, `'STEP_ALL'`; `set_output` returns structured results to the parent.
- `researcher-file-explorer` has only `spawn_agents` + `set_output` and fans out to `researcher-file-picker`.
- `file-picker` has only `find_files`; `code-searcher` has `code_search` + `set_output`.
- `reviewer` has only `run_file_change_hooks` + `end_turn`, inherits history, and cannot modify files.
- `context-pruner` has only `set_messages`, inherits history, and deterministically simplifies terminal/tool results before shortening old messages.
- `editor` owns mutation tools and a bounded programmatic step loop; `thinker-best-of-n` generates N candidates and delegates selection.

## LocalMind comparison

Already shipped: BaseAgent directory registry, task-type selection, playbooks, scoped tools, per-agent model routing, `delegate` handoff, `delegate_parallel` (max 5), `delegate_inline` context-pruner, immutable DelegationInstructionPacket, parent/child run IDs, final-output-only child messages, fixed ReviewerAgent output schema, deterministic verifier/acceptance gates, and lifecycle observations.

Still active: `_pipeline.py` invokes `should_use_sub_agents()` before modern agent selection; parallel child runs share filesystem state; `delegate`/`delegate_parallel` parent-facing content is not uniformly bounded even though metadata previews are bounded; ReviewerAgent is not an unconditional post-mutation runtime stage.

## Tooling friction

- `code_search` failed once when given a compound `cwd` (`backend/src/core backend/src/agents`) and once when given a file path as `cwd`; rerun with a single directory. This is project-tool invocation friction, not a product finding.
- `context-sync verify` refreshed `.context/memory/core.lock`; this expected context change must be included in the context closeout commit.

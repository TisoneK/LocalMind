# Current Task

**Status:** IDLE — Session 419 closed. P0 Context Engineering **Step 3
(Memory Retrieval Gate)** shipped in `38739c5`: `cap_facts_to_budget` (~500
tokens) applied at `agent_runtime._memory_facts`. Scoping finding — retrieval
was already per-request/conditional/semantic-top-K/relevance-thresholded, so
the only missing Component-5 piece was the token budget cap (count cap ≠ size
cap). 5 cap tests + 50 memory regression pass; ruff clean. Behavior unchanged
on normal turns (ceiling for long-fact sets). Also this session: UI rework —
Actions tab (`fce41d5`), Terminal (`06d1d12`), terminal command grouping +
newest-first Actions/Workspace (`9fa9827`).

**Feature:** `p0-context-engineering` (preview) — Steps 1-3 complete; 2b + 4-8 open

## Notes for the next session

- **Live-verify Step 3 when a provider window is free:** run the prompt-audit
  harness (`scripts/live_test_prompt_audit.py --adapter bankofai --model hy3`)
  before/after on a memory-heavy session; confirm the injected "What you know
  about this user" section is bounded (~500 tok) and recall still works
  (CAT3/CAT5). The cap is deterministic (unit-verified); this confirms the live
  injected size.
- **Next P0 options:** Step 2b (fold the CHAT branch into the baseline+tail
  split — smaller), or Step 4 (tool-result index + search, the Context Mode
  hybrid). Step 5 = Context Budget Manager (the structural composer).
- **Coordination:** Step 3 scope (memory.py, agent_runtime.py) was disjoint
  from Step 2b (prompts.py/build_agent_system_prompt) — safe to run in parallel.
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash / qwen3.8-flash
  (`--adapter bankofai --model X`); deepseek-v4-flash paid; gemini-2.5-flash
  works but one turn eats the per-minute quota; zai 401; chutes/cerebras $0.
- **Tooling:** commit messages via `git commit -F <file>` (heredoc subst breaks
  through the terminal wrapper); macOS box (no `timeout` CLI).
- **Standing:** ~36 pre-existing Windows backend failures + ~32 ruff baseline
  need the deferred peer pass; ADR-57 slice 3 (concurrent Thinker) queued.

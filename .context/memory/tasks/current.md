# Current Task

**Status:** IDLE — Session 420 closed. Fixed the "find my CV" transcript
failure family (commits `33a81f2`, `e8cd69a`, `e32c92e`): (1) honest limit
classification — `AgentTrace.limit_kind` (iteration_cap/wall_clock/
repetition/hard_ceiling) drives `classify_failure` (wall_clock_limit /
repetition_loop) and the Session 32 fallback wording, ending the
"everything is iteration_limit" misdiagnosis; (2) `agent_loop_failure` no
longer fires when the forced synthesis delivered a real answer (banner no
longer lies above a complete answer; `_force_final_answer` sets
`final_response` on real-model text only); (3) `identical_call_streak`
hard-stops same-tool+same-args loops at 3 (the user's "limit a failing
tool running the same command over and over" — done, in addition to the
existing cap-failure-never-success extension rules); (4) system_search
relaxed fallback quality gate (path→basename, generic-token stoplist,
2-char distinctive token allowed). 15+2 new tests; full-suite failure set
identical to baseline; live-verified on bankofai/qwen3.8-flash isolated
8765 (CV answer + zero failure events; search gate on the exact
transcript queries). Contract addendum in AGENTS.md item 2.

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
  through the terminal wrapper); macOS box (no `timeout` CLI). On Windows:
  heredocs also eat backslashes — write path-holding code with the Write tool.
- **Standing:** ~56 pre-existing backend failures (incl. 60 multipart
  collection errors from missing python-multipart in this venv) + ruff
  baseline need the deferred peer pass; ADR-57 slice 3 queued.

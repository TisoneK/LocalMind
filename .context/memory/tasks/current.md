# Current Task

**Status:** IDLE — Session 350 shipped the memory end-to-end fix (B-2026-08-23-1 done; four gaps: fallback timestamp, classifier content/type pass-through, candidate-extraction wiring, recall operation).

## Session 350 outcome — memory op works end to end (store → gather → summarize → recall)

- The user's backlog ask: make memory op work end to end — recognize store requests, gather correct info from chat evidence/system talk, save summarized memory.
- **Four gaps found by pipeline map + simulation (not guesswork), three live-confirmed:**
  1. **Gap A (breaker):** `memory_op`'s SQLite fallback omitted `timestamp` → `warm_start_facts` computed age=now−0 → every fallback-stored fact looked >30d old → **agent stored facts it could never see again**.
  2. **Gap B:** deterministic write passed the raw message; `memory_op` re-extracted with a corrupting regex ("note down my project" → stored "down my project") and always tagged `semantic`.
  3. **Gap C:** `extract_memory_candidates`/`should_store_candidate` (corrections, source knowledge from tool outcomes) were dead code.
  4. **Gap D (live-found):** `memory_op` had NO recall operation — "recall X" fell through to STORE (persisted junk "recall"); models send `{operation, query}` while schema says `content`, so text_tools dropped the query.
- **FIXES (all model-agnostic):** `memory_tool.py` fallback writes `timestamp`; `agent_runtime` passes classifier content+memory_type to `memory_op` (which gained optional params); `_memory_mixin` Path 4 runs `extract_memory_candidates` with obs-history tool results before Path 2's early returns; `memory_tool` gained a keyword recall (`_RECALL_PAT`, prefix matching, recent-facts fallback for bare/no-match) and `text_tools._extract_tool_input` accepts `query` as a `content` alias.
- **LIVE (bankofai, isolated 8765, scratch tracehome + real settings):** T1 "remember that I prefer concise answers" → deterministic, 0 LLM calls, `memory_type=user_preference, importance=0.8, timestamp` in DB. T2 NEW session (no history): "Based on what you remember about me, how should I write my emails?" → agent answered from stored memory ("you prefer concise answers … Short. Direct. No fluff."). Junk-"recall" corruption fixed and re-verified (exactly 1 fact row).
- **Tests:** 12 new in `tests/core/test_memory_e2e.py`; full backend **2321 passed / 2 skipped / 0 failures**; ruff zero new violations.

## Next

- **B-2026-08-23-2 (High):** The agent isn't fully aware of its complete environment — it looked for todos "in chat" and didn't mark tasks complete when asked. Investigate environment/todo awareness.
- Remaining 2026-08-23 items: B-3 (exported chat completeness), B-4 (shell-active awareness + settings UI guide), B-5 (tab auto-switch), B-6 (file rendering docx/pdf/excel), B-7 (filetask summary info), B-8 (goal-driven fastest/safest path + subgoals), B-9 (action pill tooltips), B-10 (concrete planning), B-11 (todo title/content split), B-12 (clickable filenames).

**Feature:** none (single-session memory end-to-end fix)
**ADR:** none (bug-fix session; no architectural decision)
**Review:** n/a (live + unit verified per memory contract)

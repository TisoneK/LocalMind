# Current Task

**Status:** IDLE — Session 382 closed **B-2026-08-23-8** (goal-driven agent, part 1): deterministic goal tree with ordered sub-goals.

## Session 382 outcome

- **Goal tree (`9a8a421`):** `derive_goal_tree()` now extends the Session 330 fixed checklist — every derived goal (file/folder deliverable) carries ordered sub-goals phrased fastest+safest (check → prep parent folder → write → verify), each feeding the next. Derived ONCE with the flat items = same immutable denominator; no mutable state, no new tools, Parent-only (ADR-53).
- **Threaded end-to-end:** `agent_runtime` derives the tree as plain dicts → `BaseAgent.run` → `AgentLoop.run` (`goal_tree=`), seeded as `plan-{i}-sub-{j}` todos right after their parent, rendered nested (indented, connector, no checkbox) in the Todos panel — NEVER counted in the n/n denominator, completed together with the parent (narration-advance AND end-of-loop), finalized with the parent at turn end. Injected into the model context as an ordered `# Goal route (follow in order; each step feeds the next)` so the agent takes the fastest+safest path instead of guessing.
- **Frontend:** `TodoList` groups sub-rows (`/^plan-\d+-sub-\d+$/`) under their parent with a `↳`/`✓` marker; denominator stays parent-only.
- **Scoped out (orthogonal):** the "efficient planner" half (no redundant recon) — that's B-2026-08-23-10 (concrete planning) territory.
- **Verification:** backend 2498 passed / 2 skipped (incl. 8 new tests: 5 derive-tree + 3 loop-level incl. prompt-injection assert); frontend 348 passed (2 new TodoList nested-render tests); ruff/tsc/eslint clean (2 loop.py E501s pre-existing at HEAD).
- **Next:** continue the backlog one item at a time. Top candidates: **B-2026-08-23-33** (op permissions), **-34** (chat modes), **-35** (never-rude declines), **-37** (write-stats table), or quick UI wins (-21 time formatting, -22 token short-form, -26 ⋮ panel overflow). Pre-existing untracked trace residue at `backend/Dev/` + `backend/scratch/` left untouched.
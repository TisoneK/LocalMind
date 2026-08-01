# Feature: adr-8-agent-centric-routing

Goal: implement ADR-8 — switch LocalMind's agent-mode routing from
**tool-centric** (intent classifier picks a TOOL, then `select_agent`
finds the agent whose toolset has it) to **agent-centric** (task-type
classifier picks an AGENT, the agent owns its tools, the agent's
workflow governs HOW it uses them, agents collaborate via delegation).
ADR-8 was proposed in Session 33 and switches to **standing Target**
in Session 34. **ADR-8 builds on ADR-5** (closed-loop shape stays —
5-step loop + workspace feedback bar — agents just get richer context
and delegation ability) and **ADR-6/ADR-7** (BaseAgent subclasses
become real agents with workflows, not hollow shells; the `.context/`
protocol + playbook files become load-bearing).

Five principles (full ADR text in `.context/memory/plans/decisions.md`
ADR-8):

1. **Classification by task type, not tool.** "Create hello world repo"
   is a *coding* task → CodingAgent — not a SHELL intent → CodingAgent.
2. **Agents own tools; tools don't own agents.** The intent router no
   longer picks a tool and then finds the agent that has it.
3. **Agents collaborate.** A coding task needing research delegates to
   the ResearchAgent — parallel or handoff — instead of being
   re-classified (losing context).
4. **The workflow is the value.** `coding.md`, `research.md`,
   `safety.md`, etc. — loaded into the agent's system prompt and
   govern tool use, not just scoped toolsets.
5. **Agents are directories, not modules.** Each agent is a
   self-contained package under `backend/src/agents/<name>/`:
   `agent.py` + `playbook.md` + `context_builder.py` + `tools.py` +
   `is_done.py` + `persona.md` + `tests/`. Co-location >
   scattered-class-and-data. Auto-discovering registry (scan `agents/`
   for directories with `agent.py`).

Four implementation phases (multi-session):

- **Phase 1 — Agents as directories** (structural foundation). Pure
  refactor, no behavior change. Move each agent CLASS from its
  standalone module into its existing directory: `coding_agent.py` →
  `agents/coding/agent.py`, `research_agent.py` →
  `agents/research/agent.py`, `browser_agent.py` →
  `agents/browser/agent.py`, `direct_agent.py` →
  `agents/direct/agent.py`. Move playbook files from
  `backend/data/workflows/<name>.md` → `agents/<name>/playbook.md`.
  Move inline personas from `prompts.py:_PERSONA_MAP` →
  `agents/<name>/persona.md`. `__init__.py` re-exports from `agent.py`
  for backward compatibility. The registry auto-discovers directories
  with `agent.py`. **No real-model test needed** for Phase 1 alone —
  pure structural move, behavior-preserving (the existing pytest suite
  is the safety net).

- **Phase 2 — Wire `build_context()` into `BaseAgent.run()`**
  (highest-leverage piece). The playbook files finally reach the
  model. `BaseAgent.run()` calls `self.build_context()` before
  delegating to `AgentLoop.run()`; the result is passed through to
  `build_agent_system_prompt()` and injected as a system-prompt
  section. `build_coding_context()` actually loads `playbook.md`
  (currently returns a static header — `agents/coding/context_builder.py:55-84`).
  Also: `AgentLoop.run()` respects `agent_config.max_iterations` and
  `agent_config.max_wall_clock_secs` when provided (currently dead
  code — module-level `MAX_ITERATIONS=8` / `MAX_WALL_CLOCK_SECS=180`
  is used instead). **Real-model smoke test mandatory** before
  shipping (per Session 31/33 flaw log — third iteration of the
  lesson).

- **Phase 3 — Agent-initiated delegation.** Replace the
  `should_use_sub_agents()` keyword heuristic with agent-initiated
  delegation. The CodingAgent's workflow + system prompt includes the
  ability to say "I need research on X" → the framework spawns a
  ResearchAgent sub-task → results flow back → CodingAgent continues.
  Parallel or handoff — UX decision (sub-panel for parallel? handoff
  is silent unless it fails). Real-model test mandatory.

- **Phase 4 — Task-type classifier.** Replace (or augment) the intent
  classifier with a task-type classifier. "Create hello world repo" →
  `task_type=coding` (not `intent=SHELL`). Task type selects the
  agent; the agent's workflow governs tool use. Intent classification
  can still exist as a SIGNAL the agent uses, but it's no longer the
  routing key. Probably LLM-based but cached per-session. Real-model
  test mandatory.

- **Started:** 2026-07-27 (Session 34 — initialization only, no code)
- **Branch:** main (LocalMind pushes to main directly per
  `workflows/active.md` — no feature-branch flow; this feature commits
  alongside other work but every commit touching agent-mode is prefixed
  to make the trail greppable: `refactor(agents):` for Phase 1
  structural moves, `feat(agent-loop):` for Phase 2 wiring, etc.)
- **Status:** completed for the ADR-8 phases; autonomy and additive capability
  runtime work are shipping in narrow slices, with transitional wiring
  follow-ups remaining open.
- **Current state:** Phases 1–4 are implemented. Session 51 added the first
  autonomy slice: persisted objectives, a background ObjectiveRuntime,
  pause/resume/cancel lifecycle controls, ownership/lease fencing, explicit
  read-only tool policy propagation, Engine serialization, objective API
  routes, frontend objective controls, and the first read-only capability
  discovery surface (`GET /api/capabilities` plus an Observe catalog section).
  The capability projection is descriptive only and does not alter routing,
  tools, agent selection, SSE, or runtime observation behavior. BrowserAgent
  inspection, chat transport/UI repairs, and workspace feedback remain intact.
  Deferred work includes keyed Engine locks, direct fast-path policy tests, the
  public `streamChat()` integration regression, remaining transitional
  AgentLoop wiring, optional SubAgentType consolidation, a live `agent-browser`
  smoke test, and separate contracts for actionable non-coding capabilities.
  Session 59 added a deterministic worker-to-report boundary: tool traces
  now produce evidence-first `WorkReport` output when model synthesis is empty
  or too weak, including forced-synthesis error paths and late XML-intercepted
  tools. Stream completion markers are held until the report is delivered.
  Session 60 added the next delegation boundary: immutable instruction packets,
  isolated child run IDs with parent correlation, bounded structured results,
  explicit child-tool restrictions, untrusted evidence delimiters, and
  structured failure metadata for construction/configuration, timeout, child
  exception, and empty-response paths. Legacy `{target_agent, task}` calls
  remain compatible. Delegation is still synchronous handoff in this slice;
  parallel child execution and frontend child-run panels remain deferred.
  Session 61 renamed the six runtime agent instruction files from
  `workflow.md` to `playbook.md`, updated all playbook loaders and prompt/test
  terminology, and preserved the generic Plan→Execute→Verify workflow plus
  universal `backend/data/workflows/safety.md` policy. The product commit is
  `044e140`; validation and review are recorded in
  `.context/memory/reviews/2026-07-31-review-18.md`.


- **No-regression list (must hold after every phase):**
  1. Session 31/32 fix: `MAX_ITERATIONS=8` default, configurable via
     `LOCALMIND_MAX_ITERATIONS` env var; `MAX_WALL_CLOCK_SECS=180s`,
     configurable via `LOCALMIND_MAX_WALL_CLOCK_SECS`. Fallback says
     "iteration limit reached" when `trace.hit_limit` is True.
     Regression tests: `tests/e2e/test_iteration_limit_and_safety.py`.
  2. Session 32 fix: `backend/data/workflows/safety.md` "check before
     acting" universal constraint injected via `build_agent_system_prompt()`
     for ALL agent intents.
  3. Session 31 adapter fix: `chat_with_tools` appends a synthetic
     `user` message when the last is `tool` role (DeepSeek-v4-flash-free
     + similar providers reject tool-terminated messages with HTTP 400).
     Phase 1 detection waits for actual `content` (not just reasoning),
     hard cap 500 chunks. Regression tests:
     `tests/adapters/test_zen_deepseek_fixes.py`.
  4. Session 33 fix: engine fallback uses `_obs.all()` (read-only),
     NOT `_obs.drain()` (destructive — steals SSE events from the
     `chat.py:129` bridge). Regression tests:
     `tests/e2e/test_obs_drain_bug.py`.
  5. ADR-9 ZenMux config-only integration: `ProviderConfig` for
     `zenmux` in `openai_compat.py` (base_url
     `https://zenmux.ai/api/v1`, default model `x-ai/grok-4.5`, env
     var `ZENMUX_API_KEY`). Marked IMPLEMENTED BUT UNTESTED — smoke
     test blocked on free plan. Not Phase-1-relevant, but don't
     remove the ProviderConfig during the agents reorg.
  6. Baseline: 412 tests pass (Session 33 baseline held through the
     `drain()` fix; ADR-9 added 0 new tests). After each phase,
     `pytest` must show >= 412 passing.
- **Success criteria (Phase 1 = structural refactor, no behavior change):**
  1. `ls backend/src/agents/` shows four directories: `coding/`,
     `research/`, `browser/`, `direct/` — each with `agent.py` (the
     class) + `playbook.md` + `persona.md` + `context_builder.py` +
     `is_done.py` + `tools.py` + `__init__.py` + `tests/`.
  2. `coding_agent.py`, `research_agent.py`, `browser_agent.py`,
     `direct_agent.py` no longer exist as standalone modules — their
     classes live inside their directories.
  3. `backend/data/workflows/` directory is empty (or removed); the
     workflow `.md` files live inside their agent directories.
  4. `prompts.py:_PERSONA_MAP` is gone (or empty); personas live at
     `agents/<name>/persona.md`.
  5. The registry auto-discovers agents (no manual registration in
     `agents/__init__.py` beyond a directory scan). Adding a new
     agent = adding a new directory under `agents/` with an
     `agent.py` file.
  6. All existing tests pass (>= 412). No new tests strictly required
     for Phase 1, but a `tests/agents/test_directory_layout.py`
     sanity test is recommended — verifies each agent directory has
     the expected files.
  7. `ruff check .` shows no new serious bugs beyond the existing
     E501 noise (111 lines >120 chars — pre-existing, not blocking).
- **Next steps:** Next implementation session should start Phase 1.
  Read this `manifest.md` + `notes.md` first. The existing partial
  directory structure (`agents/coding/{context_builder,is_done,tools,__init__}.py`
  already exists) means Phase 1 is mostly "drop the class into the
  directory it should already own" — should be quick. **Do NOT attempt
  Phase 2 in the same session as Phase 1** — Phase 1 is structural
  and ship-able on its own; Phase 2 changes the model's prompt and
  needs real-model testing. Per Session 31/33 flaw log: ship Phase 1,
  verify with the existing pytest suite, then in a SEPARATE session
  start Phase 2 with a real-model smoke test planned.
- **Open questions (deferred to ADR-8 text or future sessions):**
  1. Does the task-type classifier (Phase 4) need an LLM call, or can
     it be keyword-based? LLM adds latency; keyword is less accurate.
     Probably LLM-based but cached per-session.
  2. How does agent-to-agent delegation handle streaming? (Phase 3)
     If the CodingAgent delegates to the ResearchAgent mid-stream,
     does the user see the ResearchAgent's work? Probably yes (in a
     sub-panel), but this is a UX decision.
  3. What happens to the intent classifier? (Phase 4) It becomes a
     signal the agent uses ("user mentioned shell commands, so shell
     is likely involved") rather than the router. Or it could be
     removed entirely if the task-type classifier is good enough. TBD.

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
  tools, agent selection, SSE, or runtime observation behavior.  BrowserAgent inspection, chat transport/UI repairs, and workspace feedback remain intact.
  Session 62 corrected the Zen free-model default to `deepseek-v4-flash-free`
  and contained CenterPanel transcript scrolling so streaming cannot displace
  the workspace header/composer. Session 63 added the live Observe metrics
  bridge: streaming latency follows the request clock, prompt-token telemetry
  is used for Context Tokens when available, and completion tokens are never
  mislabeled as context.  Session 64 completed the backend prompt-token telemetry
  path: provider usage is normalized and preserved through adapters, AgentLoop, Engine, tool calls, terminal frames, and fallback/error paths. Session 66 completed the first Tier A Codebuff borrowing slice: bounded head+tail output for shell and code execution, with incremental stream capture and trailing-error preservation. These are additive runtime/UI repairs and do not alter agent routing or delegation contracts.
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

## Session 195 — Phase 4 track 2: weather signal + bare <tool_call> leak defense (shipped)

- **What:** live transcript bug — "Whats the weather like in Kitengela now?" misrouted
  to CHAT (LLM classifier confidence 0.30) and the model's
  `<tool_call>web_search<arg_key>…</arg_key><arg_value>…</arg_value></tool_call>` markup
  streamed raw into the bubble. Root fix: deterministic weather→WEB_SEARCH signal
  (zero LLM, realtime_sensitive; noun-or-question guard so "It's hot in here" never
  fires). Defense fix: the bare <tool_call>/arg_key/arg_value format added to the
  Session 127 interception (parse/detect/strip) and the DIRECT path now buffers RAW
  text so detection can't be hidden by the strip — misrouted requests escalate to the
  agent loop and the search actually RUNS instead of leaking.
- **Files:** `thinking_dispatcher.py` (weather signal), `agent/text_tools.py`
  (`_TOOL_CALL_RE`/`_ARG_KEY_VALUE_RE` format 3), `core/filters.py`
  (`_TOOL_CALL_TAG_PATTERN`/`_TOOL_CALL_PARTIAL`), `engine/_pipeline.py` (raw-buffer
  detection).
- **Tests:** 19 new; backend **1747 green**. Backlog: deterministic engine web_search
  fast-path for weather (Session 193 file-ops pattern); wire the ambiguous file-ask
  reply through the deterministic chain.

## Session 194 — Phase 4 track 2: find_path catalog contract (glob/grep-style, shipped)

- **What:** the user's design push — "why can't find_path work like Glob or Grep:
  find ALL files and paths once, then the agent filters or asks clarification?"
  find_path evolved from a one-shot capped lookup into a CATALOG enumeration:
  walk once (2.5s time budget, not a result cap), cache the walk (bounded TTL),
  and serve every follow-up — "show more", "only pdf", "in Documents" — as
  instant in-memory filtering/pagination. Output is a catalog (total + folder/
  type breakdown + small page) so context stays bounded while NOTHING is
  silently hidden. The deterministic file-ops picker now chooses from the FULL
  catalog (all_paths), and the ambiguous ask shows a ranked shortlist.
- **Files:** `tools/find_path.py` (walker/cache/filters/pagination/catalog),
  `core/file_ops.py` (spec filters, catalog fields, format_top_candidates,
  shared _score_match), `thinking_dispatcher.py` (continuation signal args),
  `engine/_pipeline.py` (spec pass-through, ranked ambiguous ask).
- **Tests:** 22 new; backend **1728 green**. Backlog: route the ambiguous-ask
  reply ("open CV-Tisone.docx") through the deterministic chain, not the
  agent-loop follow-up path.

## Session 193 — Phase 4 track 2: deterministic file-ops execution layer (shipped)

- **What:** file operations became RUNTIME behavior, not model choices, for
  the 80% file-handling use case. The engine intercepts `file_ops`-domain
  signal plans (Session 191's file-search + new direct-read branch) and
  executes find → pick → read as code; the model gets ONE final-synthesis
  call, and when the model is down/empty the deterministic evidence is
  yielded (never blank, never raw provider JSON). This closes the transcript
  failure: find_path found CV-Tisone in 1.9s but the model never read it.
- **Files:** new `core/file_ops.py` (executor + picker); `tools/find_path.py`
  (metadata["paths"]); `core/thinking_dispatcher.py` (file_ops domain +
  direct-read branch); `core/engine/_pipeline.py` (2c fast-path).
- **Tests:** `tests/core/test_file_ops.py` (17) + 8 signal tests. Full
  backend **1706 green**, frontend 137 green, tsc clean.
- **Ties to Phase 4 (task-type classifier):** the `primary_domain` field IS
  the task-type signal — `file_ops` is the first domain the engine routes
  on deterministically (task type → execution path, no LLM). The same
  pattern (domain → deterministic runtime behavior) is the blueprint for
  other high-frequency task types.
- **Flaw-log compliance:** no agent-loop change — the deterministic path
  bypasses the loop rather than modifying it, so no real-model test gate
  applies (the executor tests exercise real find_path/file_reader).

## Session 196 — Freebuff / Codebuff orchestration review (completed)

- **Scope:** research and architecture review only; no product behavior changes.
- **Result:** official Codebuff definitions/docs verify scoped agent contracts,
  child allowlists, isolated-by-default history, output modes/schemas,
  generator controls, narrow specialist tools, and structured parent results.
  Freebuff's README verifies specialized agents and isolated Desktop workspaces.
- **Corrections:** hosted `/api/v1/agent-runs`, `codebuff_metadata`,
  `ancestorRunIds`, Google A2A endpoints, universal reviewer enforcement, and
  an exact public Basher prompt/schema remain unverified and are not LocalMind
  requirements.
- **Durable findings:** H1 legacy `should_use_sub_agents()` branch, H2 shared
  workspace in parallel delegation, and M1 unbounded parent-facing child prose
  were added to the review and backlog as B-2026-08-14-1..3.
- **Validation:** `sh scripts/ci-check.sh` passed before the review: 1747 backend
  tests, Ruff clean, frontend TypeScript clean, ESLint 0 errors / 64 existing
  warnings.
- **Report:** `.context/memory/reviews/2026-08-14-review.md`.

## Session 197 — Web-search reasoning contract fix (completed)

- **Scope:** narrow backend bug fix; no routing or orchestration redesign.
- **Root cause:** the primary AgentLoop web-search path passed
  `reasoning=_step_reasoning()` to `_handle_web_search_result()`, but the
  handler signature did not accept that keyword, so the search result crashed
  before synthesis.
- **Fix:** added the optional `reasoning` parameter to the handler boundary;
  existing raw `thought` trace behavior remains unchanged.
- **Validation:** focused regression passed; full `sh scripts/ci-check.sh`
  passed with **1748 backend tests**, Ruff clean, frontend TypeScript clean,
  and ESLint 0 errors / 64 existing warnings.
- **Report:** `.context/memory/reviews/2026-08-14-review-2.md`.

## Session 198 — Current-weather freshness guard (completed)

- **Scope:** deterministic freshness enforcement at the web-search extraction and synthesis boundary.
- **Finding:** a same-day August 14 search result and an older August 8 result reached synthesis together; the model selected the stale evidence. The machine clock and Git state were current.
- **Fix:** time-sensitive queries now parse explicit dates in numbered result blocks, filter non-current dated blocks when a same-day block exists, and return an honest gap report when dated evidence is stale-only. Undated and non-time-sensitive research remains unchanged.
- **Tests:** `tests/core/test_synthesizer_freshness.py` — 4 focused tests; full backend **1752 green**, Ruff/tsc clean, ESLint 0 errors / 64 existing warnings.
- **Report:** `.context/memory/reviews/2026-08-14-review-3.md`.

## Session 199 — Delegated output interception (shipped)

- **What:** preserved the parent-agent interception contract for delegation.
  Child progress remains observable, but raw child tool output is no longer
  forwarded into the user-facing Actions/SSE payload. The parent still receives
  the complete delegated result internally and synthesizes the final answer.
- **Files:** `core/obs.py` strips child output from forwarded `tool_call`
  metadata; `api/routes/chat.py` applies a second SSE presentation filter;
  delegation/API regression tests cover both boundaries.
- **Validation:** focused delegation/API tests 47 passed; full backend **1759
  green**, Ruff/tsc clean, ESLint 0 errors / 64 existing warnings.
- **Report:** `.context/memory/reviews/2026-08-14-review-4.md`.

## Session 200 — Legacy delegation path removed (shipped)

- **What:** removed the pre-loop `should_use_sub_agents()` heuristic,
  decomposition, and direct-chat sub-agent framework. The selected parent
  AgentLoop is now the sole delegation entry point; cross-domain work uses its
  scoped `delegate` / `delegate_parallel` / `delegate_inline` tools.
- **Files:** `_pipeline.py` no longer imports or invokes the heuristic;
  `core/agent/sub_agent.py` was deleted; stale docs and legacy tests were
  replaced with parent-routing regressions.
- **Validation:** focused delegation/routing tests 110 passed; full backend
  **1753 green**, Ruff/tsc clean, ESLint 0 errors / 64 existing warnings.
- **Report:** `.context/memory/reviews/2026-08-14-review-5.md`.

## Session 201 — Parent-agent runtime replaces request pipeline (completed)

- **Scope:** remove the request-time `_pipeline.py` execution architecture,
  not map around it.
- **Implementation:** deleted `_pipeline.py`; added LocalMind's own
  `ParentAgent` and `AgentRuntime`; made `Engine` an import-compatible alias
  for the runtime; retained lifecycle services while moving tool choice,
  delegation, evaluation, replanning, and synthesis into the parent loop.
- **Contract:** every non-blocked request enters one parent AgentLoop. Specialized
  agents are reached only through parent-owned scoped delegation tools. Dispatcher,
  execution-graph, and workspace-orchestrator modules have no production
  request-path callers.
- **Validation:** full CI **1742 passed, 2 skipped**, Ruff/tsc clean, ESLint 0
  errors / 64 existing warnings. No local provider credential was available
  for a new real-model smoke; this is recorded in review-6.
- **Report:** `.context/memory/reviews/2026-08-14-review-6.md`.

## Session 202 — Full frontend Agent workspace (completed)

- **What:** exposed the LocalMind parent/child run tree in the existing
  workspace without changing backend SSE transport.
- **Implementation:** `useChat` now projects delegation lifecycle and tagged
  child tool events into live `AgentRun` state; `AgentWorkspace` renders the
  expandable nested tree; `RightPanel` adds the `Agents` tab and
  `WorkspaceLayout` wires the state through.
- **Validation:** frontend **142 tests passed**, TypeScript/build passed,
  ESLint 0 errors / 64 existing warnings.
- **Report:** `.context/memory/reviews/2026-08-14-review-7.md`.
- **Deferred:** historical run-tree replay and per-child retry/resume controls.

## Session 203 — Lighter dark UI theme (completed)

- **What:** increased readability of the existing dark green workspace without
  introducing a light-mode toggle.
- **Implementation:** raised shared generic and LocalMind brand surface,
  border, secondary-text, and status-color variables in `frontend/src/globals.css`;
  added the public Unreleased changelog entry.
- **Validation:** frontend **141 tests passed**, TypeScript/build passed,
  ESLint 0 errors / 64 existing warnings.
- **Report:** `.context/memory/reviews/2026-08-14-review-8.md`.

## Session 204 — Authoritative current time/date handling (completed)

- **What:** corrected the parent-agent clock-query failure where a free-tier
  model emitted rejected `shell(Get-Date)` before using sysinfo, then corrupted
  the verified date during final synthesis.
- **Implementation:** the parent contract now requires sysinfo exclusively for
  current time/date/day questions; the AgentLoop corrects accidental shell clock
  calls to sysinfo and returns the exact verified sysinfo line without a second
  paraphrase call. Added focused regression coverage and environment guidance.
- **Validation:** full CI passed with **1748 backend tests, 2 skipped**, Ruff/tsc
  clean, and ESLint 0 errors / 64 existing warnings.
- **Product commit:** `ef03365`.
- **Report:** `.context/memory/reviews/2026-08-14-review-9.md`.
- **Limitation:** no new live-provider smoke was run; no local provider
  credentials were available/used.

## Session 205 — Live parent-agent interaction during slow tools (completed)

- **What:** kept the user-facing chat active while the parent agent waited on a
  slow model or tool instead of hiding all progress until the next engine chunk.
- **Implementation:** shielded SSE wait timeouts, selective observation draining,
  heartbeat-flushed parent tool/terminal events, bounded parent results, and
  preserved delegated child-output privacy. No frontend transport change was
  needed because the existing UI already renders these event types.
- **Validation:** backend **1751 passed, 2 skipped**; frontend **141 passed**;
  TypeScript/build/Ruff clean; ESLint 0 errors / 64 existing warnings.
- **Product commit:** `6538296`.
- **Report:** `.context/memory/reviews/2026-08-14-review-10.md`.
- **Limitation:** no live-provider smoke was run; local provider credentials
  were unavailable.

## Session 206 — Greeting fast path restored (completed)

- **What:** stopped greetings and simple conversational inputs from entering
  the parent tool loop and spending 30+ seconds in silent reasoning.
- **Implementation:** restored the existing deterministic/direct helpers at the
  `AgentRuntime` boundary; `Hi` makes zero provider/tool calls, while
  conversational questions use direct chat without tool planning. Substantive
  work remains on the single parent-agent path.
- **Validation:** backend **1752 passed, 2 skipped**; frontend **141 passed**;
  TypeScript/build/Ruff clean; ESLint 0 errors / 64 existing warnings.
- **Product commit:** `8aefc51`.
- **Report:** `.context/memory/reviews/2026-08-14-review-11.md`.
- **Limitation:** no live-provider smoke; local provider credentials were
  unavailable.

## Session 207 — User-visible parent workflow progress (completed)

- **What:** made substantive parent-agent turns visibly acknowledge, plan, act,
  and verify instead of exposing raw planner/reasoning text or appearing silent.
- **Implementation:** `AgentRuntime` emits an immediate acknowledgement;
  `AgentLoop` emits concise planning, next-action, and verification statuses;
  raw provider planning/reasoning remains internal to `TaskState` and evidence.
  Native tool/delegation/acceptance behavior is unchanged.
- **Validation:** backend **1754 passed, 2 skipped**; frontend **141 passed**;
  TypeScript/build passed; changed-file Ruff clean; ESLint 0 errors / 64 existing
  warnings. Repository-wide Ruff retains unrelated pre-existing test findings.
- **Product commit:** `0f65c22`.
- **Report:** `.context/memory/reviews/2026-08-14-review-12.md`.
- **Notes:** `.context/memory/sessions/2026-08-14-207/notes.md`.
- **Limitation:** no live-provider smoke; local provider credentials were
  unavailable.

## Session 208 — Immediate SSE acknowledgement (completed)

- **What:** separated transport acknowledgement latency from provider/model
  generation latency after the user reported 9–15 seconds of apparent silence.
- **Implementation:** `_event_stream()` now emits a first-class `status_update`
  before title persistence, memory retrieval, adapter setup, or model generation.
  Parent-agent routing, direct greeting behavior, SSE keepalives, persistence, and
  delegated-output privacy remain unchanged.
- **Validation:** backend **1755 passed, 2 skipped**; frontend **141 passed**;
  TypeScript/build passed; changed-file Ruff passed; ESLint **0 errors / 64
  existing warnings**.
- **Product commit:** `06943b6`.
- **Report:** `.context/memory/reviews/2026-08-14-review-13.md`.
- **Notes:** `.context/memory/sessions/2026-08-14-208/notes.md`.
- **Limitation:** no live-provider smoke; final answer latency remains dependent
  on the selected provider/model.

## Session 209 — Parent-owned tool observation workflow (completed)

- **What:** restored the missing parent-agent continuation boundary. Successful
  web searches no longer become terminal chat answers before the parent can
  inspect, follow up, verify, replan, or synthesize.
- **Implementation:** removed the web-search terminal shortcuts from native,
  MiniMax/text-encoded, and late-intercepted AgentLoop branches. Search output
  now returns as a normal `tool` observation and the parent makes the next
  decision. The existing SSE/UI event surface already renders todos, actions,
  terminal output, statuses, and final tokens, so no frontend change was needed.
- **Validation:** backend **1756 passed, 2 skipped**; frontend **141 passed**;
  TypeScript/build passed; changed-file Ruff passed; ESLint 0 errors / 64
  existing warnings.
- **Product commit:** `5c2cfbd`.
- **Report:** `.context/memory/reviews/2026-08-14-review-14.md`.
- **Notes:** `.context/memory/sessions/2026-08-14-209/notes.md`.
- **Limitation:** no live-provider smoke; local provider credentials were
  unavailable.

# Notes: agent-loop-closed-loop (append-only while the feature is alive)

Feature-scoped findings, attempts, dead ends — the detail that would
otherwise bloat the global logs. Facts that outlive the feature go to
their real domain: architectural decisions → `plans/decisions.md`,
user preferences → `user/preferences.md`, environment facts →
`system/environments.md`, protocol friction → `flaws/log.md`.

<!-- TEMPLATE — copy below the last entry:
---
## YYYY-MM-DD — <agent> / <model> (Session N)
<findings, attempts, dead ends — detail that would otherwise bloat the
global logs. Facts that outlive the feature go to their real domain.>
-->

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 13)

Feature directory created. No implementation attempted this session —
this was the scaffolding session (Session 13 = core-0.3.0 preview
adoption + first feature directory seeded). The architectural target
itself was captured in the prior session (Session 12, ADR-5).

Two design refinements surfaced while writing the manifest:

1. **Branch policy vs feature-scoped memory.** The 0.3.0 design's
   concurrency story assumes feature branches (`memory/features/<slug>/`
   travels with the code and merges with it — separate directories per
   feature make concurrent branches naturally conflict-free in memory).
   LocalMind pushes to `main` directly per `workflows/active.md`, so
   the "branches naturally conflict-free" benefit doesn't apply here.
   That's fine — the value for LocalMind is the *archival* story (the
   ledger + the ability to move a feature directory to `archive/` once
   merged, instead of leaving its breadcrumbs forever in
   `tasks/backlog.md` and `agents/sessions.md`), not branch isolation.
   Worth noting in `plans/decisions.md` if ADR-5 ever gets a follow-up
   ADR about branching.

2. **`workspace_state.py` vs `workspace/manager.py` naming collision
   risk.** The existing `backend/src/core/workspace/manager.py` is the
   per-turn scratch directory (TODO.md / CONTEXT.md / inbox / outbox —
   tool I/O isolation within one turn). The new service proposed in
   ADR-5 is `backend/src/core/workspace_state.py` (persistent project
   state across turns — git/diff/test output fed back into context).
   They are siblings, not replacements, but the names are close enough
   that an agent skimming the codebase could conflate them. ADR-5
   already calls this out explicitly ("Do NOT conflate"), and the
   manifest repeats it. If the naming proves confusing in
   implementation, candidates for the new module: `workspace_state.py`
   (current), `project_state.py`, `turn_feedback.py`, `loop_observability.py`.
   Defer the rename decision until implementation reveals actual usage.

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 14)

User provided more architectural context for the same ADR, working
through three options for how `backend/` should be organized. Captured
as ADR-6 (refines ADR-5 — specifies the organizational structure ADR-5
left open).

**The three options explored:**

1. **Multi-harness framework** — `harness/coding/`, `harness/research/`,
   `harness/direct/`, each implementing the same loop shape with
   different context/tools/termination. base.py supplies the abstract
   loop; each harness supplies `build_context()`, `tools`, `observe()`,
   `is_done()`. User rejected the framing: "More like an agent" —
   harnesses are workflow pickers, agents are addressable things.

2. **Single unified agent** — one `agent.py` loop, all tools available
   flat, the model dynamically picks tools per task. Closer to Claude
   Code. User identified the core risk: tool descriptions have to be
   good enough that a gemma3:1b-class model reliably picks the right
   one. With a flat tool surface and a 1B model, wrong-tool selection
   is the likely failure mode.

3. **Multiple distinct agents with shared base** — `agents/base_agent.py`
   + `coding_agent.py` + `research_agent.py` + `browser_agent.py` +
   `direct_agent.py`. Each is a thin subclass supplying its own
   `context_builder`, scoped `tools`, `is_done()`. Shared in base: 5-step
   loop, compaction, streaming, permission checking. User converged
   here: "Like coding agent, research agent, browser agent." Key
   argument: scoped toolset per agent = fewer tools for the small model
   to choose from = more reliable selection. Explicit user selection
   (UI picker) avoids an expensive LLM-based router.

**Decision: option 3.** Captured as ADR-6 with Status: accepted. The
decision rests on three pillars: (a) scoped tools per agent for small-
model reliability, (b) explicit user selection over LLM-based router
(cheaper on gemma3:1b-class hardware, no wasted turns from wrong
classification), (c) shared base_agent.py keeps the 5-step loop +
compaction + streaming + permission checking DRY across agents.

**Implementation order refined.** The manifest's "Next steps" now
recommends promoting the existing `backend/src/tools/browser_agent.py`
to a full agent FIRST — it's already domain-scoped in name, so it's the
smallest-risk first concrete step (no existing coding/research agent to
break). Then extract `base_agent.py` from `agent/loop.py` with
`browser_agent.py` as the first subclass. Then build `coding_agent.py`
+ `workspace_state.py` (highest leverage per ADR-5). Then
`research_agent.py` and `direct_agent.py`.

**Design risk flagged.** Per ADR-6 point 6: tool descriptions are the
real design risk. Even with a scoped toolset per agent, a 1B-class model
needs the tool schema itself to pre-disambiguate. This is an
implementation-time concern but the most likely failure mode — test
early that the model reliably picks the right tool from each agent's
scoped surface. Don't wait until all agents are built to discover the
tool descriptions are too vague.

**No code changes this session** — ADR-6 capture only, same scope
discipline as Sessions 9, 12, 13 (architecture-capture sessions don't
touch product code).

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 15)

First implementation session for this feature. Three architecture-
capture sessions (12, 13, 14) preceded it; the manifest's "Next steps"
was detailed enough that implementation could start immediately.

**What landed:**

Created `backend/src/agents/` package — the structural skeleton ADR-6
calls for:

- `base_agent.py` — abstract `BaseAgent` class + `AgentConfig` dataclass.
  The `AgentConfig` carries the ADR-5 hard caps (`max_iterations`,
  `max_wall_clock_secs`) and the scoped `allowed_tools` frozenset per
  ADR-6. `BaseAgent` defines the abstract interface (`config()`,
  `build_context()`, `is_done()`, `description()`) plus a shared
  `run()` that delegates to the existing `AgentLoop` in Phase 1
  (non-breaking) and a `scoped_tools()` helper that filters the global
  tool list down to the agent's allowlist.
- `registry.py` — name → agent class registry with `register()`,
  `get_agent()`, `list_agents()`, `is_registered()`. The UI picker /
  intent router will call `get_agent(name)` to look up agents.
- `browser_agent.py` — first concrete `BaseAgent` subclass. Supplies
  browser-specific config (15 max iterations, 240s wall clock, scoped
  to `Intent.BROWSE` only), delegates to `browser/` subpackage for
  context/tools/is_done.
- `browser/` subpackage — `context_builder.py` (browser-context header
  + memory facts + orchestrator plan), `tools.py` (`BROWSER_TOOLS =
  {Intent.BROWSE}` — the smallest possible scoped surface, ideal for
  testing the scoped-tools concept), `is_done.py` (Phase 1: always
  returns `(False, "")` — lets existing AgentLoop handle termination).

19 new tests in `tests/agents/test_agents.py` lock in: BaseAgent is
abstract, BrowserAgent config/description/context/is_done/scoped_tools,
registry register/get/list/is_registered/conflict-raises. All 19 pass.
Full suite: 216 pass (197 baseline + 19 new), 0 real ruff bugs (112
E501 pre-existing), mypy error is pre-existing numpy stub issue.

**Design decisions made during implementation:**

1. **Non-breaking Phase 1 delegation.** `BaseAgent.run()` delegates to
   the existing `AgentLoop` rather than hosting the loop body itself.
   This keeps the new abstraction non-breaking — all existing traffic
   continues to flow through `AgentLoop` unchanged. Phase 2 (next
   session) will extract the loop body into `BaseAgent._run_loop()`.
   The `agent/loop.py` docstring documents this phase plan.

2. **The existing `tools/browser_agent.py` stays registered.** The new
   `BrowserAgent` class composes the existing tool — it doesn't replace
   it. The tool continues to be available via the flat `tools/`
   registry; the new agent class is the structural skeleton for
   per-agent scoping. A future session will migrate the routing so
   browser tasks go through `BrowserAgent.scoped_tools()` instead of
   the flat `_filtered_tool_defs()`.

3. **`AgentConfig` carries the ADR-5 hard caps.** `max_iterations` and
   `max_wall_clock_secs` are per-agent, with sensible defaults
   (`DEFAULT_MAX_ITERATIONS = 20`, `DEFAULT_MAX_WALL_CLOCK_SECS = 300`).
   BrowserAgent overrides to 15 / 240 (browser tasks are slow but
   rarely need many iterations). These caps aren't enforced yet in
   Phase 1 (the existing AgentLoop has its own MAX_ITERATIONS); Phase 2
   will enforce them in `BaseAgent._run_loop()`.

4. **`scoped_tools()` is a method, not a property.** It takes the full
   tool list as an argument so the agent can filter against whatever
   the global registry currently has, at call time. This avoids
   ordering issues with tool registration vs. agent construction.

5. **Description quality matters (ADR-6 point 6).** The test
   `test_browser_agent_description_is_concrete` asserts the description
   is >50 chars, mentions "browser" and "click"/"navigate", and
   mentions what it CAN'T do. This locks in the ADR-6 point-6
   requirement that agent descriptions must be concrete enough for a
   gemma3:1b-class model to disambiguate.

**What didn't land (deferred to next session):**

- Loop body extraction (`BaseAgent._run_loop()`) — Phase 2
- Intent router wiring (`model_router.py` → `agents.registry.get_agent()`)
- `coding_agent.py` + `workspace_state.py` — the ADR-5 highest-leverage piece
- `research_agent.py`, `direct_agent.py`
- Context compaction step (B-2026-07-26-2)

The session stayed scoped to "promote browser_agent to a full agent as
the smallest-risk first concrete step" per the manifest's next-steps.
Didn't try to do too much — the loop body extraction is a separate
session's work.

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 16)

Delivered the ADR-5 differentiator: the workspace-state feedback loop.
This is the "observations flow back into context every turn" line from
the CODING HARNESS diagram — the literal difference between a harness
and a bare API.

**Key decision: deviated from the manifest's "Phase 2 first" plan.**
The Session 15 manifest said `coding_agent.py + workspace_state.py`
"require Phase 2 loop extraction first." Session 16 reconsidered that
rationale and concluded it's wrong for `workspace_state.py` specifically:
it's a standalone service (`snapshot() -> dict`) that can be wired into
the existing `AgentLoop.run()` with a small surgical change, without
extracting the loop body. This delivers the ADR-5 differentiator
without the risky 2926-line refactor. Phase 2 (full loop extraction)
remains a future session's work but isn't blocking. The manifest's
"Next steps" was corrected to reflect this.

**What landed:**

1. **`backend/src/core/workspace_state.py`** — the feedback service.
   - `WorkspaceSnapshot` dataclass: git_available, git_status,
     git_diff_stat, git_branch, git_head, last_build_result, open_files,
     timestamp. `is_clean()` helper.
   - `snapshot(cwd)` — takes a point-in-time snapshot. Never raises
     (git unavailable → git_available=False, all git_* fields empty).
     5s timeout on all git subprocess calls.
   - `format_snapshot(snap)` — formats as a string for context
     injection. Concise (gemma3:1b-class hardware — every token
     expensive). Caps git status at 50 lines, diff stat at 30 lines,
     build output tail at 500 chars.
   - `mark_turn_start(cwd)` — records current HEAD as the baseline for
     the next snapshot's diff. Called at the beginning of each agent
     turn.
   - `record_build_result(result, command, output_tail, exit_code)` —
     records the last test/build/typecheck result. Persists across
     snapshots within a session.
   - `reset()` — clears per-session state (for tests).
   - Git helpers: `_git_rev_parse`, `_git_branch`, `_git_status_short`,
     `_git_diff_stat` — all synchronous, all timeout-guarded, all
     return None on failure.

2. **25 tests** in `tests/core/test_workspace_state.py`: WorkspaceSnapshot
   defaults + is_clean variants, snapshot() on non-git dir + nonexistent
   dir + clean repo + dirty repo + diff stat + diff since
   mark_turn_start, mark_turn_start() in git repo + non-git dir,
   record_build_result() stores + caps output + persists across
   snapshots, format_snapshot() empty + branch/head + clean + dirty +
   build result + caps status lines, reset() clears build result +
   turn head, git helper edge cases (timeout + git not on PATH).

3. **Wired into `AgentLoop.run()`** — small surgical change (3 edits):
   - Added `mark_turn_start()` + `snapshot()` + `format_snapshot()` at
     step 1 (assemble prompt), guarded by `WORKSPACE_STATE_ENABLED`
     flag and a try/except (workspace_state must never break the loop).
   - Appended `workspace_context` to the system prompt after
     `build_agent_system_prompt()` builds it.
   - Added `_loop_start_time = time.monotonic()` at the top of `run()`
     and a wall-clock cap check at the top of the iteration loop:
     `if _elapsed > MAX_WALL_CLOCK_SECS: break` (with obs emit + log
     warning).

4. **`MAX_WALL_CLOCK_SECS = 300.0`** + **`WORKSPACE_STATE_ENABLED = True`**
   added to `agent/constants.py`. The wall-clock cap is the ADR-5 "OR
   limit" — prevents a small model from spinning forever. 300s = 5 min.

**Design decisions:**

1. **Standalone module, not part of BaseAgent.** `workspace_state.py`
   lives in `core/` not `agents/`. It's a service the agent loop
   consumes, not part of the agent abstraction. This keeps it usable
   by the existing `AgentLoop` (Phase 1) AND by `BaseAgent._run_loop()`
   (Phase 2) without restructuring.

2. **Never raises.** `snapshot()` catches all git failures (timeout,
     FileNotFoundError, OSError) and returns `git_available=False`. The
   agent loop's try/except is a second safety net. Workspace state is
   observability — it must never break the primary code path.

3. **Per-turn diff baseline.** `mark_turn_start()` records the HEAD at
   the beginning of each turn. The next snapshot diffs against it,
   showing only what changed during this turn. Without
   `mark_turn_start()`, snapshot reports the full unstaged diff — still
   useful, just less precise.

4. **Wall-clock cap breaks the loop, doesn't raise.** When the cap is
   hit, the loop `break`s and falls through to the existing "force
   final answer" path (which already handles the max-iterations case).
   No new error path — just a new termination condition.

5. **`WORKSPACE_STATE_ENABLED` flag.** Defaults True but can be
   disabled via constants.py if the context bloat becomes a problem
   on small models. The flag is checked in the loop, not in
   workspace_state itself — the service is always available, the loop
   decides whether to use it.

**What didn't land (deferred):**

- Intent router wiring (`model_router.py` → `agents.registry.get_agent()`)
  — next session's smallest step
- `coding_agent.py`, `research_agent.py`, `direct_agent.py` subclasses
- Phase 2 loop body extraction (`BaseAgent._run_loop()`) — not blocking
- Context compaction step (B-2026-07-26-2) — deferred
- Open-file tracking (frontend would need to report open files to the
  backend) — `open_files` field exists in WorkspaceSnapshot but is
  always empty for now

**Test failures during development:** 2 of the initial 25 tests
failed. (1) `test_snapshot_diff_since_mark_turn_start` — passed `&&`
as separate args to `git add` instead of using `shell=True`; fixed by
using a shell string. (2) `test_snapshot_includes_diff_stat` — wrote
a new untracked file, but `git diff --stat` doesn't show untracked
files (only tracked-but-modified); fixed by modifying the existing
tracked README.md instead. Both were test bugs, not module bugs — the
module behaved correctly.

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 17)

Built the CodingAgent — the second concrete BaseAgent subclass and the
centerpiece of the CODING HARNESS diagram. Same thin-subclass pattern
as BrowserAgent (Session 15): scoped tools, context builder, is_done,
non-breaking Phase 1 delegation to existing AgentLoop.

**What landed:**

Created `backend/src/agents/coding/` subpackage + `coding_agent.py`:
- `coding/tools.py` — `CODING_TOOLS = {shell, file_task, file_write,
  edit_file, code_exec}`. 5 tools — the focused coding surface from
  the diagram's Column 3 (Execute: shell/file_read/code_exec; Land:
  file_write/file_edit). Excludes web_search, web_fetch, browse,
  memory_op, sysinfo.
- `coding/context_builder.py` — coding-specific context header.
  Mentions the workspace_state feedback loop (the coding agent benefits
  most from it — git diff shows what it changed, build/test results
  show whether the change worked). Includes memory facts (capped at 10)
  + orchestrator plan.
- `coding/is_done.py` — Phase 1: always `(False, "")`. Phase 2 will
  add: tests pass → done, build succeeds → done, no more tool calls →
  done.
- `coding_agent.py` — `CodingAgent(BaseAgent)`. Config: name="coding",
  max_iterations=20, max_wall_clock_secs=600 (10 min — coding tasks
  are slow and need more headroom than browser tasks). Description is
  concrete (ADR-6 point 6): mentions what it does (edits files, runs
  shell, executes code), what it can't do (web/browser/memory), and
  the workspace state feedback loop.

17 new tests in `tests/agents/test_coding_agent.py`: config, description
concreteness, build_context (header + memory facts + workspace state
mention), is_done Phase 1, scoped_tools filters non-coding (5 tools,
excludes web/browser/memory/sysinfo), registry (coding registered,
both browser+coding present), CODING_TOOLS invariants (subset of
AGENT_ALLOWED_TOOLS, 5 tools, excludes web/browser), build_coding_context
(memory facts capped, orchestrator plan, workspace mention), is_coding_done
Phase 1, coding vs browser comparison (disjoint toolsets, coding has
more iterations/wall-clock).

**Pre-existing naming inconsistency discovered:**

The assertion `CODING_TOOLS.issubset(AGENT_ALLOWED_TOOLS)` caught a
naming mismatch: `Intent.FILE_EDIT.value` is `"file_edit"` but
`AGENT_ALLOWED_TOOLS` uses `"edit_file"` (the tool module name in
`tools/edit_file.py`). Most intent values match their tool module names,
but FILE_EDIT doesn't — its intent value is `"file_edit"` while its
tool module is `edit_file.py`. Fixed by using string literals that
match `AGENT_ALLOWED_TOOLS` (the names the tool-filtering logic in
`agent/loop.py` actually compares against), with a NOTE comment
documenting the inconsistency. This is a pre-existing codebase issue,
not introduced by this session — just surfaced by the assertion.

**Design decisions:**

1. **5 coding tools, not 10.** The coding agent's scoped toolset is
   shell + file_task + file_write + edit_file + code_exec. Excludes
   web_search/web_fetch (research agent), browse (browser agent),
   memory_op (secondary during coding — the agent has env_context +
   workspace_state), sysinfo (the agent gets system info from
   env_context already). Smaller surface = more reliable selection on
   gemma3:1b-class hardware (ADR-6 point 6).

2. **20 iterations / 600s wall clock.** Coding tasks need more headroom
   than browser tasks — a typical "create X" task takes 2-3 iterations,
   but debugging can take more. 20 iterations / 10 minutes is generous;
   the wall-clock cap (added Session 16) is the real safety net. The
   existing AgentLoop's MAX_ITERATIONS=5 still applies in Phase 1 (the
   AgentConfig caps aren't enforced yet — that's Phase 2).

3. **Context mentions workspace_state.** The coding agent's
   build_context() explicitly mentions "The workspace state (git
   status, diff since last turn, last build/test result) is injected
   into your context every turn — use it to verify your changes." This
   primes the model to look for and use the workspace_state feedback
   (which AgentLoop.run() injects per Session 16). The test
   `test_build_coding_context_mentions_workspace_state` locks this in.

4. **Disjoint toolsets between agents.** The test
   `test_coding_and_browser_have_different_toolsets` verifies that
   CODING_TOOLS and BROWSER_TOOLS are disjoint — no overlap. This is
   the ADR-6 scoped-toolset value: each agent has its own focused
   surface, the model never sees tools outside its agent's scope.

**What didn't land (deferred):**

- `research_agent.py` + `direct_agent.py` — next session (same pattern,
  should be quick)
- Intent router / engine pipeline wiring — needs a design decision
  (UI picker vs intent-based auto-selection)
- Phase 2 loop body extraction — not blocking
- Context compaction step (B-2026-07-26-2) — deferred


---
## 2026-07-26 — Super Z / GLM-5.2 (Session 18)

Completed the 4-agent registry. Built ResearchAgent (web_search +
web_fetch, 10 iters / 300s) and DirectAgent (tools_enabled=False, empty
toolset, 1 iter / 60s). Same thin-subclass pattern as browser + coding.
23 new tests verify all 4 agents, their scoped toolsets are pairwise
disjoint (ADR-6 value), and DirectAgent is the only agent with
tools_enabled=False. Registry now complete: browser, coding, research,
direct. This is the ADR-6 organizational structure fully in place —
4 specialized agents sharing BaseAgent, each with its own scoped
toolset. The actual routing (which agent gets selected for a given
user message) is Session 19's work.
---
## 2026-07-26 — Super Z / GLM-5.2 (Session 19)

Built the intent→agent selection layer — `agents/selection.py`. Maps
every Intent enum value to an agent name, then looks up the agent class
via the registry. 16 new tests verify: every intent is mapped (no
KeyErrors), the mapping is deterministic, each intent maps to the agent
whose scoped toolset includes that intent, and select_agent() returns
the right BaseAgent subclass.

The selection layer is non-breaking (opt-in). The existing engine
pipeline still uses AgentLoop directly. A future session wires
`select_agent(intent)` into the engine to replace the if/else — that's
the last wiring step, but it needs a design decision on UI picker vs
auto-selection (ADR-6 prefers UI picker; this intent-based mapping is
the deterministic fallback).

**Feature at natural completion point.** The ADR-5 differentiator
(workspace_state feedback loop) is live. The ADR-6 organizational
structure (4 agents sharing BaseAgent, scoped tools) is in place. The
selection layer is built and tested. Deferred: Phase 2 loop extraction,
engine wiring, context compaction.

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 20)

Wired the agents into the engine end-to-end. The 4 agents are no longer
dead code — the engine pipeline now calls `select_agent(intent)` to pick
the agent, constructs it, and calls its `run()` method. The agent passes
its scoped toolset to `AgentLoop.run()` via the new `agent_config`
parameter, so the model only sees the tools that belong to its agent.

**What landed:**

1. `_filtered_tool_defs()` now accepts an optional `allowed_tools`
   parameter. When provided, filters to that scoped set instead of the
   global `AGENT_ALLOWED_TOOLS`. Default behavior unchanged (backward
   compat).

2. `AgentLoop.run()` now accepts an optional `agent_config` parameter.
   When provided, its `allowed_tools` is passed to `_filtered_tool_defs()`
   — the model sees only the agent's scoped tools.

3. `BaseAgent.run()` now passes `self.config()` as `agent_config` to
   `AgentLoop.run()`. The scoped toolset flows through automatically.

4. `AGENT_SELECTION_ENABLED = True` added to `constants.py`. When True,
   the engine uses `select_agent(intent)` to pick the agent.

5. Engine pipeline (`_pipeline.py`) wired: when `AGENT_SELECTION_ENABLED`,
   calls `select_agent(effective_intent)` → constructs the agent → calls
   `agent.run()`. Falls back to direct `AgentLoop.run()` on any failure
   (non-breaking — the try/except catches selection errors and logs a
   warning).

6. 7 new tests in `tests/agents/test_scoped_tools.py` verify
   `_filtered_tool_defs()` respects the scoped allowlist: coding agent
   sees 5 tools, browser agent sees its subset, empty set returns no
   tools, coding scope is smaller than global.

**Verified end-to-end:** smoke test confirmed coding agent sees exactly
5 tools (code_exec, edit_file, file_task, file_write, shell) vs 9 global
tools. The ADR-6 scoped-toolset value is now live — a gemma3:1b-class
model choosing among 5 coding tools is far more reliable than choosing
among 9+ flat tools.

**The feature is now genuinely complete.** ADR-5 differentiator (workspace
feedback) live. ADR-6 4-agent structure built. Selection layer built.
Engine wired. Scoped tools actually filter. What remains deferred: Phase
2 loop body extraction (internal refactor, non-blocking) and context
compaction (B-2026-07-26-2, separate backlog item).

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 21)

Fixed a real production bug the user caught: a one-word "Hi" was burning
11.5s and ~4.8k tokens because it hit the full ThinkingDispatcher (JSON-
schema capability inference LLM call) before being classified as CHAT.
That's massive overkill for trivial inputs.

**Root cause:** the engine pipeline runs ThinkingDispatcher for every
message that isn't client-pre-classified. The dispatcher makes a full
LLM call with a JSON-schema prompt to infer capabilities (requires_tools,
requires_grounding, execution_mode, etc.). For "Hi" this is 11.5s of
wasted compute — the answer is obviously "just chat, no tools."

**Fix:** added `backend/src/core/trivial_input.py` — a deterministic
trivial-input detector that short-circuits greetings/thanks/farewells/
yes-no/acknowledgments BEFORE the dispatcher runs. The detector is
conservative: only matches obviously-conversational inputs (≤5 words,
≤40 chars, matches one of ~35 regex patterns). Anything ambiguous falls
through to the normal pipeline. Wired into `engine/_pipeline.py`
process() right after the safety gate (step 0.5).

The short-circuit streams a direct chat response with a minimal prompt
(no system prompt machinery, no tool defs, no JSON schema). Target:
<500 tokens, <2s for trivial inputs (vs 11.5s / 4.8k tokens before).

27 new tests verify the detector: greetings (hi/hello/hey/good morning/
what's up), farewells (bye/see you/good night), thanks (thanks/thx/ty/
appreciate it), acknowledgments (ok/okay/got it/sure), yes-no (yes/no/
yep/nope), and non-trivial inputs that must NOT short-circuit (questions,
code requests, long messages, greeting+question combos like "hi, can you
help?"). Punctuation stripped, case-insensitive, whitespace trimmed.

**Minimax model issue (separate):** the user's screenshot showed
`minimax-M2.1-free` not supported. The codebase uses `minimax-m2.5-free`
(lowercase, .5). The user's LocalMind settings have a typo — `M2.1`
instead of `m2.5`. Not a code bug; the user needs to update their
settings to `minimax-m2.5-free`.

**The user was right to call this out.** I declared the feature
"genuinely complete" in Session 20, but a one-word greeting burning
11.5s is a production-breaking UX bug. The agents were wired in but
the pipeline itself was over-engineered for trivial inputs. This fix
addresses the root cause.

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 22)

Fixed the chat title pollution bug the user reported. The sidebar was
filling up with "Hi" / "Hello" / "Quick hello" because:

1. Stage 1 (placeholder): `generate_title_smart("Hi")` returned "Hi" (the
   greeting text, capitalized) — not "New Chat"
2. Stage 2 (LLM refine): `refine_title_async()` fired on every first
   message, including "Hi" — wasting an LLM call that either failed
   (model error → silent fallback to "Hi") or produced a bad title

**Root cause:** title-gen was turn-count-gated (fires on `is_first`),
not intent-gated. A greeting on turn 1 has no intent to summarize.

**Fix (per the user's design):** title-gen is now intent-gated using
the `is_trivial_input()` detector from Session 21.

1. `generate_title_smart()` now returns "New Chat" for trivial inputs
   (greetings/thanks/farewells/yes-no/acknowledgments), NOT the greeting
   text. The sidebar shows "New Chat" until a substantive message arrives.

2. New `should_refine_title(message, current_title)` function — returns
   True only when:
   - The message is non-trivial (has real intent to summarize)
   - AND the title hasn't already been refined (current_title is None,
     "New Chat", or "Error — try again")
   This is the intent-gated trigger the user requested.

3. `refine_title_async()` now checks `is_trivial_input()` first and
   returns immediately for greetings — no LLM call wasted on "Hi".

4. `chat.py` Stage 2 now calls `should_refine_title(message, current_title)`
   instead of just checking `is_first`. Title-gen fires on the first
   SUBSTANTIVE message, regardless of turn number. If message 1 is "Hi",
   title-gen skips. If message 2 is "How do I fix a Python bug?",
   title-gen fires on that.

**Behavior change:**
- "Hi" → placeholder "New Chat", no LLM call → title stays "New Chat"
- "Hi" then "How do I fix a Python bug?" → title-gen fires on message 2,
  produces a real title like "Python debug help"
- "How do I fix a Python bug?" as first message → title-gen fires
  immediately (substantive first message)
- Already-refined titles are NOT overwritten (no re-titling on drift —
  per the user's question, the title locks in after first generation)

21 new tests verify the intent-gating: trivial inputs return "New Chat"
placeholder, trivial inputs don't trigger refine, substantive inputs do
trigger refine, already-refined titles don't get overwritten.

---
## 2026-07-26 — Super Z / GLM-5.2 (Session 23)

Fixed a critical security bug: the model's internal reasoning was
leaking into the chat response verbatim, including system prompt
contents (user's name "tison", "Windows 11", "0 facts in memory",
the full values list, response format examples). Any user could extract
the entire system prompt just by looking at a "Hi" response.

**Root cause:** the OpenAI-compat adapter was MERGING reasoning_content
into text:
```python
text = delta.get("content", "") or delta.get("reasoning_content", "")
```
This treats the model's internal thinking as interchangeable with the
actual answer — if `content` is empty, it falls back to `reasoning_content`.
That's why thinking leaked into chat: the adapter was merging reasoning
into the text stream instead of routing it to the `thinking` field.

**The fix:** built `_extract_content_and_reasoning(delta)` helper that
keeps them SEPARATE:
- `content` → `StreamChunk.text` (the actual answer)
- `reasoning_content` → `StreamChunk.thinking` (internal reasoning, rendered
  in a collapsible "THINKING" panel)
- Never merged

Also handles `<think>...</think>` tags (DeepSeek-v3, Qwen format) —
extracts the tag content to `reasoning`, removes it from `content`.

Fixed all 4 occurrences of the bug in openai_compat.py (lines 742, 854,
1028, 1190). The Ollama adapter was already correct (routes thinking to
the `thinking` field) — the bug was only in the OpenAI-compat adapter.

12 new tests verify the separation: content-only, reasoning-only, both
fields, empty delta, None values, <think> tag handling (closed/unclosed/
multiple), and the critical security test — PII (name, OS, memory state,
system prompt values) stays in reasoning, NOT in content.

**The user was right to call this "worse than a display bug."** It's a
prompt-leak/security concern: any user could extract the system prompt
(including user PII structure) just by looking at thinking output. The
fix ensures reasoning never appears in the chat text, only in the
collapsible thinking panel.

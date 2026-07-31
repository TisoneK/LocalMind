# Agent Instructions — LocalMind

<!-- Generated at bootstrap from .context/core/templates/AGENTS.md.
Refreshed on core updates (fill <PROJECT_NAME> again). Optionally also
copied to CLAUDE.md and .github/copilot-instructions.md so tools that
auto-load those paths get the same digest. -->

This repo uses the `.context/` protocol: persistent agent memory plus a
vendored copy of the full workflow, committed to git. **Before doing any
work, read `.context/kickoff.md` and follow it.** It routes you — local
IDE agent or cloud/sandbox agent — to the right instruction set in
`.context/core/rules/`.

If you read nothing else, obey these rules:

1. **Start at `.context/kickoff.md`.** Do not treat "start the context
   workflow" as running this project's app, and do not grep the codebase
   for "context" — the protocol lives in the `.context/` directory.
2. **Never write under `.context/core/`** — it is a read-only, versioned
   copy of the protocol. All project memory you write lives under
   `.context/memory/`.
3. **Pick your instruction set by YOUR agent type**, never by what a
   previous session recorded: local IDE agent →
   `.context/core/rules/ai-engineering-protocol-local.md`; cloud/sandbox
   agent → `.context/core/rules/ai-engineering-protocol.md`. Local
   agents never use PATs or clone this repo; cloud steps are not yours.
4. **Read memory before working:** at minimum
   `.context/memory/workflows/active.md`,
   `.context/memory/agents/sessions.md` (last entries),
   `.context/memory/tasks/current.md`, and
   `.context/memory/inefficiencies/log.md` (known traps). If the
   active session has detailed notes at
   `.context/memory/sessions/`, skim them for current state.
5. **One task at a time.** If `.context/memory/tasks/current.md` shows
   another live session in progress, do not start.
6. **Append-only files are append-only:** `agents/sessions.md`,
   `tasks/backlog.md`, `plans/decisions.md`, `flaws/log.md`,
   `inefficiencies/log.md`. Add at the bottom; never edit or delete
   past entries.
7. **No secrets in tracked files, ever.** Values go only in
   `.context/memory/secrets/` (self-gitignored). Never echo a secret or
   token in chat, logs, or commit messages.
8. **Two surfaces, two prefixes:** editing product code = normal commit
   prefixes; editing `.context/` = `chore(context):` (reports:
   `docs(review):`). Never mix both surfaces in one commit.
9. **The session is not done until everything is committed AND pushed**,
   the session is logged in `.context/memory/agents/sessions.md`, and
   `.context/memory/tasks/current.md` is cleared. If the user has to
   remind you to commit or push, that is a protocol failure — log it in
   `.context/memory/flaws/log.md`.
10. **Don't ask permission for the default next step.** Do it and
    report. Ask only on genuine ambiguity or destructive/irreversible
    actions.

Formats and file rules: `.context/core/schemas/context-schema.md` is
the single source of truth. Project-specific rule adjustments:
`.context/memory/overrides/rules.md` (they win over the edition).
## LocalMind architectural target (added 2026-07-26, Session 12)

Agent-mode is aligned to the **CODING HARNESS closed-loop** model
(Context → 5-step Agent Loop → Tools, with a Workspace feedback bar
that pipes git/diff/test output back into context every turn). See
**ADR-5** in `.context/memory/plans/decisions.md` for the foundational
diagram-to-module mapping. ADR-8 is now the standing implementation
target; it builds on ADR-5 without replacing the closed-loop model.
Do not relitigate the closed-loop model — implement the current ADR-8
target in `workflows/active.md`.

## Feature-scoped memory (added 2026-07-26, Session 13)

Multi-session work is tracked under
`.context/memory/features/<slug>/manifest.md` — read the active one
(named in `tasks/current.md`'s `Feature:` line) before starting; update
it before you stop. The `features/ledger.md` file is append-only and
permanent (one line per feature ever); the per-feature directory is
working state that may be archived to `features/archive/` once the
ledger line records the merge sha or abandonment reason. Single-session
work uses `Feature: none` and skips the feature directory entirely.
This is a project-level preview ahead of core 0.5.0 (feature-scoped memory is not yet part of the vendored core);
see `memory/overrides/rules.md` for the full opt-in.

## Silent-failure fallback contract (added 2026-07-27, Session 31)

The agent loop's contract with the engine is: **always yield text on
the silent-failure path**. When the model returns an empty stream (or
all chunks are filtered out as system-leak XML — common with free-tier
models), the loop MUST yield a meaningful fallback that surfaces what
tools actually ran, NOT silently return nothing. The engine's
last-resort fallback (when the loop yields zero text) is intent-aware
and suggests concrete next steps (switch model, one step at a time,
re-run) — it MUST NOT say "rephrase your request" because the user's
phrasing is almost never the cause (real cause: free-tier model
overload or context window overflow).

If you add a new code path where the model's text might be empty after
tool execution, wire it through `AgentLoop._summarize_trace_for_user()`
so the user sees what tools ran. Regression tests live in
`tests/e2e/test_tool_execution_failure.py`.

## Adapter provider quirks (added 2026-07-27, Session 31 addendum)

The OpenAI-compat adapter (`backend/src/adapters/openai_compat.py`)
has two provider-specific quirks that were the ACTUAL root cause of the
"Tools execution failure" bug (not model overload — that was a wrong
guess). If you touch the adapter, know these:

1. **Trailing `tool` role → 400 on some providers.** DeepSeek-v4-flash-free
   (via Zen) and possibly other providers reject requests where the last
   message is a `tool` role. The agent loop sends this format after every
   tool execution. Fix: `chat_with_tools` appends a synthetic `user`
   message when the last message is `tool` role. This is general (applies
   to all providers) — do not remove it unless you've verified the
   provider accepts tool-terminated messages.

2. **Phase 1 detection must wait for content, not just reasoning.** Some
   models (DeepSeek-v4-flash-free) produce 80+ reasoning chunks before
   the tool_call delta arrives. Phase 1 breaks at `chunks_read >= 15` —
   but ONLY if it has seen actual `content` (not just reasoning).
   Reasoning-only streams keep reading until content or tool_calls
   arrives (hard cap: 500 chunks). If you change the Phase 1 break
   condition, test against a model that produces long reasoning streams
   before tool calls — otherwise you'll reintroduce the silent-drop bug.

Regression tests: `tests/adapters/test_zen_deepseek_fixes.py`. The
real-model test scripts that found these bugs are in
`/home/z/my-project/scripts/` (not committed — they contain API key
references in comments, but no actual keys).

## Iteration limit + check-before-acting contract (added 2026-07-27, Session 32)

Two contracts from Session 32, both critical — removing either
reintroduces the "Tools execution failure" bug:

1. **Iteration limit must be >= 8 and configurable.** The Session 31 cap
   of 3 was too low — the model did 3 reconnaissance calls (checking
   state before acting, exactly what we want) and hit the cap before the
   actual work. `MAX_ITERATIONS` defaults to 8 (configurable via
   `LOCALMIND_MAX_ITERATIONS` env var); `MAX_WALL_CLOCK_SECS` defaults to
   180s (configurable via `LOCALMIND_MAX_WALL_CLOCK_SECS`). Do NOT lower
   these defaults below 8 / 180s without a concrete reason — multi-step
   tasks (recon + work + verify) need the room. The wall-clock cap is the
   real safety net against a spinning model, not the iteration cap.

2. **Fallback messages must say "iteration limit reached" when
   `trace.hit_limit` is True.** Sessions 21-31 kept guessing "overload" /
   "context overflow" / "tool output too large" when the actual cause was
   the iteration cap. The misdiagnosis was worse than no diagnosis — it
   sent the user down wrong paths. When `hit_limit` is True,
   `_summarize_trace_for_user()` and the engine fallback MUST say
   "iteration limit reached" explicitly and suggest "tell me to continue"
   (NOT "switch to a larger model" — the model didn't fail, it ran out of
   steps). If you add a new fallback path, check `trace.hit_limit` first.

3. **"Check before acting" is a universal workflow constraint.**
   `backend/data/workflows/safety.md` defines the rule: every tool
   invocation that creates, writes, modifies, or deletes something MUST
   first check whether the target already exists or has content, and
   adapt the plan based on what's found — never act on an assumed state.
   This is injected into the agent system prompt for ALL agent intents via
   `build_agent_system_prompt()`. If you add a new tool, the safety
   workflow already covers it (it's universal). If you remove the
   injection, the model will go back to running `mkdir` before checking
   if the dir exists, and barreling into non-empty unrelated directories.

Regression tests: `tests/e2e/test_iteration_limit_and_safety.py`.

## LocalMind architectural target — ADR-8 (added 2026-07-27, Session 34)

The standing Target is now **ADR-8: agent-centric routing** (tasks →
agents → tools, not tasks → tools → agents). See the full ADR in
`.context/memory/plans/decisions.md` ADR-8 for the five principles
(classification by task type, agents own tools, agents collaborate,
the workflow is the value, agents are directories) and the four
implementation phases.

**This supersedes ADR-5 as the standing Target** — but it does NOT
supersede ADR-5 architecturally (per ADR-8's "Supersedes / builds on"
section: ADR-8 *builds on* ADR-5; the 5-step closed-loop shape stays;
agents just get richer context and delegation ability). All the
Session 31-33 fixes (iteration cap, hit-limit-aware fallback,
check-before-acting safety workflow, `_obs.all()` not `drain()` in
the engine) are still in force and must not be regressed.

**Four phases, multi-session:**
1. **Agents as directories** — structural foundation. Move
   `coding_agent.py` → `agents/coding/agent.py`,
   `research_agent.py` → `agents/research/agent.py`,
   `browser_agent.py` → `agents/browser/agent.py`,
   `direct_agent.py` → `agents/direct/agent.py`. Move
   `backend/data/workflows/<name>.md` →
   `agents/<name>/workflow.md`. Move inline personas from
   `prompts.py:_PERSONA_MAP` → `agents/<name>/persona.md`.
   Registry auto-discovers directories with `agent.py`. Backlog item:
   "Wire `build_context()` into `BaseAgent.run()`" (Session 33) is
   Phase 2's prerequisite and currently blocked on Phase 1.
2. **Wire `build_context()` into `BaseAgent.run()`** — workflow files
   finally reach the model. Highest-leverage piece. Backlog item
   already filed (Session 33).
3. **Agent-initiated delegation** — replace `should_use_sub_agents()`
   keyword heuristic with agent-initiated delegation (parallel or
   handoff).
4. **Task-type classifier** — replace or augment the intent classifier
   so "create hello world repo" routes to `task_type=coding` (not
   `intent=SHELL`).

**Per the flaw log (Session 31/33): every phase needs real-model
testing before shipping.** ADR-8 is currently **proposed** (Session 33
filed it; Session 34 — this session — switches the standing Target
from ADR-5 to ADR-8 and seeds the feature-scoped memory at
`.context/memory/features/adr-8-agent-centric-routing/`). No code
changes this session — this is context-only initialization.

**Active feature directory:**
`.context/memory/features/adr-8-agent-centric-routing/` (read its
`manifest.md` + `notes.md` before starting Phase 1 work).

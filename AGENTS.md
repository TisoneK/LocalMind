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
   `.context/memory/inefficiencies/log.md` (known traps).
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

---

## LocalMind architectural target (added 2026-07-26, Session 12)

Agent-mode is being aligned to the **CODING HARNESS closed-loop** model
(Context → 5-step Agent Loop → Tools, with a Workspace feedback bar
that pipes git/diff/test output back into context every turn). See
**ADR-5** in `.context/memory/plans/decisions.md` for the full
diagram-to-module mapping and the four gaps to close. Standing Target
in `workflows/active.md` is currently set to ADR-5 implementation —
backlog items B-2026-07-26-1 (5-step loop + workspace-state injection)
and B-2026-07-26-2 (context compaction) are the entry points. Don't
relitigate the closed-loop model — implement it.

## Feature-scoped memory (added 2026-07-26, Session 13)

Multi-session work is tracked under
`.context/memory/features/<slug>/manifest.md` — read the active one
(named in `tasks/current.md`'s `Feature:` line) before starting; update
it before you stop. The `features/ledger.md` file is append-only and
permanent (one line per feature ever); the per-feature directory is
working state that may be archived to `features/archive/` once the
ledger line records the merge sha or abandonment reason. Single-session
work uses `Feature: none` and skips the feature directory entirely.
This is a project-level preview of core 0.3.0 (core is still at 0.2.0);
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

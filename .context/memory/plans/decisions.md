# Architectural Decisions (append-only, ADR-style)

Decisions already made — future agents respect these rather than
relitigating them. To reverse one, append a new ADR that supersedes it.

---
## ADR-1: LocalMind is dark-only by design (2026-07-11)

- **Status:** accepted
- **Context:** `globals.css` defines both light (`:root`) and dark (`.dark`) CSS variable sets. shadcn/ui components use `dark:` Tailwind variants. But no theme toggle exists, and `.dark` was never applied to `<html>` — so shadcn components rendered in their light theme while custom components used hardcoded dark hex colors, causing visual inconsistency.
- **Decision:** Apply `.dark` class to `<html>` element by default (commit `9bfe8c8`). LocalMind is a dark-only app. Light theme variables in `globals.css` are retained for future theming support but are not currently active.
- **Consequences:** Future agents should NOT flag "missing `dark:` variants" as a theme gap — the app is intentionally dark-only. If a light theme is ever added, the hardcoded hex in custom components (`SettingsModal.tsx`, etc.) must be replaced with CSS variables first. See backlog item "Theming strategy decision needed" — the user may still decide to commit fully to dark-only (remove light variables) or implement a toggle.

---
## ADR-2: SSRF protection re-validates redirect targets (2026-07-11)

- **Status:** accepted
- **Context:** `web_fetch` used `httpx.follow_redirects=True`, which let httpx follow 302 redirects to internal IPs (169.254.169.254, localhost) without re-validation. The SSRF check (`_is_url_safe`) ran only on the initial URL. This is the classic SSRF redirect-bypass pattern — an attacker could coerce the agent into fetching cloud metadata endpoints or internal services.
- **Decision:** Set `follow_redirects=False` and implement manual redirect following with `_is_url_safe()` re-validation on every hop (commit `e49d54a`). Caps at 5 redirects. Resolves relative redirects via `httpx.URL.join()`.
- **Consequences:** Future agents adding URL-fetching code must follow this pattern — never use `follow_redirects=True` without per-hop SSRF re-validation. The regression tests in `tests/tools/test_web_fetch_ssrf_redirect.py` enforce this. If a new tool needs to fetch URLs, copy the redirect-following pattern from `web_fetch.py` rather than re-implementing it.

---
## ADR-3: Reports live in .context/reviews/ (not docs/report/) (2026-07-11)

- **Status:** accepted
- **Context:** Session 1 placed review reports in `docs/report/`. The `.context/` system (introduced Session 2) has a dedicated `reviews/` subdirectory that travels with the repo as agent memory.
- **Decision:** Migrate `docs/report/2026-07-11-review.md` → `.context/reviews/2026-07-11-review.md`. Delete `docs/report/`. All future review reports go in `.context/reviews/YYYY-MM-DD-review.md`.
- **Consequences:** Future agents look for prior reviews in `.context/reviews/`, not `docs/report/`. The old `docs/report/` directory is gone — don't recreate it.

---
## ADR-4: .context/ directory is the agent memory system (2026-07-11)

- **Status:** accepted
- **Context:** Prior to Session 2, there was no structured way for agents to share context across sessions. Each agent started blind. The user and Super Z co-designed the `.context/` system (packaged at `TisoneK/.context`) to solve this.
- **Decision:** LocalMind carries a `.context/` directory at the repo root, committed to git. It contains: `system/` (environments, ai-models), `user/` (identity, preferences), `workflows/active.md`, `agents/sessions.md` (append-only), `reviews/` (one file per session), `tasks/` (current + backlog), `plans/decisions.md` (append-only ADRs), `inefficiencies/log.md` (append-only), and `secrets/` (local-only, self-gitignored).
- **Consequences:** Every agent session reads `.context/` at startup (Step 3) and updates it at the end (Steps 15–17). Append-only logs are never edited — corrections are appended. No secrets in tracked `.context/` files. Context updates commit with `chore(context):` prefix. The protocol lives in the `TisoneK/.context` package repo, not in each project — projects bootstrap from `context-skeleton/` and the `.context/` data lives its own life.

---
## ADR-5: Adopt the CODING HARNESS closed-loop as LocalMind's agent-mode architectural target (2026-07-26)

- **Author:** Super Z / GLM-5.2 (Session 12)
- **Status:** accepted (architectural target — implementation pending, see backlog B-2026-07-26-1 / B-2026-07-26-2 and feature `agent-loop-closed-loop`)
- **Context:** During Session 12 the user shared a "CODING HARNESS" diagram that frames a coding agent not as "LLM + tool-calling" but as a **closed loop** with three columns plus a workspace feedback bar:

  - **Column 1 — Context (blue), "what enters the prompt":** *Gather* (codebase search & index, `@`-files/symbols, docs/AGENTS.md) and *Shape* (thread + instruction, token budget & compaction, prior tool output kept in-window).
  - **Column 2 — Agent loop (orange), "what the harness runs":** a numbered 5-step cycle — (1) assemble prompt from context, (2) model call (plan · tool calls · stream), (3) parse calls · route · permissions, (4) execute tools · capture output, (5) observe errors · diff · test logs — with the explicit footer "↻ Repeat until done, blocked, or limit."
  - **Column 3 — Tools (green), "what changes the world":** *Execute* (terminal/sandboxed bash, read & search files, MCPs & external APIs) and *Land* (apply patches / structured edits, format-on-save & linters, retry on failed apply or test).
  - **Bottom bar — Workspace (yellow), full width:** git state & open files, build/test/typecheck output, real filesystem — *not chat-only*. With the italic note: *"Observations flow back into context every turn — that's why bare API ≠ Cursor."*

  The diagram's thesis, which the user endorsed and forwarded: the **workspace feedback loop** — not the model — is what separates a real coding harness (Cursor, Claude Code) from a bare API call. On LocalMind's target hardware (low-RAM, gemma3:1b-class models), context is the scarcest resource, which makes the *Shape* sub-group (token budget & compaction, prior tool output in-window) and the *Observe* step (feeding diffs/errors/test logs back into context) disproportionately important.

  **Current state of LocalMind's agent-mode** (verified during Session 12 via `wc -l` on the actual source files):

  | Diagram column | Diagram sub-piece | LocalMind module today | Gap |
  |---|---|---|---|
  | Context — Gather | codebase search & index | `backend/src/storage/vector.py` + sqlite-vec ( Sessions 1–7) | present |
  | Context — Gather | `@` files / AGENTS.md | `backend/src/core/context_builder.py` (736 LOC) | present |
  | Context — Shape | thread + instruction | `backend/src/core/session_context.py` (298 LOC) | present |
  | Context — Shape | token budget & compaction | (ad-hoc truncation inside `_pipeline.py`) | **missing — explicit compaction step** |
  | Context — Shape | prior tool output in-window | `backend/src/core/agent/loop.py` (2926 LOC) keeps a tool-history list | partial — no in-window budget enforcement |
  | Agent loop — step 1 | assemble prompt | `context_builder.py` + `agent/prompts.py` | present |
  | Agent loop — step 2 | model call (plan/tool/stream) | `backend/src/core/agent/orchestrator.py` (532 LOC) + `agent/loop.py` | present |
  | Agent loop — step 3 | parse · route · permissions | `backend/src/core/agent/tool_dispatch.py` (109 LOC) + `backend/src/core/safety_gate.py` (135 LOC) | partial — permissions layer exists but is keyword-regex, not an explicit allowlist/confirm-before-execute gate |
  | Agent loop — step 4 | execute · capture | `tool_dispatch.dispatch_with_retry` + `tools/` package | present |
  | Agent loop — step 5 | observe (errors/diff/test) | (logged to observability tab, not fed back into context) | **missing — no automatic feedback into next-turn context** |
  | Agent loop — footer | "repeat until done/blocked/limit" | `agent/loop.py` iterates but has no hard iteration/time cap | **missing — hard cap for small-model safety** |
  | Tools — Execute | terminal/sandboxed bash | `backend/src/tools/shell.py` + `code_executor/sandbox.py` | present (sandboxing is partial — see backlog "Sandbox code execution") |
  | Tools — Execute | read & search files | `backend/src/tools/file_reader.py` | present |
  | Tools — Execute | MCPs & external APIs | `backend/src/tools/web_fetch.py` + `web_search.py` + `browser_agent.py` | present (MCPs not yet wired) |
  | Tools — Land | apply patches / structured edits | `backend/src/tools/file_writer.py` + `edit_file.py` | present |
  | Tools — Land | format-on-save, linters | (not wired into the agent loop) | **missing — no auto-format/lint after apply** |
  | Tools — Land | retry on failed apply or test | `tool_dispatch.dispatch_with_retry` retries tool errors | partial — doesn't retry on *test* failure, only tool exceptions |
  | Workspace bar | git state & open files | `backend/src/api/routes/filesystem.py` + `terminal.py` (user-facing, not agent-facing) | **missing — no agent-facing workspace-state service** |
  | Workspace bar | build/test/typecheck output | (run manually via terminal; output not captured into context) | **missing — same** |
  | Workspace bar | real filesystem (not chat-only) | yes — LocalMind is local-first | present |

  Three of the four modules the user offered to sketch already exist: `context_builder.py` (Context-Shape), `agent/loop.py` (Agent-loop), `tool_dispatch.py` + `safety_gate.py` (Tools-route-permissions). The fourth — a `workspace_state.py` service that pipes git status/diff + test/build output back into the agent's context each turn — **does not exist** and is the diagram's actual differentiator.

- **Decision:** Adopt the CODING HARNESS closed-loop as the architectural target for LocalMind's agent-mode. Specifically:

  1. **Context-Shape gets an explicit compaction step.** Before the model call, if the assembled prompt exceeds a configured token budget, summarize older tool outputs / turns rather than truncating blindly. Sized for the gemma3:1b-class target — every token of context is expensive.
  2. **Agent-loop gets a hard iteration cap.** The loop terminates on "done, blocked, OR limit" — the limit is a hard `max_iterations` + `max_wall_clock` configurable in `constants.py`, so a small model cannot spin forever on a task it can't solve.
  3. **Tools-route gets an explicit permission layer.** The existing `safety_gate.py` keyword-regex destructive-op detector is upgraded (or wrapped) into an explicit allowlist + confirm-before-execute gate for filesystem-write, shell, and delete operations. Local-first means there's no cloud sandbox to fall back on — the permission layer IS the safety boundary.
  4. **A new `backend/src/core/workspace_state.py` service owns the feedback loop.** Each turn, before step 1 (assemble prompt), the agent loop queries `workspace_state.snapshot()` which returns: `git status --short`, `git diff --stat` since last turn, last test/build/typecheck result, and currently-open files. This snapshot is injected into the context for the next model call — that's the "observations flow back into context every turn" line from the diagram, and it's the literal difference between a harness and a bare API.

- **Consequences:**
  - Future agents working on agent-mode MUST consult this ADR before refactoring `context_builder.py`, `agent/loop.py`, `tool_dispatch.py`, `safety_gate.py`, or adding a workspace-state service. Don't relitigate the closed-loop model — implement it.
  - The 2926-line `agent/loop.py` monolith (already flagged in backlog as "Long-term: Decompose monolith files") is the natural place to land steps 1–5 + the iteration cap. The decomposition should follow the diagram's 5-step shape, not an ad-hoc split.
  - `workspace/manager.py` (the per-turn scratch directory with TODO.md / CONTEXT.md / inbox / outbox) is **not** the same as the diagram's "Workspace" bar. The former is an internal isolation layer for tool I/O within one turn; the latter is the persistent project state (git, build, tests) that feeds back across turns. Don't conflate them — the new `workspace_state.py` is a sibling of `workspace/manager.py`, not a replacement.
  - Implementation is multi-session. Backlog items B-2026-07-26-1 (formalize 5-step loop + iteration cap + workspace-state injection — High) and B-2026-07-26-2 (explicit compaction step — Medium) are the two entry points. Pick B-2026-07-26-1 first — the diagram's thesis is that the workspace feedback loop is the differentiator, so it has the highest leverage.
  - Direct-mode (single-shot chat, no tools) is explicitly OUT OF SCOPE for this ADR. The closed loop only matters for agent-mode. Don't add iteration caps or workspace-state injection to direct-mode code paths.

- **Supersedes:** none. Builds on ADR-4 (`.context/` is the agent memory system) — the workspace-state feedback loop turns `.context/`'s cross-*session* memory into cross-*turn* memory *within* a session.

---
## ADR-6: Multi-agent architecture with shared base_agent (refines ADR-5) (2026-07-26)

- **Author:** Super Z / GLM-5.2 (Session 14)
- **Status:** accepted (architectural target — implementation pending, part of feature `agent-loop-closed-loop`)
- **Context:** ADR-5 (Session 12) adopted the CODING HARNESS closed-loop as agent-mode's target but didn't specify the *organizational structure* — one agent or many? In Session 14 the user worked through three options for how `backend/` should be organized:

  **Option 1 — Multi-harness framework** (`harness/coding/`, `harness/research/`, `harness/direct/`):
  base.py defines the abstract loop; each harness supplies `build_context()`, `tools`, `observe()`, `is_done()`. The user rejected this framing: *"More like an agent"* — harnesses are workflow pickers, agents are addressable things.

  **Option 2 — Single unified agent** (`harness/agent.py` + flat `tools/`):
  one agent loop, all tools available, the model dynamically picks tools per task. Closer to how Claude Code behaves — "coding" vs "research" isn't a mode, it's just which tools happen to get called. The user identified the core risk: *"tool descriptions have to be good enough that a small local model (gemma3:1b-class) reliably picks the right one."* With a flat tool surface and a 1B-class model, wrong-tool selection is the likely failure mode.

  **Option 3 — Multiple distinct agents with shared base** (`agents/base_agent.py` + `agents/coding_agent.py` + `agents/research_agent.py` + `agents/browser_agent.py` + ...):
  each agent is a complete, addressable thing — a thin subclass of `base_agent.py` that supplies its own `context_builder`, scoped `tools`, and `is_done()`. Shared in the base: the 5-step loop, compaction, streaming, permission checking. The user converged here: *"Like coding agent, research agent, browser agent."* Key argument: a scoped toolset per agent is exactly what a small model needs — fewer tools to choose from = more reliable selection. And explicit user selection (a UI picker) avoids an expensive LLM-based router call before the real agent even starts.

  **Existing LocalMind structure** (verified Session 14):
  - `backend/src/core/agent/` — `loop.py` (2926 LOC), `orchestrator.py` (532 LOC), `tool_dispatch.py` (109 LOC), `prompts.py`, `constants.py`, `models.py`, `search.py`, `sub_agent.py`, `synthesizer.py`, `agent_filters.py`. This is the de-facto base — the 5-step loop, retry logic, planning. It would become `base_agent.py` + shared infrastructure.
  - `backend/src/tools/` — flat bag of 14 tools: `shell.py`, `file_reader.py`, `file_writer.py`, `edit_file.py`, `web_search.py`, `web_fetch.py`, `browser_agent.py`, `code_exec.py`, `memory_tool.py`, `sysinfo.py`, `installed_programs.py`, plus `base.py`, `contracts/`, `code_executor/`. No per-agent scoping exists today — every tool is available to every agent invocation.
  - `backend/src/core/workspace/manager.py` — the per-turn scratch directory (TODO.md / CONTEXT.md / inbox / outbox). Stays as-is; NOT the same as the ADR-5 `workspace_state.py` service (per ADR-5's "do not conflate" note).

- **Decision:** Adopt **option 3 — multiple distinct agents with shared `base_agent.py`**. This refines ADR-5 by specifying the organizational structure: the closed-loop from ADR-5 is implemented by `base_agent.py`, and multiple specialized agents subclass it. Concretely:

  1. **Target directory structure:**
     ```text
     backend/agents/
       __init__.py
       base_agent.py          # abstract 5-step loop (assemble → call model → parse → execute → observe → repeat)
                               # + shared compaction/token-budget logic, streaming interface, permission checking
                               # + hard iteration cap + wall-clock cap (ADR-5 requirement)
       registry.py             # name -> agent class; the intent router / UI picker selects one

       coding_agent.py         # thin subclass: supplies coding-specific context_builder, scoped tools, is_done()
       coding/
         context_builder.py    # codebase search/index, @file resolution, AGENTS.md
         workspace_state.py    # git status/diff, build/test/typecheck — the ADR-5 feedback service
         tools/
           bash.py             # from backend/src/tools/shell.py
           filesystem.py       # from file_reader.py + file_writer.py + edit_file.py
           code_exec.py        # from code_exec.py + code_executor/

       research_agent.py
       research/
         context_builder.py    # source tracking, query planning
         tools/
           web_search.py       # from web_search.py
           doc_reader.py       # from web_fetch.py (reframed)

       browser_agent.py        # NOTE: backend/src/tools/browser_agent.py already exists — promoted to a full agent
       browser/
         context_builder.py    # page state, DOM snapshot, nav history
         tools/
           navigate.py
           click.py
           extract.py

       direct_agent.py         # thin wrapper — steps 1-2 only (assemble → model → respond), no tool execution
                               # this is what Direct Mode becomes

       <future: automation_agent.py, notes_agent.py, etc.>
     ```

  2. **What each agent supplies to `base_agent.py`:**
     - `context_builder` — its own gather/shape logic (codebase index vs. web search vs. page state vs. nothing)
     - `tools` — its own scoped toolset (a coding agent doesn't have browser tools; a browser agent doesn't have `bash`)
     - `is_done()` — its own stop condition (tests pass / enough sources / task-page reached / user says stop)

  3. **What's shared in `base_agent.py` regardless of agent:**
     - The 5-step loop and "repeat until done, blocked, or limit" logic (ADR-5)
     - Token budget & compaction (ADR-5 / B-2026-07-26-2)
     - Streaming interface back to the frontend
     - Permission checking (the upgraded safety_gate from ADR-5)
     - Hard iteration cap + wall-clock cap (ADR-5 / B-2026-07-26-1)

  4. **Direct Mode vs Agent Mode becomes a selection, not a code path.** Direct Mode = `direct_agent.py` (thin wrapper, no tools or tools auto-denied). Agent Mode = user picks from `{coding, research, browser, ...}` via a UI picker. The existing toggle in `backend/src/core/model_router.py` / the engine pipeline becomes a registry lookup, not an if/else buried in a chat handler.

  5. **Explicit user selection over LLM-based router.** Given the gemma3:1b-class target hardware, an extra classification call before the real agent starts is expensive (burns a full model call) and a wrong classification wastes the whole turn. A UI picker is cheaper and more reliable. A future LLM-based router is NOT forbidden — it's deferred until hardware improves or a future model makes it cheap enough.

  6. **Tool descriptions are the real design risk.** The user identified this in the option-2 exploration and it carries over: even with a scoped toolset per agent, a 1B-class model needs the tool schema itself to pre-disambiguate. Tool descriptions must be concrete enough that the model rarely picks wrong. This is an implementation-time concern, not an architectural one — but it's the most likely failure mode and should be tested early.

- **Consequences:**
  - **Refines ADR-5, does not supersede it.** ADR-5 defines the loop shape (the what); ADR-6 defines the organizational structure (the how-many). Both apply: every agent implements the ADR-5 closed-loop, and there are multiple specialized agents per ADR-6.
  - The `backend/src/core/agent/` → `backend/agents/base_agent.py` migration is the single biggest piece of implementation work. The 2926-line `loop.py` monolith decomposes into `base_agent.py` (the shared loop + caps + compaction) plus per-agent subclasses. This is multi-session work.
  - The flat `backend/src/tools/` bag gets redistributed into per-agent `tools/` subdirectories. Tools shared across agents (e.g., `memory_tool.py`) stay at a shared level or get duplicated per agent — decision deferred to implementation.
  - The existing `backend/src/tools/browser_agent.py` is already a "browser agent" in name but is currently structured as a tool, not a full agent. Promoting it to a full agent (per the structure above) is a natural first concrete step — it's already domain-scoped.
  - `direct_agent.py` replaces the current Direct Mode code path. The existing dual-mode logic in `backend/src/core/engine/_pipeline.py` and `backend/src/core/model_router.py` simplifies to a registry lookup.
  - The intent router (`backend/src/core/model_router.py`) becomes a thin layer that either (a) reads the user's UI selection and looks up `registry.py`, or (b) in a future session, makes an LLM-based classification call. Not both — pick one per session.
  - Future agents (`automation_agent.py`, `notes_agent.py`) fit cleanly: subclass `base_agent.py`, supply context_builder + tools + is_done(), register in `registry.py`. No existing agent needs to change.
  - **The `agent-loop-closed-loop` feature scope expands.** Originally (Session 13) it was "implement ADR-5 — the closed-loop wiring." Now it's "implement ADR-5 + ADR-6 — the closed-loop wiring AND the multi-agent restructure." The feature name still fits (the closed-loop is still the core concept); the manifest is updated to reflect the expanded scope.

- **Supersedes:** none. **Refines:** ADR-5 (specifies the organizational structure ADR-5 left open). **Builds on:** ADR-4 (`.context/` is the agent memory system).

---
## ADR-7: LocalMind persistent learning + workflow constraints (the .context/ system) (2026-07-27)

- **Author:** Super Z / GLM-5.2 (Session 28)
- **Status:** accepted (architectural target — implementation multi-session)
- **Context:** Sessions 21–27 fixed a series of bugs that all traced back to the same root cause: LocalMind's pipeline is single-shot — classify once, pick one tool, generate once, done. There's no persistent learning across sessions, no task plan that survives a single turn, no workflow constraints that tell the agent what "done" looks like. The user observed: "it works as if it doesn't have memory and its frustrating, like a child that can't think."

  The user's insight: they already solved this problem for their own coding workflow via the `.context/` system (this very protocol). The `.context/memory/` structure — `tasks/current.md`, `agents/sessions.md`, `user/preferences.md`, `system/environments.md`, `plans/decisions.md`, `flaws/log.md` — isn't just task files. It's **persistent learning infrastructure**: the system knows what it's working on, what it's learned about the user, what went wrong before, and what it decided. Every session reads it at startup and writes to it at exit. The agent doesn't follow a script — it knows the goal, knows what's true, and figures out HOW on its own.

  The user's design principles (stated explicitly):
  1. **`.context/` is for learning about the system, user, ai-agents, codebase — and learning from it.** Not just task tracking.
  2. **`.context/` doesn't restrain the agent from creativity.** The agent knows what it needs to do next but has to figure out on its own how to achieve that goal.
  3. **Workflows define constraints and checkpoints, NOT procedures.** A workflow tells the agent what "done" looks like and what it must not violate — NOT which exact tool calls to make. If a workflow reads like a fixed sequence of tool calls, it recreates the rigid single-shot pipeline problem one layer up.
  4. **`.context/` must be WRITTEN TO, not just read.** Every workflow needs a step at the end: "what did we learn here that belongs in `.context/`?" If LocalMind hits the same wrong-tool or same-question-forgotten failure twice, `.context/` isn't being written to or consulted.
  5. **The directory is extensible, not fixed.** New workflow files get added as new request patterns emerge — same as `.context/` grew organically over sessions rather than being scoped upfront.

- **Decision:** Build a two-layer system for LocalMind:

  **Layer 1: `backend/data/.context/` — persistent learning (read AND write)**

  ```text
  backend/data/.context/
  ├── system/
  │   ├── environment.md     # hardware, OS, installed tools, constraints (durable version of sysinfo)
  │   └── models.md          # which models are available, their strengths/weaknesses
  ├── user/
  │   ├── identity.md        # who the user is (name, role, timezone)
  │   └── preferences.md     # communication style, recurring projects, patterns
  ├── agents/
  │   └── capabilities.md    # what each agent can do, past successes/failures
  ├── codebase/
  │   ├── architecture.md    # how LocalMind is structured (this ADR, ADR-5, ADR-6)
  │   └── known_bugs.md      # bugs found and fixed (Session 21-27 findings)
  ├── memory/
  │   ├── sessions.md        # append-only log of what happened each session
  │   └── facts.md           # accumulated user facts (the learning output)
  └── flaws/
      └── log.md             # what went wrong + what was learned (the feedback loop)
  ```

  **Layer 2: `backend/data/workflows/` — constraint-style workflow files**

  ```text
  backend/data/workflows/
  ├── general.md             # default — "understand the request, act, verify"
  ├── research.md            # multi-source lookups (search → dedupe → synthesize)
  ├── coding.md              # file edits, running commands, verifying changes
  ├── error_recovery.md      # retry once, degrade to partial, or surface error
  ├── clarification.md       # ask a follow-up when intent is ambiguous
  ├── memory_update.md       # when and how to write new facts to .context/
  └── system_task.md         # OS-level actions where safety/confirmation matters
  ```

  **Design rules for workflow files** (the critical part):

  1. **Define "done", not "how".** A workflow says what the final output must look like and what constraints must be satisfied — NOT which tools to call in what order. Example: `research.md` says "the final output must be a real synthesis from multiple sources, and raw search results must be chunked/summarized before feeding to Generate if they exceed the context budget." It does NOT say "step 1: call web_search, step 2: call synthesis_tool."

  2. **Define checkpoints, not scripts.** A workflow says "verify before marking done" — e.g., "don't mark a step done until its output actually satisfies what it was for." The agent decides HOW to verify.

  3. **Every workflow ends with a learning step.** "What did we learn here that belongs in `.context/`?" This is the write-back that makes the system learn across sessions. If a workflow doesn't have this, it's static — not learning.

  4. **The agent has creative autonomy.** The workflow provides boundaries and knowledge. The actual path from "here" to "goal achieved" is the agent's own reasoning — same as how the `.context/` sessions in this project discovered steps as they went, each informed by the previous one.

  **The test for whether a workflow is written right:** does it tell the agent what "done" looks like and what it must not violate, without telling it which exact actions to take to get there? If yes, it's a constraint. If no (it reads like a fixed sequence of tool calls), it's recreating the rigid pipeline problem.

- **Consequences:**
  - This is a multi-session architectural milestone. Layer 1 (`.context/` structure) and Layer 2 (`workflows/` files) are created in this session as scaffolding. The engine wiring (reading `.context/` at startup, writing to it at session end, consulting workflows before acting) is future sessions.
  - The `workflows/` files are constraint-style from day one — NOT procedural scripts. This is the key design decision that prevents recreating the rigid pipeline one layer up.
  - The `.context/` structure mirrors the project's own `.context/memory/` but is adapted for LocalMind's runtime (learning about the user's machine, the user's preferences, the codebase LocalMind is working on — not about LocalMind's own development).
  - Every workflow's learning step feeds back into `.context/`. This is the feedback loop: workflow runs → agent learns → `.context/` updated → next session reads it → agent is smarter. If LocalMind hits the same failure twice, the loop is broken.
  - The `general.md` workflow is the fallback for anything that doesn't match a defined pattern. New workflows get authored as they're discovered to be needed — same organic growth as the project's `.context/`.

- **Supersedes:** none. **Builds on:** ADR-4 (`.context/` is the agent memory system), ADR-5 (closed-loop), ADR-6 (multi-agent). **Extends:** the todo plan system (Session 27) — workflows define what the plan should look like, the engine emits it as todos, the agent executes with creative autonomy.


---

## ADR-8: Agent-centric routing (tasks → agents → tools, not tasks → tools → agents)

**Date:** 2026-07-27 (Session 33 — proposed, NOT yet implemented)
**Status:** proposed
**Author:** Super Z / GLM-5.2 (architectural insight from user)

### Context

The current architecture is **tool-centric** at the classification layer:

```
User message → Intent classifier → TOOL (SHELL / FILE_WRITE / WEB_SEARCH / ...)
            → select_agent(intent) → agent whose toolset includes that tool
            → AgentLoop with scoped tools → model picks tools
```

"Create hello world repo in C:\Users\tison\...\ProjectPhill" gets classified as `SHELL` (because it involves shell commands), then the CodingAgent is selected because its toolset includes `shell`. But the task ALSO needs `file_write` (creating hello.py) and `git` operations — the classification picked ONE tool, and the agent was downstream of that pick.

The user identified the core problem: **"we are directing tasks to tools instead of agents! The agents are the ones who are supposed to use the tools."**

Three concrete symptoms of this mismatch:
1. **The CodingAgent is selected but hollow.** `BaseAgent.run()` delegates directly to `AgentLoop.run()` and never calls `self.build_context()`. The `coding.md` workflow (read-before-write, verify-after-write, follow-conventions) sits on disk unused. The CodingAgent's only effect is passing a scoped toolset.
2. **The sub-agent framework exists but is a parallel system.** `core/agent/sub_agent.py` has its own agent types (CODER, RESEARCHER, WRITER, OPERATOR, ANALYST), its own registry, its own execution path — completely decoupled from the `BaseAgent` subclasses. Two agent registries that don't share agents, workflows, or context.
3. **Multi-tool tasks get reduced to one tool.** "Create hello world repo" needs shell + file_write + git. Classifying it as "SHELL" is arbitrary. Under tool-centric routing, the agent loop has to figure out it also needs file_write — which works, but the workflow guidance (`coding.md`) that would structure that multi-tool reasoning never reaches the model.

### Decision

**Route tasks to agents, not tools.** Agents own their tools; the agent's workflow governs HOW it uses them. Agents are self-contained packages (directories), not single modules.

```
User message → Task classifier → TASK TYPE (coding / research / browse / chat)
            → Agent for that task type (agents/coding/, agents/research/, ...)
            → Agent loads its workflow (agents/coding/workflow.md)
            → Agent decides which of its tools to use, in what order, with what verification
            → If the task needs another domain → agent triggers another agent (parallel or handoff)
```

Five principles:

1. **Classification by task type, not tool.** "Create hello world repo" is a *coding* task → CodingAgent. The CodingAgent owns shell + file_write + file_edit + code_exec + file_task — it decides which to use based on its workflow.

2. **Agents own tools; tools don't own agents.** The intent router no longer picks a tool and then finds the agent that has it. The task type picks the agent, and the agent's toolset is part of its identity.

3. **Agents collaborate.** A coding task needing research doesn't get re-classified as "web_search" (losing the coding context). The CodingAgent delegates to the ResearchAgent — either parallel (both work simultaneously) or handoff (ResearchAgent returns results, CodingAgent continues). This replaces the current `should_use_sub_agents()` keyword heuristic with agent-initiated delegation.

4. **The workflow is the value.** The coding workflow's "read-before-write, verify-after-write, follow-conventions, small-verifiable-changes" is what guides the agent's tool use — not just having 5 tools vs 10. The workflow files (`coding.md`, `research.md`, `safety.md`, etc.) are loaded into the agent's system prompt and govern its behavior.

5. **Agents are directories, not modules.** Each agent is a self-contained package — a directory co-locating everything that defines the agent. This makes agents robust (rich, extensible, testable) instead of limited to what fits in a single class file. A single-file agent (`coding_agent.py`) can hold a class definition but can't co-locate its workflow, context builder, scoped tools, tests, and persona docs. A directory-based agent (`agents/coding/`) holds all of that as a unified unit.

### Agent directory structure (Principle 5 in detail)

Each agent lives in its own directory under `backend/src/agents/<name>/`:

```
agents/coding/
├── __init__.py          # exports CodingAgent (the class, re-exported from agent.py)
├── agent.py             # the BaseAgent subclass (CodingAgent) — config(), description()
├── workflow.md          # the constraint-style workflow (was backend/data/workflows/coding.md)
├── context_builder.py   # build_coding_context() — loads workflow.md + gathers context
├── tools.py             # CODING_TOOLS frozenset — the agent's scoped toolset
├── is_done.py           # is_coding_done() — the agent's stop condition
├── persona.md           # the agent's persona/expertise framing (was inline in prompts.py)
└── tests/
    ├── __init__.py
    ├── test_context.py  # tests for build_coding_context()
    ├── test_workflow.py # tests that workflow.md is loaded + injected
    └── test_is_done.py  # tests for the stop condition
```

**Why directories, not modules:**

- **Co-location.** Everything that defines the coding agent is in one place. To understand the coding agent, you read one directory — not `coding_agent.py` + `coding/context_builder.py` + `coding/tools.py` + `coding/is_done.py` + `data/workflows/coding.md` + the persona section of `prompts.py`. Today these are scattered across 4+ locations.
- **Extensibility.** A directory can grow. Want to add a `examples/` subfolder with sample coding tasks? Add a `verifier.py` for agent-specific verification logic? Add a `README.md` documenting the agent's design? A directory makes this natural; a single file forces everything into class methods or external files.
- **Testability.** Tests live next to the code they test. `agents/coding/tests/test_workflow.py` verifies the coding workflow is loaded and injected — co-located with the workflow it tests.
- **Discoverability.** `ls agents/` shows you every agent in the system. Each is a directory. Adding a new agent = adding a new directory. No registry editing, no imports to wire — the registry auto-discovers directories (Phase 1 implementation detail).
- **Robustness.** A single-file agent is fragile — it can only hold a class. A directory-based agent is robust — it holds a class + workflow + context + tools + tests + persona + examples. This is the difference between "a class that happens to be called an agent" and "a real agent package."

**Current state (pre-ADR-8):** The directory structure partially exists — `agents/coding/`, `agents/research/`, `agents/browser/`, `agents/direct/` each have `context_builder.py`, `is_done.py`, `tools.py`, `__init__.py`. BUT:
- The agent CLASSES (`CodingAgent`, `ResearchAgent`, etc.) are single files OUTSIDE their directories: `coding_agent.py`, `research_agent.py`, etc. They should be INSIDE: `agents/coding/agent.py`.
- The workflow files (`coding.md`, `research.md`) are in `backend/data/workflows/` — a separate location. They should be INSIDE the agent directory: `agents/coding/workflow.md`.
- The personas are inline in `prompts.py` (`_PERSONA_MAP`). They should be `agents/coding/persona.md`.
- The SubAgentType agents (CODER, RESEARCHER, WRITER, OPERATOR, ANALYST) in `sub_agent.py` are dataclass instances in a single file — no directory at all. They should be `agents/coder/`, `agents/researcher/`, etc. (or merged into the existing agents per Phase 1).
- There are no per-agent tests co-located with the agents.

### Implementation phases (multi-session)

**Phase 1: Agents as directories (structural foundation).** Convert each agent from a single-file module to a self-contained directory package. Move the agent class into `agents/<name>/agent.py`, move the workflow file into `agents/<name>/workflow.md`, move the persona into `agents/<name>/persona.md`. The `__init__.py` re-exports the class for backward compatibility. The registry auto-discovers agent directories (any directory under `agents/` with an `agent.py` is an agent). This is the foundation — it makes the agents robust enough to hold the workflows and delegation logic that Phases 2-4 add. Without this, Phase 2 (wire build_context) has nowhere to co-locate the workflow files.

**Phase 2: Wire `build_context()` into `BaseAgent.run()`.** When an agent runs, it calls `build_context()` to gather its task-specific context — INCLUDING loading its workflow file (`agents/coding/workflow.md`, `agents/research/workflow.md`, etc.). The context is passed through to `build_agent_system_prompt()` and injected as a section. This is the fix backlogged in Session 33: the workflow files finally reach the model. (Depends on Phase 1 — the workflow files need to be co-located with the agent for `build_context()` to find them.)

**Phase 3: Agent-initiated delegation.** Replace the `should_use_sub_agents()` keyword heuristic with agent-initiated delegation. The CodingAgent's workflow + system prompt includes the ability to say "I need research on X" → the framework spawns a ResearchAgent sub-task → results flow back → CodingAgent continues. This is the "agents can trigger other agents to work parallelly or hand over" the user described. (Depends on Phase 1 — delegation needs the unified agent directory structure to spawn sub-agents by name.)

**Phase 4: Task-type classifier.** Replace (or augment) the intent classifier with a task-type classifier. "Create hello world repo" → task_type=coding (not intent=SHELL). The task type selects the agent; the agent's workflow governs tool use. Intent classification can still exist as a signal the agent uses, but it's no longer the routing key. (Depends on Phases 1-2 — the classifier needs real agents with real workflows to route to.)

### Consequences

- **This is a multi-session architectural milestone.** Phases 1-4 span multiple sessions. Phase 1 (agents as directories) is the structural foundation; Phase 2 (wire build_context) is the highest-leverage piece — it makes the workflow files actually reach the model. Phases 3-4 are the full agent-centric vision.
- **Agents become real packages, not classes.** The shift from `coding_agent.py` (single file) to `agents/coding/` (directory) is structural — each agent co-locates its class, workflow, context builder, tools, stop condition, persona, and tests. This makes agents robust (extensible, testable, discoverable) instead of fragile (limited to what fits in one file).
- **The workflow files become load-bearing AND co-located.** `agents/coding/workflow.md`, `agents/research/workflow.md`, etc. — these are no longer documentation in a separate `data/workflows/` directory; they're part of the agent package, loaded into the system prompt. They must be well-written (constraint-style, not procedural — per ADR-7).
- **The intent classifier becomes a signal, not a router.** Intent (SHELL, FILE_WRITE, etc.) is still useful for the agent to know what kind of tool the user expects — but it's no longer the routing key. Task type (coding/research/browse/chat) is the router.
- **Agent-to-agent delegation is the new capability.** This is the biggest unlock: a coding task that needs research no longer requires the user to break it into two messages, and no longer requires the system to re-classify (losing context). The CodingAgent just delegates.
- **The registry becomes auto-discovering.** Instead of manually registering agents in `__init__.py`, the registry scans `agents/` for directories with an `agent.py` file. Adding a new agent = adding a new directory. This is the discoverability benefit of the directory structure.
- **Per the flaw log: every phase needs real-model testing before shipping.** This ADR is proposed, not implemented. No code changes this session.

### Supersedes / builds on

- **Builds on:** ADR-6 (multi-agent — this is the completion of ADR-6's vision; the BaseAgent subclasses become real agents with workflows, not hollow shells)
- **Builds on:** ADR-7 (`.context/` system + workflows — the workflow files become load-bearing)
- **Supersedes:** the `should_use_sub_agents()` keyword heuristic (Phase 3 replaces it with agent-initiated delegation)
- **Does NOT supersede:** ADR-5 (closed-loop) — the 5-step loop shape stays; agents just get richer context and delegation ability

### Open questions

1. **Does the task-type classifier need an LLM call, or can it be keyword-based?** An LLM call adds latency; keyword-based is less accurate. Probably LLM-based but cached per-session (task type rarely changes mid-conversation).
2. **How does agent-to-agent delegation handle streaming?** If the CodingAgent delegates to the ResearchAgent mid-stream, does the user see the ResearchAgent's work? Probably yes (in a sub-panel), but this is a UX decision.
3. **What happens to the intent classifier?** It becomes a signal the agent uses ("the user mentioned shell commands, so shell is likely involved") rather than the router. Or it could be removed entirely if the task-type classifier is good enough. TBD.

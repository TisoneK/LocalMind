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

---

## ADR-9: Add ZenMux provider (unified API gateway with free models + insurance)

**Date:** 2026-07-27 (Session 33 — Steps 1-4 implemented, Step 5 smoke test still BLOCKED)
**Status:** implemented but untested (config code shipped; API smoke test blocked by plan limitation)
**Author:** Super Z / GLM-5.2 (feature request from user + web research)

### Smoke test result (Session 33)

**BLOCKED.** Ran the real-API smoke test per ADR-9 Step 5 (and per the flaw log: don't ship provider/adapter changes without testing). Findings:

- **Key is valid.** `GET /api/v1/models` returns 200 with 145 models (Claude, GPT, Gemini, Grok, DeepSeek, GLM, Kimi, MiniMax, etc.).
- **All chat completions return 403.** `POST /api/v1/chat/completions` returns `{"error":{"code":"403","type":"access_denied","message":"You have no permission to access this resource"}}` for every model tested (8 models across 6 providers).
- **Root cause:** The user is on ZenMux's free plan ("5 Flows/5h, $0"), which explicitly states **"Studio Chat only"** and **"No API Request access."** The `/models` endpoint isn't gated (listing models is free), but `/chat/completions` requires a paid plan. The free Builder tier mentioned in the web research does NOT include API access — it's Studio Chat only.
- **Steps 1-4 implemented anyway (config-only).** User explicitly asked to implement. The integration is config-only (ProviderConfig + env var + context windows + frontend wiring) — no new adapter logic. The adapter code that handles OpenAI-compatible providers already exists and is tested (Zen, Chutes, Z.ai). Risk of config-only change is lower than adapter logic changes. All code is marked "IMPLEMENTED BUT UNTESTED" with explicit comments. When the user upgrades to a paid plan, they run the smoke test (Step 5); if it fails, we fix the adapter THEN — with a working key, not blind.

**To unblock the smoke test:** the user needs to upgrade to a ZenMux plan that includes API access. Per ZenMux's pricing: Pro ($20/mo), Max ($100/mo), or Ultra ($400/mo). Once the account can make API calls, re-run the smoke test (Step 5 below); if it passes, mark ADR-9 as "tested — done." If it fails (e.g., ZenMux has a quirk like DeepSeek's trailing-tool-role 400), fix the adapter with a working key.

### Context

User wants to add ZenMux (zenmux.ai) as a new LLM provider. ZenMux is a unified API gateway aggregating 100+ AI models (Claude, GPT, Gemini, DeepSeek, Grok, etc.) with a single API key. It's OpenAI-SDK compatible — same protocol shape as the existing Zen, Chutes, and Z.ai providers — so it should slot into LocalMind's existing `OpenAICompatAdapter` as a drop-in.

**Why ZenMux is worth adding:**

1. **Free models available (on paid plans).** Grok 4.5, Claude Opus 4.6 promo, etc. rotate over time. NOTE: per the smoke test above, these "free models" require a paid subscription — the free plan has no API access at all.

2. ~~**Standing free tier.**~~ **REMOVED — see smoke test result.** The free Builder tier (~5 flows/5h) is Studio Chat only with no API access. Not usable for LocalMind integration.

3. **"Insurance" differentiator.** ZenMux's paid tiers (Pro $20/mo, Max $100/mo, Ultra $400/mo) automatically compensate you when you get hallucinated outputs, excessive latency, or low throughput. This is unique — no other provider LocalMind integrates offers this. For a local-first app where the user is paying per-token, the hallucination insurance is genuinely valuable.

4. **Model aggregation.** One API key covers 100+ models across providers. Instead of managing separate keys for OpenAI, Anthropic, Google, etc., the user manages one ZenMux key and gets access to all of them. Lower friction for the user.

5. **Pay-as-you-go per-token.** Model usage is billed per-token at model/provider-specific rates against a topped-up balance, separate from the subscription tiers.

**Integration specifics (from web research + smoke test):**
- **Base URL:** `https://zenmux.ai/api/v1`
- **Protocol:** OpenAI-SDK compatible (same as Zen, Chutes, Z.ai)
- **Model format:** `provider/model-name` (e.g. `google/gemini-3.6-flash`, `anthropic/claude-opus-5`, `x-ai/grok-4.5`) — NOTE: the actual format uses hyphens (`x-ai/`) not the web-researched `xai/`. Verified from the `/models` response.
- **Plan requirement:** A PAID plan (Pro/Max/Ultra) is required for API access. The free plan returns 403 on all chat completions. This must be documented in LocalMind's provider description so users don't waste time creating a free key that can't make calls.
- **Also supports:** OpenAI's Responses API on the same base URL (not needed for LocalMind's current adapter, but good to know)
- **Auth:** Bearer token in `Authorization` header (standard)

### Decision

**Add ZenMux as a new provider in the OpenAI-compat adapter.** This is a configuration addition, not an architectural change — ZenMux uses the same protocol as existing providers, so no new adapter code is needed. The work is: (1) add a `ProviderConfig` entry, (2) add an env var mapping, (3) add model context windows, (4) wire the frontend, (5) test against the real API.

### Implementation steps

**Step 1: Add `ProviderConfig` in `backend/src/adapters/openai_compat.py`**

Add to `PROVIDER_CONFIGS` (after the `zen` entry, since they're similar gateways):

```python
"zenmux": ProviderConfig(
    name="zenmux",
    display_name="ZenMux",
    base_url="https://zenmux.ai/api/v1",
    api_key=os.getenv("ZENMUX_API_KEY", ""),
    default_model="xai/grok-4.5",  # currently free per web research
    key_env="ZENMUX_API_KEY",
    model_env="ZENMUX_MODEL",
    settings_field="zenmux_model",
),
```

Note: model strings use `provider/model-name` format (e.g. `xai/grok-4.5`, `anthropic/claude-opus-4-6`, `google/gemini-3.1-pro-preview`). This is different from most providers (which use bare model names) but the adapter passes the model string through as-is, so no format conversion is needed.

**Step 2: Add env var mapping in `backend/src/core/config.py`**

Add to the `env_key_map` in `get_api_key()`:
```python
"zenmux": "ZENMUX_API_KEY",
```

**Step 3: Add model context windows in `backend/src/adapters/openai_compat.py`**

Add to `MODEL_CONTEXT_WINDOWS`:
```python
# ZenMux (aggregated models — use the underlying model's context window)
"xai/grok-4.5": 131072,
"anthropic/claude-opus-4-6": 200000,
"anthropic/claude-sonnet-4-6": 200000,
"google/gemini-3.1-pro-preview": 1048576,
"google/gemini-3.5-flash": 1048576,
"openai/gpt-5.5": 128000,
"deepseek/deepseek-v4-flash": 131072,
```

Note: ZenMux aggregates 100+ models — we can't add all of them. Add the most common ones + the currently-free ones. Unknown models fall back to the `"default": 32768` entry. The model list should be fetched live from `GET /api/v1/models` (same as Zen) — the Settings panel already does this for other providers.

**Step 4: Wire the frontend**

Add to `frontend/src/components/shared/SettingsModal.tsx` provider list:
```typescript
{ id: 'zenmux', name: 'ZenMux (free models + insurance)' },
```

The ModelSelector and model-fetching endpoint (`GET /api/models?provider=zenmux`) already work generically — they call the provider's `/models` endpoint and display the results. No new frontend code needed beyond the provider list entry.

**Step 5: REAL-API SMOKE TEST (per flaw log — DO NOT SKIP)**

Per the Session 31/33 flaw log: **do not ship provider/adapter changes without a real-API smoke test.** Before committing:

1. Get a ZenMux API key from the user (or sign up at zenmux.ai for the free tier).
2. Run a trivial test call against `https://zenmux.ai/api/v1/chat/completions` with model `xai/grok-4.5` (currently free):
   ```bash
   curl -s -H "Authorization: Bearer $ZENMUX_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"model":"xai/grok-4.5","messages":[{"role":"user","content":"Say hello"}],"stream":false}' \
        https://zenmux.ai/api/v1/chat/completions
   ```
3. Verify: (a) the API returns 200, (b) the response has the expected `choices[0].message.content` shape, (c) streaming works (`"stream":true` returns SSE chunks), (d) the `provider/model-name` format is accepted.
4. Test with the LocalMind adapter specifically: construct an `OpenAICompatAdapter(provider="zenmux")` and call `chat()` — verify it streams correctly and doesn't hit the trailing-tool-role 400 (Session 31's adapter fix should handle this, but verify).
5. If any of these fail, fix the adapter BEFORE shipping — don't ship a broken provider.

**Step 6: Test with a multi-step agent task**

After the smoke test passes, test a multi-step task (e.g. "Create hello world repo") against ZenMux to verify:
- The trailing-tool-role fix (Session 31) works with ZenMux's message format
- The Phase 1 reasoning-detection fix (Session 31) works if ZenMux models produce reasoning_content
- The iteration limit (Session 32) is sufficient
- No SSE stream races (Session 33's `drain()` fix holds)

### Consequences

- **New provider option for users.** ZenMux gives access to 100+ models with one API key, including currently-free models (Grok 4.5, Claude Opus 4.6 promo). This is especially valuable for users who want to try multiple models without managing multiple API keys.
- **No architectural change.** ZenMux uses the same OpenAI-compatible protocol as Zen, Chutes, Z.ai, etc. The existing `OpenAICompatAdapter` handles it. The work is configuration + frontend wiring + testing.
- **Model string format difference.** ZenMux uses `provider/model-name` (e.g. `xai/grok-4.5`) instead of bare model names. The adapter passes the model string through as-is, so no conversion is needed — but the `MODEL_CONTEXT_WINDOWS` registry needs entries with the `provider/` prefix.
- **Per the flaw log: the smoke test is mandatory.** Sessions 31-33 taught us that provider/adapter changes break in ways mocked tests can't catch (SSE races, message-format rejections, reasoning-stream handling). The real-API smoke test is Step 5, not an afterthought.
- **The free-model rotation is a feature.** ZenMux's free models change over time. The Settings panel fetches the live model list from `GET /api/models?provider=zenmux`, so the user always sees what's currently available — no hardcoded model list to maintain.

### Supersedes / builds on

- **Builds on:** the OpenAI-compat adapter pattern (shared across Zen, Chutes, Z.ai, OpenRouter, etc.)
- **Builds on:** Session 31's adapter fixes (trailing-tool-role synthetic user message, Phase 1 reasoning-only detection) — ZenMux will benefit from these automatically
- **Does NOT supersede:** any existing provider. ZenMux is an addition, not a replacement.
- **Does NOT supersede:** ADR-8 (agent-centric routing). This is a provider addition; ADR-8 is an architectural change to how tasks route to agents. They're independent.

### Open questions

1. **Which model should be the default?** `xai/grok-4.5` is currently free, but free models rotate. Should the default be a free model (changes over time) or a stable paid model (always available, costs tokens)? Probably default to the currently-free one and let the user change it.
2. **Does ZenMux support the `tools` parameter for function calling?** Most OpenAI-compatible providers do, but some don't. The smoke test (Step 5) should verify this — if ZenMux doesn't support `tools`, the adapter's MiniMax-style text-based tool-call detection would need to handle it.
3. **Does ZenMux return `reasoning_content` for reasoning models?** DeepSeek-v4-flash-free (via Zen) does, and the adapter handles it. ZenMux aggregates DeepSeek — does it pass through `reasoning_content`? The smoke test should verify this.
4. **Should LocalMind document the insurance feature?** The hallucination/latency/throughput insurance is a ZenMux differentiator, but it's between the user and ZenMux — LocalMind doesn't participate. Probably just a note in the provider description: "ZenMux offers hallucination insurance on paid tiers — see zenmux.ai for details."

---
## ADR-10: Expand LocalMind through capability families while preserving developer roles (2026-07-31)

- **Status:** accepted direction — implementation pending
- **Context:** LocalMind is intended to handle ordinary local tasks such as document processing, system awareness, browser/app interaction, productivity, and data work, while remaining valuable for software developers. The existing Coding, Debugger, Reviewer, Verifier, and Analyst agents are important developer workflows and must not be removed merely to add non-coding capabilities.
- **Decision:** Keep agents as reusable decision/workflow roles and tools as controlled execution primitives. Expand additively through capability families: knowledge/reasoning, local information, internet, computer interaction, productivity, data, and external-service connectors. Use the existing `Capability`, `TaskProfile`, `ExecutionGraph`, registry, delegation, and objective-runtime foundations. Treat `Observe → Think → Decide → Act → Observe → Verify` as the long-term desktop-assistant loop. Define capability-family and observation contracts before adding a broad new tool inventory.
- **Consequences:** Developer agents remain first-class and retain their scoped tools. New domain capabilities can be used by existing or future roles without creating dozens of narrow agents. `Observe` should begin as a structured, permission-aware snapshot contract and grow incrementally from existing system/browser/workspace signals. This decision is additive and does not supersede ADR-5, ADR-6, ADR-7, or ADR-8; it extends their closed-loop, multi-agent, learning, and agent-centric foundations.

---
## ADR-11: Deterministic conversational fast-path — skip the LLM capability-inference call for obvious chat queries (2026-08-09)

- **Author:** Buffy / deepseek-v4-flash (Session 67)
- **Status:** accepted direction — implementation pending (B-2026-08-09-1 / B-2026-08-09-6)
- **Context:** A reviewer conversation reported 39.9s latency for "What can you do?" and the user independently observed "Hi" taking >10s while the same model answers elsewhere in milliseconds. Code verification confirmed the cause: non-trivial conversational queries pay **two sequential LLM calls** — the ThinkingDispatcher's capability-inference call (large JSON-schema prompt, `DISPATCHER_TIMEOUT_SECS=30`, main model) followed by the actual chat-generation call (`context_builder` full prompt), with `maybe_compress_history()` a potential third call. The Session 21 trivial-input short-circuit (`trivial_input.py`) only covers greetings/thanks/farewells/yes-no/acks, so ordinary questions like "What can you do?" miss it. The engine already has a dispatcher-skip fast path (`client_intent` + `client_confidence >= 0.9`, `_pipeline.py` ~L951) and the client already sends `X-LocalMind-Intent`, but the header only fires on explicit UI tool buttons — nothing classifies plain messages.
- **Decision:** Extend deterministic pre-classification so obviously-conversational queries (interrogatives + no tool keywords, e.g. "What can you do?", "Who are you?", "How does this work?") short-circuit to a **single** chat LLM call, skipping the dispatcher entirely. Server-side first (extend `trivial_input.py` with a conservative "conversational question" category + tests); the existing client-intent header path is the follow-on for any messages the client can classify cheaply. Preserve the conservative rule from `trivial_input.py`: anything ambiguous falls through to the full dispatcher (misrouting protection — "What is today's EPL games?" must still route to WEB_SEARCH).
- **Consequences:** Conversational turns drop to one LLM call (est. saving the dispatcher round-trip, ~10-20s on slow free tiers). Routing accuracy must not regress — the new category is regex-anchored to interrogative+no-tool-keyword inputs only, and the existing capability-correction logic (realtime_sensitive → WEB_SEARCH) stays. `DISPATCHER_HIGH_CONFIDENCE_SKIP` remains agent-intent-only; it does not cover this path. Per the Session 31/33 flaw-log rule, ship only after a real-model test against deepseek-v4-flash-free.

---
## ADR-12: Truthful per-stage observability — backend-emitted stage timings replace frontend heuristics (2026-08-09)

- **Author:** Buffy / deepseek-v4-flash (Session 67)
- **Status:** accepted direction — implementation pending (B-2026-08-09-2 / B-2026-08-09-5)
- **Context:** The Observe panel's five pipeline steps ("Intent Classify → Context Build → Tool Select → Generate → Execute") are a frontend heuristic inferred from observation fields, not real stages — verified: on a completed no-tool turn, "Tool Select" stays orange/running forever and "Execute" shows done with no tools. The backend already times individual phases (`dispatcher_complete.latency_ms`, `memory_retrieved.latency_ms`, `turn_complete.total_latency_ms`) but never aggregates or surfaces them. The trivial-input path emits **no** `turn_complete` at all, and the `/api/observability` fallback is session-agnostic (shows another session's aggregate). Net result: the fastest turns show the least/wrong data, and nobody can see where a 39.9s turn went without server logs.
- **Decision:** Emit a structured `stage_timing` observation per turn (ordered list of `{stage, duration_ms}` — trivial-check, dispatcher, memory, context-build, generate, tool-exec) on every completion path including the trivial short-circuit; render it as a collapsed per-stage breakdown in the Observe panel, replacing the invented stage list. Make the observability fallback per-session. Where a stage legitimately did not run (no tool on a chat turn), the UI must show "skipped", not "running".
- **Consequences:** The Observe panel becomes a real diagnostic (the reviewer's "which stage ate the 10s+" question becomes answerable in-UI). This builds on ADR-11 (the fast path makes the stage list shorter for chat turns) and on Sessions 63-65 telemetry. It does not supersede ADR-8; per-stage timings feed ADR-8's closed-loop observability. The `toolsUsed` staleness bug (empty `tools_used` keeps the previous turn's tools) must be fixed in the same pass.

---
## ADR-13: Per-message performance metadata in the chat transcript (2026-08-09)

- **Author:** Buffy / deepseek-v4-flash (Session 67)
- **Status:** accepted direction — implementation pending (B-2026-08-09-3 / B-2026-08-09-4 / B-2026-08-09-8)
- **Context:** Latency and token figures exist only in the session-global Observe panel / bottom bar (last turn only, no history), and the two surfaces disagree: the bottom bar formats adaptive s/ms correctly while the Observe panel shows raw unlabeled ms (e.g. `39853`) with a hardcoded `max=10000`. The bottom bar already splits prompt/completion (Sessions 64-65 wired backend telemetry), but prompt tokens only populate at turn_complete, and "Vector Store Hits" is mislabeled (it displays the memory-facts count). A reviewer asked for per-turn latency attached to each chat head, split prompt/completion tokens, and consistent units.
- **Decision:** Add optional per-message performance metadata to assistant messages (latency, prompt/completion tokens, optional per-stage breakdown from ADR-12), populated at turn completion; display a small muted line/chip under each assistant reply (latency + split tokens), consistent with the existing timestamp style; apply one shared latency formatter everywhere (sub-second → ms, ≥1s → one-decimal s). Rename "Vector Store Hits" to "Memory Facts" and render "—" only when a session truly has no observation (0 is a valid number). Keep the bottom bar as the global live summary.
- **Consequences:** Each turn becomes self-diagnosing in the transcript itself; slow turns are visually attributable without the Observe panel open. Requires extending the `ChatMessage` type + SSE/persistence contract (best-effort — old messages without metrics render as today). Depends on ADR-12 for the per-stage breakdown variant; independent of ADR-11.

---
## ADR-14: Single front door + thin routing dispatcher — the dispatcher never runs the full pipeline itself (2026-08-09)

- **Author:** Buffy / deepseek-v4-flash (Session 95, per user's architecture thread — source: `/Users/bao/Desktop/Buffy - LocalMind Chat.txt`)
- **Status:** accepted direction — architectural target (implementation pending; supersedes the "dispatcher runs the full pipeline" shape for new work)
- **Context:** The user's thread with a reviewer/architect agent established a target architecture grounded in Codebuff/Freebuff's real production system (verified by web research in the thread: Buffy is the orchestrator on Claude Opus 4.7; sub-agent roster is base/editor/reviewer/thinker/researcher/file-picker/basher/code-searcher; per-agent model routing is SHIPPED — Opus 4.7 for orchestrator, Gemini 3.1 Flash Lite for several sub-agents, MiniMax M3 in Lite mode; sub-agents contribute only their FINAL OUTPUT to the orchestrator's context, never full message history). Key confirmed facts:
  1. **User ↔ dispatcher is the ONLY external interface.** The user talks to one agent (Buffy/dispatcher). Every sub-agent (basher, etc.) exists purely as the main agent's internal delegation target — no user-facing entry point. "It only receives orders from Buffy not the user."
  2. **The dispatcher must be a thin front door, not a full pipeline pass.** Its job: acknowledge → classify intent (cheap: structured output / function-calling, not full prose reasoning) → decide the route → kick it off. Running the dispatcher through Context Build + Tool Select + Generate on its own account is the redundancy behind the 40s latency on "Hi" / "What can you do?" (the thread explicitly identified this as the likely cause; ADR-11/12 confirmed the two-LLM-call bottleneck for chat queries and the missing per-stage truth).
  3. **Routing fan-out:** trivial/conversational → straight to Generate (skip everything); needs a tool → Tool Select → Execute → Generate; needs a sub-agent → delegate, get structured JSON back, then Generate; needs multi-step work → hand off to the objective/agentic loop (ADR-16).
  4. **Cheap work should run on cheap paths.** Per-agent model routing (B-2026-08-02-10, shipped Session 85) and the conversational fast-path (ADR-11, shipped Sessions 68-71) are the first two realizations of this principle.
- **Decision:** Adopt the single-front-door + thin-dispatcher shape as LocalMind's routing target: one user-facing entry (the engine's chat pipeline is the front door); the dispatcher/classifier is a cheap, fast routing step that invokes ONLY the heavier stages the input actually needs — never a full unconditional pass. Sub-agents remain internal delegation targets (already the case for `delegate`/`delegate_parallel`/`delegate_inline`); extend them only as internal routing targets, never as user-facing entry points.
- **Consequences:**
  - New routing work must be built as short-circuit decisions, not more unconditional pipeline stages. Measure each stage's cost with ADR-12 stage timings before adding stages.
  - The dispatcher's own "thinking" should be structured/constrained output (or a heuristic fast path per ADR-11), not full prose reasoning — this is the difference between a router and a second conversational turn.
  - Does NOT supersede ADR-11 (conversational fast-path — this generalizes its principle to ALL routing) or ADR-8 (agent-centric routing — agents still own tools; the dispatcher routes to agents/tools/loops). Builds on ADR-5/6 (closed-loop + multi-agent) — the dispatcher is the front of the closed loop, not a new loop.

---
## ADR-15: Sub-agent contract — bounded instruction in, fixed structured result out; general + specific sub-agents; three-tier tool model (2026-08-09)

- **Author:** Buffy / deepseek-v4-flash (Session 95, per user's architecture thread)
- **Status:** accepted direction — architectural target (implementation incremental)
- **Context:** The thread clarified how Codebuff/Freebuff's sub-agents actually work, which is the template LocalMind's delegation should follow:
  1. **General vs specific sub-agents.** A *general* sub-agent is a broad worker scoped per-call by whatever instruction the dispatcher passes (covers the long tail: "read this and summarize", "run this", "search for X"). A *specific* sub-agent is purpose-built for one recurring job with its own tuned prompt, tool access, and FIXED output schema (code-review → `{issues:[], severity}`, test-runner → `{passed,failed,output}`, git-ops → git-only). Specific sub-agents are more reliable and faster for their one job because the output shape is fixed, not inferred per call. **The dispatcher's routing job: cheap classification — does this sub-task match a specific sub-agent, else fall through to the general one.** Add specific sub-agents INCREMENTALLY as recurring task types appear — never enumerate them all up front.
  2. **Bounded instruction in, fixed structured result out.** Sub-agents receive explicit instructions: exactly what to do, what NOT to do, and exactly what shape to return. Reasoning lives in the main agent (Buffy) — the sub-agent executes against a spec, it does not reason from context. "Never 'figure out what to do' — always 'do exactly this, return exactly that'."
  3. **Final-output-only context.** Sub-agents contribute only their final output to the orchestrator's context — never full message histories. This is why the orchestrator stays fast while coordinating many sub-agents (verified in Codebuff's design docs).
  4. **Three-tier tool model** (refines the tool-vs-subagent question):
     - **Raw tool** — mechanical, no interpretation (read a file, list a directory) → plain function call.
     - **Tool-acting-as-subagent** — bounded interpretation within a scope, fixed structured return (basher = terminal execution; Greptile/code-searcher = semantic code Q&A). Given a scoped instruction, does its own bounded work, returns a clean result.
     - **Inline-only, stays with the main agent** — needs full accumulated context + open reasoning (file WRITING: deciding what the change should be is itself the reasoning task). Writing stays inline because it's reasoning-heavy + context-heavy; basher stays a sub-agent because it's execution-light + context-light.
  5. **Two-factor test** for tool-vs-subagent: context-heavy + reasoning-heavy → inline with the main agent's thinking block; context-light + execution-only → sub-agent candidate (cheap model, no thinking block).
- **Decision:** LocalMind's delegation follows this contract: (a) existing `delegate`/`delegate_parallel`/`delegate_inline` are the general sub-agent mechanism — keep them as the catch-all; (b) add SPECIFIC sub-agents incrementally (fixed output schemas) as recurring task types appear — first candidates: code-review (`{issues, severity}`), test-runner (`{passed, failed, output}`), git-ops; (c) route to specific-first, general-fallback; (d) verify/keep final-output-only context (do not let sub-agent message histories bloat the parent prompt); (e) keep file WRITING inline (it is the reasoning task) — do not delegate it.
- **Consequences:**
  - Future delegation work must respect the bounded-instruction contract: every sub-agent call gets explicit do/don't/return-shape instruction; results are structured and consumed without re-interpreting prose.
  - New "tools" that do bounded interpretation (search, fetch-and-answer) should follow the tool-acting-as-subagent tier: scoped instruction in, structured result out — not raw-data dumps.
  - Does NOT supersede ADR-14 (dispatcher routing — this specifies the sub-agent side of the routes). Builds on ADR-6/8 (multi-agent + agent-centric routing). The per-agent model routing (B-2026-08-02-10) is the enabler for the "cheap model for specific sub-agents" half.

---
## ADR-16: Two workflows — general single-pass vs specific objective-driven loop, as distinct entry points (2026-08-09)

- **Author:** Buffy / deepseek-v4-flash (Session 95, per user's architecture thread)
- **Status:** accepted direction — architectural target (implementation pending; the objective loop is the biggest open build)
- **Context:** The thread drew a critical distinction for LocalMind's redesign:
  1. **General workflow** — the default always-on path for ordinary conversation and single-shot tool use: Intent Classify → Context Build → Tool Select → Generate → Execute, one pass, no persistent objective. "What's my disk space?" / "summarize this file" — one turn, one or zero tool calls, done. This is what LocalMind already has, and it must stay FAST and CHEAP (the current latency work).
  2. **Specific task workflow** — triggered when the user (or system) defines an objective rather than a single query: "refactor this module, run the tests, fix what breaks". This needs a LOOP that is currently missing: plan a sequence of steps, execute one, observe the result, decide the next step or stop, possibly spawn sub-agents, and report back only when the objective is done or blocked. **LocalMind's "Autonomous Work" panel is clearly meant for this ("click + to start an objective") but isn't wired to anything.**
  3. **They should NOT be the same code path with an if-statement bolted on.** A shared toolkit (tool-execution functions, context building) that both paths call into, but TWO DISTINCT entry points/orchestrators: one for the fast single-pass conversational flow, one for the looping objective-driven flow. The user opted into the heavy path by starting an objective — it can be slow; the general path must not pay for it.
- **Decision:** Treat general (single-pass) and specific-task (objective loop) as two distinct orchestrators sharing the tool/context toolkit — NOT as one linear pipeline with a mode flag. The objective loop is the target for the "Autonomous Work" panel: plan → execute → observe → decide next/stop → report when done or blocked (possibly spawning sub-agents per ADR-15).
- **Consequences:**
  - The general path stays lean — no loop machinery, no objective persistence. The specific-task loop is built separately (see B-2026-08-09-13) and wires the existing objective/todo machinery (`objective_runtime.py`, todo plan emission) to the Autonomous Work UI.
  - Future work on the pipeline must not accidentally grow the general path into the loop (the two must stay decoupled — the user's explicit caution: don't build objective-mode as an extension of the same linear pipeline you're keeping lean).
  - Builds on ADR-5 (closed loop — the objective loop IS a closed loop over a whole task) and ADR-7 (workflows — the loop executes constraint-style workflows to "done"). Supersedes nothing.

---
## ADR-17: Prompt-budget program — measured static floor, chained-call collapse, and realtime UI as the latency target (2026-08-11)

- **Author:** Buffy / deepseek-v4-flash (Session 143, per the user's thread — real-model traces 2026-08-09..11)
- **Status:** accepted — measurement + program; implementation starts Session 144
- **Context:** The user's real-model thread ("Show me all projects in dev", "Check git status…") repeatedly hit the SAME failure shape: a tool-requiring request takes 35-120s, shows a silent black-box "SHELL" card, dumps a raw Worker-report instead of a synthesized answer, and reports ~18K "prompt tokens" for what should be a 2-3 tool call. Measured prompt composition (2026-08-11, from the actual builders):
  1. **Static floor ≈ 9K tokens per agent-path LLM call.** Agent system prompt 16,487 chars ≈ **4,121 tok** (split: ~594 tok CRITICAL RULES, ~378 tok RESPONSE FORMATTING, ~256 tok TOOL ARGUMENT RULES, ~232 tok HOW TO THINK, ~210 tok RESULT VERIFICATION, ~189 tok check-before-acting per-tool, ~163 tok must-NOT-do, ~150 tok shell safety, ~123 tok environment, plus Operator/strategy/self-check/verification sections). SHELL intent-scoped tool defs: 18 tools / 15,185 chars ≈ **3,797 tok** (intent scoping from Session 124 cut 24→18; still large because tool description text is verbose). Coding-agent context (build_coding_context) 3,055 chars ≈ **763 tok**. Plan context capped 1,500 chars ≈ **375 tok**.
  2. **The ~18K "prompt" is the CUMULATIVE `_provider_usage` across 3-5 chained LLM calls** — dispatcher capability-inference + plan + 1-3 agent-loop iterations — each paying the ~9K floor; `_provider_usage.update()` accumulates per-turn (verified loop.py:1692/1948/2777 + engine `_last_turn_prompt_tokens`). It is NOT one bloated prompt; it is the sum of many moderately-sized ones. The user-facing number is thus honest but misleading — fixing latency means cutting CALL COUNT, not just prompt size.
  3. **Per-turn latency decomposition (from the 41.3s trace):** dispatcher round-trip → plan round-trip → loop iteration 1 (model plans+dispatches `dir`) → tool executes (50ms) → loop iteration 2 (synthesize). Four serial network round-trips at 2-3 tok/s free-tier throughput = 40+s. The tool itself ran in 50ms.
  4. **The black-box SHELL card** is the pre-tool phase (dispatcher + plan + iteration-1 LLM calls) with NO streaming — the UI only shows output after the first tool call lands. The "why:" blank + unchecked todo were already fixed (Session 142).
- **Decision:** Run a multi-session **prompt-budget program** with three parallel tracks, each measured before/after:
  1. **Cut the static floor** (Session 144): trim the agent system prompt to the minimum that preserves the Session 31-33 contracts (check-before-acting, silent-failure honesty, no-fabrication, tool-argument rules) — target ≤3,000 tok; compress tool-description verbosity so intent-scoped defs drop toward ~2,000 tok; keep coding context ≤600 tok. Anything already enforced structurally (e.g., tool input extraction) can be shortened in prose.
  2. **Collapse chained calls** (Session 145+): merge the plan step into the first agent-loop iteration where the plan is simple (plan step is only needed for multi-step goals; a single-tool request's "plan" is one line — the loop's own first iteration can emit the todo plan from the dispatcher's steps without a separate planning LLM call, which Session 134's dispatcher-plan-reuse already half-does). Reuse the Session 135 dispatcher cache aggressively (keyed by normalized message) so near-duplicate requests skip the dispatcher call.
  3. **Realtime UI** (Session 146+): stream dispatcher + plan + iteration thinking text live (the Thinking block already exists for iteration content — extend it to the pre-tool phase), so the SHELL card is live-updating, not a 35s void; wire per-stage timing (ADR-12) into the action cards; make every panel update on SSE events in ms, not at turn end.
- **Consequences:**
  - The 18K figure will shrink as call count drops (it is cumulative) AND as the floor drops. Success metric: a single-tool request reports prompt < 8K and wall-clock < 15s on the free-tier model; the SHELL card shows live thinking within ~1s.
  - Do NOT regress: Session 31 silent-failure contract (empty stream → honest evidence dump), Session 32 hit-limit messaging, check-before-acting injection, Session 124 intent tool scoping, Session 135 dispatcher cache.
  - Does not supersede ADR-14 (thin dispatcher — this program makes the dispatcher's own call cheaper/faster) or ADR-16 (two workflows — the objective loop stays separate).

---
## ADR-18: Verification-first runtime hardening — "done" becomes a checkable contract, not a model assertion (2026-08-12)

- **Author:** Buffy / deepseek-v4-flash (Session 152, per the user's agentic-architecture thread)
- **Status:** accepted direction — program documented; implementation in following sessions (real-model tested per the flaw log)
- **Context:** The user's architecture thread (2026-08-12) drew the generative-vs-agentic line: an agentic system is an execution runtime in which models are decision-making components — Observe → Understand → Plan → Act → Verify → Remember → Continue — with six primitives (Agent, Tool, Orchestrator, Memory, Environment, Verifier) and a hard rule: "an agent saying 'done' should not mean the task is done." LocalMind's ADRs already target most of this (ADR-5 closed loop, ADR-6 multi-agent, ADR-8 agent-centric routing + agents-as-directories, ADR-10's Observe→Think→Decide→Act→Observe→Verify loop, ADR-16 objective loop). This session then code-verified the GAP between the ADRs and the runtime:
  1. **Termination is model-asserted.** Every per-agent `is_done()` is a scaffold that always returns False: `agents/coding/is_done.py:9`, `agents/browser/is_done.py:9`, `agents/analyst/is_done.py:11`, `agents/debugger/is_done.py:11`, `agents/reviewer/is_done.py:11`, `agents/verifier/is_done.py:12` all carry "For now, is_done() always returns False". The loop ends when the MODEL emits its final synthesis or the per-agent iteration cap (8-20) fires. Today "done" literally IS a model assertion.
  2. **No goal contract.** Zero matches for `success_criteria` or a `Goal` object in `backend/src`. The planner emits JSON-schema plan steps as prose — nothing deterministic for a verifier to check against.
  3. **Verification is prompting, not gating.** The loop has a verify phase + `WHAT I'LL VERIFY` plan field, deterministic post-execution hooks (`_verify_tool_result`, `VERIFY_FILE_WRITE`/`VERIFY_CODE_EXEC` in `core/agent/constants.py:116-120`), and an evidence-first Worker report with an evidence-quoting gate (`core/agent/models.py`). But the VerifierAgent is reachable only as an intent-routing destination (`agents/selection.py:82` — `Intent.VERIFY → verifier`), not as an acceptance stage; `is_verifier_done` is a skeleton too.
  4. **Task state is scattered.** `ExecutionGraph` (per-plan DAG), `AgentTrace` (iterations/hit_limit), the todo plan (prose), and the objectives store each hold fragments — there is no single first-class TaskState the orchestrator drives from and injects into context.
  5. **No failure memory.** Nothing writes what-failed-and-why at loop end; ADR-7's learning step was never wired into the runtime (memory is retrieval-centric).
  6. **What IS real — must not regress:** playbooks reach the model (`agents/base_agent.py:315` `build_context()` → `build_agent_system_prompt()`), workspace feedback bar (`core/workspace_state.py` git/diff/build snapshot per turn), evidence-first Worker report + evidence gate, delegation with bounded instruction packets + final-output-only (ADR-15), iteration caps + hit-limit-aware fallbacks, check-before-acting `safety.md` injection (ADR-7/32), adapter fixes (trailing tool-role, reasoning-only Phase-1 — Session 31), `_obs.all()` not `drain()` (Session 33), signal fast paths + call collapse (ADR-17).
- **Decision:** Run a multi-session **verification-first hardening program**, closing the gaps in priority order:
  1. **P0 — Acceptance gate.** (a) The planner emits typed success criteria alongside the plan (extend the existing JSON-schema plan output). (b) A first-class `TaskState` (objective, constraints, phase, completed/pending/failed work, evidence, budget, success criteria) consolidates the scattered state; the orchestrator drives from it and it is injected into context. (c) Replace the `is_done()` stubs with real checks where criteria are testable (tests pass, file exists with content, git diff contains the expected change, HTTP status, no ERROR in output); where not testable, the existing evidence requirement (Worker-report gate) applies. (d) Gate failure → explicit replan (verify→replan edge), bounded by the existing iteration caps.
  2. **P1 — Verifier as a stage, not a destination.** Promote VerifierAgent to an acceptance stage for high-stakes intents (file write, code exec, refactor); implement real `is_verifier_done`.
  3. **P2 — Failure memory.** Append what-failed-and-why at loop end (ADR-7 learning-step wiring); read it back for repeated patterns.
  4. **P3 — Close remaining transitional wiring** (delegation streaming/UX, remaining AgentLoop glue) per the adr-8 manifest's open items.
- **Consequences:**
  - P0 success criterion: a multi-step task visibly FAILS and REPLANS when its own acceptance check fails (observable in the UI/evidence), instead of reporting done on model assertion. The is_done() stubs are gone.
  - **No-regression list:** Session 31/32 iteration caps (8 / 180s) + hit-limit fallback wording; Session 32 check-before-acting injection; Session 31 adapter fixes; Session 33 `_obs.all()`; ADR-17 call collapse + signal fast paths; evidence-quoting Worker-report gate.
  - **Flaw-log rule binds every phase:** any phase touching the loop/model path MUST be real-model tested before commit. Zen free tier was 429-rate-limited on 2026-08-11 — implementation sessions attempt the live smoke first and must not ship untested (Session 116 lesson: unit-mocked green ≠ real-model green).
  - Baseline (Session 152): backend 1293 tests pass, ruff clean, tsc clean, eslint 0 errors (61 warnings), frontend 95 tests.
  - Builds on ADR-5/6/7/8/10/16/17. Supersedes nothing. Agents stay structurally as they are; their is_done() becomes load-bearing.

## ADR-22: Agent-First Routing — dispatcher is a hint, not a directive (2026-08-13)

- **Author:** Super Z / GLM-5.2 (Session 184, per the user's "agent should decide, not intent" directive)
- **Status:** accepted direction — implementation in this session, real-model tested per the flaw log
- **Context:** The user's diagnosis (Session 176 audit + Session 184 follow-up): LocalMind "feels like generative + tools" because the ThinkingDispatcher pre-decides the intent via signal detection (regex match on `msg.startswith("ls ")` etc.) WITHOUT an LLM call, builds the literal tool-call node, hands it to the agent loop as `orchestrator_context` + `plan_steps`, then the engine sets `skip_planning=True` (`_pipeline.py:2677-2701`). The agent's first LLM call is therefore a tool-execution call, not a reasoning call. The user's example: "Show me all projects in dev folder" should reason about locating all `dev` folders (find_path), ask clarification if multiple exist, then display a projects summary — not blindly run `ls dev`.

  The audit (Session 176) mis-flagged this as a verification gap (F2 GoalInterpreter). Sessions 177-183 closed the verification half (GoalInterpreter + post-exec verifier + structured planner + frontend phase visibility + 4 is_done stubs promoted). But the FRONT HALF of the loop — Understand + Plan — was untouched. The agent still doesn't reason about routing; the dispatcher does.

  Three options were considered:
  - **A. Remove signal detection entirely** — every message goes through the dispatcher's LLM capability inference. Costs 1 LLM call (~5-15s on free tier) per request. Restores agent reasoning but pays the latency on every turn including trivial ones.
  - **B. Keep signal detection but route the result THROUGH the agent loop as input, not as a directive** — the agent sees "dispatcher suggested shell" as a hint, decides itself whether to call shell. Preserves the latency win for the common case (when the agent agrees with the hint) but restores reasoning. ✅ USER APPROVED.
  - **C. Make `skip_planning=False` always for AGENT_INTENTS** — remove the `_pipeline.py:2677-2701` override. Simpler than B but loses the orchestrator_context mechanism's value entirely.

- **Decision:** Option B. Three concrete changes:
  1. **Keep `_skip_orchestrator = True` at high confidence** — the orchestrator IS redundant when the dispatcher already classified (it would just re-classify).
  2. **Remove the `_skip_planning = True` override at `_pipeline.py:2677-2701`** — the agent ALWAYS plans for AGENT_INTENTS, even when the dispatcher produced a graph. The agent's `_plan_stream` LLM call runs; it sees the routing hint; it produces its own plan.
  3. **Reframe `orchestrator_context` from "Structured plan from capability inference" to "Routing hint from capability inference (verify and adapt before calling tools)"** — the agent system prompt frames it as a suggestion to evaluate, not a directive to execute. The agent can:
     - Agree with the hint and call the suggested tool (the common case — preserves the latency win).
     - Disagree and call a different tool (e.g. "Show me projects in dev folder" → use `find_path` to locate all `dev` dirs first, not `shell ls dev`).
     - Ask the user for clarification when the hint is ambiguous.

- **Consequences:**
  - Latency: +1 LLM call (the planning call) for high-confidence AGENT_INTENTS. On the free tier this is ~5-15s per turn. Trade-off: the agent now actually reasons about the request.
  - The `dispatcher_plan_reused` obs event is REMOVED — the dispatcher's plan is no longer "reused" as the agent's plan. Replaced with `routing_hint_provided` (informational; the agent sees the hint but produces its own plan).
  - The `dispatcher_high_confidence_skip` event still fires for the orchestrator skip (the orchestrator IS still skipped at high confidence — only the planning skip is removed).
  - **No-regression list:** Sessions 177-183 changes (GoalInterpreter, post-exec verifier, structured plan DAG, frontend phase visibility, 4 promoted is_done stubs). The acceptance gate still runs. The post-exec verifier still runs. The structured plan DAG still parses the agent's `_plan_stream` output (which now always runs for AGENT_INTENTS).
  - Baseline (Session 184 start): backend 1572 tests pass + 1 pre-existing failure (test_output_bounds — unrelated).
  - Builds on ADR-18 P0/P1/P2 + Sessions 177-183. Supersedes the v0.11 latency-fix comment at `_pipeline.py:2641-2652` (the "≥0.7 confidence skips orchestrator + planning" decision) — the orchestrator skip stays, the planning skip is removed.
## ADR-23: Session Episode Memory — the system-level "keeps learning and session context" layer (2026-08-13)

- **Author:** Buffy / deepseek-v4-flash (Session 190, per the user's directive: build the missing session-context/learning layer, explicitly system-level — "users do not need to know what's happening in that level")
- **Status:** accepted + implemented + full suite 1660 green
- **Context:** The product stored raw history, semantic facts, failure memory, and a decision ledger, but nothing distilled a session into an episode-level bridge. The closest analog — `.context/` — has agents write a compact "what happened this session, what changed, what's next" record at session close and load it next session. That piece was genuinely missing on the product side (the gap named in the Session 189 architecture review).
- **Decision:** A lazy, background, best-effort session-episode layer:
  1. **Storage:** `session_episodes` table (UNIQUE session_id, upsert, 180-day retention pruned on write) in SessionStore — one digest per session, deliberately no FK to sessions (episodes outlive their source session, like decision_ledger).
  2. **Write — `core/episode_memory.py` `EpisodeMemory.distill()`:** LLM-summarizes the session tail (cap 40 messages) into {summary, decisions, failures, next_steps} via the adapter (30s wait_for timeout); DETERMINISTIC fallback from the first user message + last response when the provider fails/times out/returns garbage, so the table never stays empty because the model was down. Re-distills when a session grows past its recorded turn_count (the bridge never freezes at the first switch point). Triggers: (a) session-switch in the engine (`_process_unlocked`: a turn for a different session than `_last_active_session_id` fire-and-forgets distill of the previous one); (b) `sweep()` at startup for sessions never switched away from (restart/crash).
  3. **Read — the episode bridge:** per turn, at the memory merge point (and the DIRECT chat path), `latest_episode(exclude_session_id=current)` → `format_episode_hint()` appended to memory_facts. Prompt-only; never rendered in chat.
  4. **System-level by construction:** no obs events, no chat output, no vector-store writes (the table IS the memory — avoids the embedding dependency), never raises.
- **Consequences:** One indexed query per turn (latest_episode) — negligible on the pooled WAL connection. One bounded background LLM call per ended session (only when the session had >= 2 user turns and the provider is up; deterministic fallback otherwise). The bridge gives a new session "what happened before" even for short greetings (DIRECT path). No user-visible changes — the layer is invisible by design.
- **No-regression list:** Session 31/32 contracts; ADR-18/19 read paths (the hint appends after the failure/decision hints at the same merge point — the merge-point comment explicitly names Episodic as a future category routed there); Session 188/189 (deterministic social replies, SO_REUSEADDR port pre-check, PowerShell routing).
- **Baseline (Session 190 start):** backend 1647 green. End: 1660 green (+13 tests), ruff clean.
- **Builds on:** ADR-18 P2 (the Remember stage), ADR-19 P2 (durable table + read-hint pattern). Supersedes nothing.

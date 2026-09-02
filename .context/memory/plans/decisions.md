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

---
## ADR-24: Parent AgentLoop is the sole delegation entry point (2026-08-14)

- **Author:** Buffy / openai/gpt-5.6-luna (Session 200)
- **Status:** accepted + implemented
- **Context:** LocalMind had a modern ADR-8 path where a selected scoped agent
  runs through `BaseAgent.run()` and can call `delegate`,
  `delegate_parallel`, or `delegate_inline`. `_pipeline.py` also retained a
  separate `should_use_sub_agents()` heuristic that could intercept complex
  requests before the parent loop, run a legacy decomposition/direct-chat
  framework, and return synthesized prose outside the parent context.
- **Decision:** Remove the pre-loop heuristic and legacy decomposition framework.
  Task-profile routing selects the parent agent; that parent AgentLoop owns all
  cross-domain delegation through its scoped delegation tools. Child results
  return through the parent's internal tool context and the parent synthesizes
  the final answer.
- **Consequences:** There is one orchestration contract, no duplicate
  decomposition LLM call, and no legacy direct-chat bypass. Future delegation
  features must be implemented as scoped parent-agent tools or AgentLoop
  behavior, not as engine-level keyword routing. Parallel workspace safety and
  bounded child results remain separate follow-ups.

---
## ADR-25: LocalMind parent-agent runtime replaces the request pipeline (2026-08-14)

- **Author:** Buffy / openai/gpt-5.6-luna (Session 201)
- **Status:** accepted + implemented
- **Context:** The user clarified that the goal was to remove the request-time
  pipeline, not preserve it behind a compatibility wrapper or merely map more
  intents through it. Codebuff/Freebuff/Buffy are prior-art references only.
  The old pipeline mixed lifecycle services with dispatcher classification,
  direct-tool shortcuts, execution graphs, and agent-loop entry decisions.
- **Decision:** `AgentRuntime` is LocalMind's lifecycle boundary and
  `ParentAgent → BaseAgent.run() → AgentLoop` is the sole live request execution
  contract for non-blocked turns. The parent owns tool choice, native calls,
  delegation, evidence evaluation, replanning, acceptance, and final synthesis.
  Specialized agents remain available only through the parent's scoped
  delegation tools. `Engine` remains an import-compatible public alias, not a
  second execution implementation. Delete `_pipeline.py` rather than retaining
  it as a shell.
- **Consequences:** Safety, history, persistence, memory, attachments, session
  CWD, observations, metrics, reflection, failure memory, abort, and steering
  remain reusable lifecycle services. Dispatcher, execution-graph, and workspace
  orchestrator modules may remain as isolated data contracts/tests, but they are
  not request-time routers or executors. Parent prompt context is advisory: any
  caller-provided plan/hint must be evaluated by the parent and cannot bypass
  planning. This supersedes the old general-request pipeline shape while
  preserving ADR-5's closed-loop and ADR-8's agent-centric/delegation contracts.

---
## ADR-26: Conversational turns bypass tool planning (2026-08-14)

- **Status:** accepted + implemented
- **Context:** After the request-pipeline removal, the existing trivial-input
  helpers had no production caller. Even a greeting such as `Hi` entered the
  full parent tool loop, causing provider reasoning/tool calls and long silent
  waits for a request with no tool objective.
- **Decision:** `AgentRuntime` recognizes deterministic social inputs and clearly
  conversational questions before memory/tool planning. Social inputs use the
  zero-provider `trivial_response` boundary; conversational questions use
  direct chat without tool definitions or parent planning. Every substantive
  turn still enters the single `ParentAgent → AgentLoop` path.
- **Consequences:** Greetings are immediate and tool-free while substantive
  tasks retain the parent-agent closed loop. The direct boundary must preserve
  persistence, observations, stage timing, and completion semantics, and must
  not grow into a second substantive router.

---
## ADR-27: Parent workflow progress is a user-facing lifecycle contract (2026-08-14)

- **Author:** Buffy / openai/gpt-5.6-luna (Session 207)
- **Status:** accepted + implemented
- **Context:** LocalMind already performed parent-agent planning, tool execution,
  observation, acceptance verification, and replanning, but substantive turns
  could appear detached. The runtime did not acknowledge the request before
  memory/provider work, and raw planner/provider reasoning was forwarded as
  frontend thinking content. A user therefore saw long silence or garbled
  internal text instead of the example-agent behavior: acknowledge → plan → act
  → verify → report.
- **Decision:** Treat concise lifecycle progress as part of the parent-agent
  contract. Substantive turns emit an acknowledgement before expensive work,
  summarize planning after the internal plan is parsed, report that the parent
  is selecting its next action during provider waits, and announce verification
  before the acceptance gate. Raw provider planner/reasoning tokens remain
  internal evidence and task-state context; they are not a user-facing answer.
- **Consequences:** The existing SSE `status_update` path becomes the primary
  progress surface while native tool-call and bounded tool-result events remain
  visible. The parent loop, not a new router or UI-specific agent, owns the
  lifecycle. Direct greetings/conversation remain governed by ADR-26 and do not
  receive substantive workflow statuses. Future workflow phases should add
  concise status events rather than exposing raw chain-of-thought/provider
  markup.
- **Product commit:** `0f65c22`.

---
## ADR-28: First SSE event is transport acknowledgement (2026-08-14)

- **Author:** Buffy / openai/gpt-5.6-luna (Session 208)
- **Status:** accepted + implemented
- **Context:** The frontend had a local assistant placeholder, but the chat endpoint performed synchronous prelude work before emitting any server event. Slow/cold clients could see 9–15 seconds of apparent silence even when the agent had begun handling the request.
- **Decision:** `_event_stream()` must emit a concise `status_update` as its first SSE event, before title persistence, memory retrieval, adapter setup, or model generation. This is a transport acknowledgement, not a second router or a substitute for the parent-agent workflow.
- **Consequences:** Native clients and proxies receive an immediate payload and can distinguish transport delay from provider generation latency. Greetings remain deterministic and tool-free; substantive turns still use the parent-agent loop. The first acknowledgement does not reduce the selected model's final-answer generation time.
- **Product commit:** `06943b6`.

---
## ADR-29: Tool observations remain inside the parent workflow (2026-08-14)

- **Author:** Buffy / openai/gpt-5.6-luna (Session 209)
- **Status:** accepted + implemented
- **Context:** LocalMind exposed plan/status/tool events, but the live `web_search` path treated a successful search as terminal. It synthesized and emitted the search result before the parent could inspect evidence, fetch a source, replan, verify, or produce a separate final answer. This reduced the workflow to `user → tool → answer` instead of the example-agent loop.
- **Decision:** A tool result is always an intermediate observation unless a runtime-owned completion contract explicitly closes the turn. Search results must be appended to the parent conversation as a tool message; the parent then owns the next decision and may continue, delegate, verify, replan, or synthesize. Native and text-encoded/intercepted tool calls follow the same boundary.
- **Consequences:** Tool cards, terminal output, todos, and concise lifecycle statuses remain visible in real time through the existing SSE bridge. The frontend does not need a second tool-result-to-chat path. Raw provider chain-of-thought remains private; user-visible thinking is structured plan/action/verification progress. The compatibility web-search helper remains available for direct unit callers but is not a live terminal shortcut.
- **Product commit:** `5c2cfbd`.

---
## ADR-30: Shared reduced-motion enter primitive for realtime-alive-ui (2026-08-14)

- **Author:** Claude Code / claude-opus-4-8 (Session 216)
- **Status:** accepted + implemented
- **Context:** The realtime-alive-ui feature (Sessions 210-215) made six surfaces feel live — the chat Actions timeline, thinking stream, plan checklist, panel action trace, agent workspace, and terminal. Five of them animate items in with the same framer-motion "fade + slide" pattern, each repeating `initial={reduceMotion ? false : {opacity:0, x/y}}` + `animate={{opacity:1, x:0, y:0}}` + `transition={{duration, ease:'easeOut'}}` and its own `useReducedMotion()` call. The duplication risked the surfaces drifting apart and made the accessibility guarantee (respect `prefers-reduced-motion`) easy to forget on the next surface.
- **Decision:** A single hook, `useEnterMotion()` in `frontend/src/lib/localmind/motion.ts`, is the canonical source of the enter animation. It returns `{ reduce, enter }`: `enter({x, y, duration})` yields spreadable `initial/animate/transition` props (with `initial: false` under reduced motion so the item just appears), and `reduce` is exposed so callers gate their other motion (pulses, pings, height collapses, framer `layout`) on the same preference. New alive surfaces MUST use it rather than re-inlining the pattern. Bespoke, non-enter animations (scale-in ticks, width-animated progress bars, height expand/collapse) stay inline but still read `reduce` from the hook. The terminal's blinking cursor is intentionally a CSS keyframe (high-frequency component), not this hook — but it honours the same `prefers-reduced-motion` media query.
- **Consequences:** One place defines the easing/target/reduced-motion behaviour; the five components (ToolSteps, ThinkingBlock, TodoList, ActionHistory, AgentWorkspace) now consume it and dropped their direct `useReducedMotion` imports. Behaviour is unchanged (173 frontend tests green, tsc/build clean). Future "alive" work inherits the accessibility guarantee by construction. Covered by `motion.test.ts` (offset/duration defaults + reduced-motion path).
- **Product commit:** recorded after push.

---
## ADR-31: Multi-palette theming via a semantic anchor layer (2026-08-14)

- **Author:** Claude Code / claude-opus-4-8 (Session 217)
- **Status:** accepted + implemented (S217); runtime + Settings pending (S218)
- **Context:** The UI was monochromatic dark-green (Session-103 made it dark-only). The user found it "too green" and asked for a redesign where the color is a signal, not wallpaper — and then for three distinct palettes (Graphite/Emerald, Midnight Iris, Warm Ink), each in light and dark, user-selectable in Settings. The ~50 `--brand-*` tokens are color-NAMED (`--brand-green`, `--brand-amber`) and referenced directly by ~15 components, so renaming them to role-based names would be a large, risky sweep.
- **Decision:** Introduce a compact semantic ANCHOR layer (~25 vars: `--acc*`, `--s-*` surfaces, `--t-*` text, `--line*`, `--warn/--danger/--info/--alt`, `--code-text`). Map every legacy `--brand-*` token AND the shadcn/ui tokens (`--background`, `--card`, `--primary`, `--border`, …) ONCE onto these anchors in `:root`. Each theme × mode is a `:root[data-theme][data-mode]` block that sets ONLY the anchors. The ANSI (`--brand-gh-*`) palette and scrollbars vary by mode only. The app is themed by setting `data-theme`/`data-mode` on `<html>`; no attributes = graphite dark. This reverses the Session-103 dark-only decision and keeps the color-named `--brand-*` tokens as legacy role-holders (no component churn).
- **Consequences:** Adding/retuning a palette is a localized CSS edit; components never change. shadcn primitives theme for free. The color-named tokens are now semantically misleading (`--brand-green` may be indigo) — documented; a future session may migrate components to role-named utilities. Light mode exists across all components for the first time and needs a dedicated contrast pass (S219). Verified: all 6 combos resolve correct computed colors via data attributes; default renders clean; 173 tests / build green.
- **Supersedes:** the Session-103 dark-only theming decision.
- **Product commit:** `40930e0`.

---
## ADR-32: Fail-fast provider preflight — surface provider errors in the first round-trip (2026-08-14)

- **Author:** Claude Code / claude-opus-4-8 (Session 219; deferred to a resume session — user out of tokens)
- **Status:** proposed (NOT yet implemented — this is a handoff ADR; see tasks/current.md)
- **Context (user-reported):** When the provider returns an error the user can hit *before generation* — e.g. free-usage-limit / rate-limit (HTTP 429), auth (401), payment (402) — the app waits through the whole agent-loop lifecycle (>20s of "doing nothing") and only surfaces the model error at the end, instead of within milliseconds. Root cause: the user-facing **acknowledgement is a deterministic lifecycle status**, not a provider call. It is emitted BEFORE the first model call:
  - `backend/src/core/agent_runtime.py:562-563` — acknowledgement emitted "before memory retrieval or the first model call".
  - The first real provider round-trip is `clock.start("generate")` at `agent_runtime.py:394` and `:639`.
  - `backend/src/core/thinking_dispatcher.py` emits `acknowledgement` from **signal fast-paths (zero LLM)** at lines 449/476/518 and from the dispatcher profile (line 329 schema). So for signal-matched or cached requests, NO provider call happens until deep in the loop, and a 429/401 only becomes fatal at `generate`.
  The user's model: "the agent should contact the model FIRST when acknowledging the request" — the understanding/dispatch step should be an actual (cheap, bounded) provider call whose provider-level errors terminate the turn immediately.
- **Decision (proposed):** Add a **fail-fast provider preflight** at the very start of a substantive turn, before the expensive lifecycle. Options to evaluate in the resume session:
  1. **Preferred:** a lightweight preflight that reuses the FIRST necessary provider call (the dispatcher/"understanding" call) and, when that call raises a normalized *pre-generation provider error* (429/401/402/403 — see ADR-20/21 error normalization), emits the canonical error card as a terminal SSE event **immediately** and ends the turn. Do NOT swallow these into a fallback that continues to the loop.
  2. For signal/cached fast-paths that legitimately skip the dispatcher LLM, add a **cheap bounded preflight ping** (tiny max_tokens "understanding" call, or a provider capability/health probe) whose sole purpose is to trip auth/limit errors early — only when the turn will otherwise do real model work.
  Classify which provider errors are "fail-fast, terminal, pre-generation" vs "retryable/transient" (reuse ADR-21's provider-envelope classifier + the 429 retry-with-backoff already in the adapter). Terminal pre-gen errors → emit the error card in the first round-trip; transient → existing retry path.
- **Consequences:** Users on exhausted free tiers / bad keys get an instant, honest error instead of a 20s dead wait. Must NOT regress: the deterministic conversational boundary (`Hi` makes zero provider calls — Session 206) must stay zero-call (no preflight for trivial/greeting turns); the acknowledgement-first UX (Sessions 207/208) stays, but a provider error now overtakes it. Add a regression test: a mocked adapter raising a 429 on the first call yields a terminal error SSE within one round-trip (not after a full loop), and `Hi` still makes zero calls.
- **Files (starting points):** `backend/src/core/agent_runtime.py` (acknowledgement + `generate` sites 394/639), `backend/src/core/thinking_dispatcher.py` (fast-path acknowledgement 449/476/518 + profile), `backend/src/api/routes/chat.py` (`_event_stream` first-event ordering), error normalization from ADR-20 (`adr-20-error-normalization`) + ADR-21 (`adr-21-provider-agnostic-errors`), and the adapter 429-retry path.
- **Relates to:** ADR-20, ADR-21; Sessions 205-208 (acknowledgement/latency), Session 206 (conversational boundary).

**Update (Session 220):** Partially implemented. The adapter-level
fail-fast landed (`1762509`): `OpenAICompatAdapter._send_streaming_with_retry`
now classifies a permanent quota/billing 429 (via `_is_permanent_429`) and
does NOT retry it — it surfaces immediately through the existing
`normalize_error` → error-card path, killing the 2s+4s×N backoff waste.
Remaining (backlog B-2026-08-14-5): the loop-level short-circuit — ensure
a terminal pre-generation provider error on the FIRST `parent.run` call
ends the turn immediately rather than iterating; and confirm 401/402/403
(not just 429) reach the error card without a full loop. Status: proposed → **partially implemented.**

**Completion update (Session 220 continuation):** The loop-level remainder is
now implemented in product commit `6014254`. Terminal planning errors propagate
through `TerminalProviderError`; `AgentRuntime` forwards terminal error chunks
instead of converting them into a generic no-answer fallback; the shared
ADR-20/21 classifier covers exhausted-quota 429 plus 401/402/403; transient
429s remain retryable. The permanent-429 adapter path also avoids its former
extra response-refresh request. ADR-32 is **accepted + implemented**. Feature
manifest: `.context/memory/features/fail-fast-provider-errors/manifest.md`.

---
## ADR-33: Parent-owned model initialization for every user turn (2026-08-14)

- **Author:** Buffy / openai/gpt-5.6-luna (Session 222)
- **Status:** accepted + implemented (`a7d5b30`)
- **Context:** Session 221 patched one missed greeting phrase, but the underlying
  live runtime still decided direct conversation versus agent work with
  `trivial_input` regexes before the parent agent existed. That architecture
  cannot scale: every new phrasing becomes another prompt-specific exception,
  and the model is not asked what the user's request means or how it should be
  handled.
- **Decision:** Every user turn enters `AgentRuntime → ParentAgent → AgentLoop`.
  The parent makes one bounded initialization model call with the complete
  available tool catalog and returns a typed decision: `direct`, `clarify`, or
  `execute`. Direct mode returns the initialization answer without a second
  execution call. Clarify mode asks one question. Execute mode emits the
  acknowledgement and goal-level plan/todos, then continues through the
  existing parent tool-call → observation → verification/replan → synthesis
  loop. Raw initialization JSON and private provider reasoning never become
  chat content.
- **Failure behavior:** malformed initialization output fails open to bounded
  execute mode; terminal provider errors still propagate through the existing
  canonical error boundary. Deterministic conversational helpers remain only
  as compatibility utilities and are not live routing owners.
- **Consequences:** ordinary direct conversation now requires one real provider
  call, while tool work reuses initialization as its planning call instead of
  adding a separate prompt-shaped classifier. Provider/model latency remains
  environment-dependent. Observe exposes an authoritative `agent_initialize`
  stage alongside context, tool, generation, and execution stages.
- **Supersedes:** the live request-routing behavior introduced by Session 206
  and the addressed-greeting patch from Session 221; it does not delete the
  compatibility helper APIs or change the parent-owned tool/delegation contract.
- **Validation:** backend 1,784 passed / 2 skipped; frontend 178 passed;
  TypeScript/build/Ruff passed; ESLint 0 errors / 64 existing warnings. No
  live-provider smoke was available.

---
## ADR-34: Parent-first realtime workspace contract (2026-08-14)

- **Author:** Buffy / openai/gpt-5.6-luna (Session 223)
- **Status:** proposed — context/research only; no product code changed
- **Context:** ADR-33 correctly moved request interpretation into a model-owned
  parent initialization call, but code-verified review shows the initialization
  call still waits behind memory retrieval, attachment parsing, and full context
  assembly. The UI then splits one execution across chat `ToolSteps`, the left
  Actions tab, the right Observe pipeline, Terminal, and a mostly passive Agents
  tab. Tool evidence can therefore look like the final assistant answer, while
  the user does not see a coherent parent-agent lifecycle.
- **Decision:** LocalMind's user-facing execution contract is one parent-owned
  realtime loop:

  ```text
  receive → acknowledge → fast thinker/understand → plan → act
  → evidence to parent + live nodes → verify/replan → parent synthesize → done
  ```

  1. **Parent initialization stays the sole interpretation boundary.** Do not
     add prompt-specific regexes, deterministic greeting exceptions, or a new
     intent classifier. The initializer returns bounded public fields for
     understanding, acknowledgement, mode, next action/plan, capabilities,
     clarification, and success criteria. Raw chain-of-thought and raw JSON
     remain private.
  2. **Bootstrap is visible and latency-bounded.** Emit a transport-level
     acknowledgement immediately, without pretending it is model thinking.
     Start the compact thinker without waiting for nonessential memory/context
     assembly. Target: acknowledgement ≤250ms and first public understanding or
     next-action event ≤5s when the provider is healthy. A complete remote/free
     provider answer is not guaranteed under 5s; time-to-first-feedback and
     time-to-first-decision are the measurable SLOs.
  3. **Evidence has one owner.** Every tool result is returned to the parent
     model as bounded evidence/context before synthesis. The UI may stream the
     same evidence into Agent, Actions, and Terminal nodes, but tool output must
     not populate the assistant's final answer. Only parent synthesis may emit
     final chat content.
  4. **Agent Workspace is the primary live surface.** Initialization activates
     the Agents tab automatically. A normalized event reducer renders parent
     and child nodes with public understanding, acknowledgement, plan/todos,
     tool calls, evidence, verification, replan, errors, and synthesis state.
     Actions and Terminal remain focused detail surfaces; chat remains the
     conversation/final-answer surface.
  5. **Retire Observe as a product pipeline.** Remove the user-facing Observe
     tab and its `Intent Classify → ... → Execute` visualization. Preserve
     backend timing/diagnostic telemetry, but render useful stage data inside
     the relevant Agent node or run details instead of a parallel pipeline UI.
  6. **Retire intent as a product contract.** Remove intent badges, intent
     classification UI/events, and intent-based routing decisions from the new
     surface. Internal `Intent` compatibility fields may remain temporarily at
     migration seams, but no new routing, UI, or lifecycle behavior may depend
     on them.
  7. **Simplify the shell.** Replace the default Electron title-bar experience
     with a deliberate LocalMind chrome design while preserving native window
     controls, platform drag/accessibility behavior, and browser fallback. Remove
     the normal-chat `Autonomous work` block from the sidebar; background
     objective persistence/API requires a separate product decision before any
     deletion.
  8. **Budget the prompts by stage.** Initialization receives a compact
     capability summary, not the full tool JSON schema. Full tool contracts are
     loaded only for the selected execution path. Measure initialization and
     execution prompts independently; do not pay the old 5K+ static floor on
     every chained call.
- **Consequences:** The Agent Workspace becomes the canonical visual model of
  agent state, and the chat transcript can no longer be mistaken for a tool
  console. The first model call becomes a fast public decision stage, while
  tool execution remains a closed loop with parent-mediated synthesis. Internal
  telemetry survives the Observe UI removal, so debugging does not regress.
- **Acceptance evidence:** A live matrix must show the event order
  `acknowledgement → agent_initialize/understanding → plan → action → evidence
  → parent synthesis`, no tool result as final assistant content, automatic
  Agents activation, no user-facing intent/Observe pipeline, first public
  thinker event within 5s under a healthy provider, and initialization/tool
  prompts below their stage budgets. Real-provider validation is mandatory.
- **Builds on:** ADR-5, ADR-8, ADR-17, ADR-18, ADR-22, ADR-30, ADR-32, and
  ADR-33. It supersedes the user-facing Observe pipeline and intent surfaces,
  not the backend observability collector or parent/delegation runtime.

---
## ADR-35: Keep conversational turns off the full execute path (latency + tokens) (2026-08-15)

- **Author:** Claude Code / claude-opus-4-8 (Session 232; proposed — needs a live-model trace to implement)
- **Status:** proposed (NOT implemented — handoff; the fix must be measured against a real provider, which this local session cannot run)
- **Context (user-reported):** A trivial greeting ("How's the going") costs ~16s and ~5,000 prompt tokens/turn (session corner: 10,204 total over 2 turns, prompt 10,124 / completion 80) on `laguna-s-2.1-free` (zen). Measured facts (Session 232, local, no provider):
  - The init/classify call is CHEAP: `build_initialization_prompt` ≈ **880 tokens** (env_context ~470 tok + compact tool summary from ADR-34 B-12). So the classify step is NOT the bloat.
  - ~5k prompt tokens/turn means the greeting is NOT completing on the cheap **direct** path — it's entering the full **execute** loop, which builds `build_agent_system_prompt(intent, available_tools, …)` with the FULL tool schemas (large).
  - Two ways a greeting reaches execute: (a) the weak free model returns `mode":"execute"` or emits unparseable JSON → `parse_initialization` fails safe to execute (`initialization.py:256-263, 267`); (b) `mode":"direct"` but an empty/missing `response` → downgraded to execute (`initialization.py:284-286`).
  - Latency: ~16s is dominated by the free model's ~2.4 tok/s + processing the large execute prompt. The model's speed is not fixable in code; the prompt size (and thus prompt-processing time) is — by keeping conversational turns off the execute path.
- **Decision (proposed):**
  1. **Instrument first (needs provider):** log the live init decision per turn — `mode`, `bool(response)`, and the provider's `prompt_tokens` — to confirm whether greetings hit execute via misclassification vs the empty-response downgrade vs something else. Do not guess-fix.
  2. **Robust direct path for weak models:** when a decision is `direct` with an empty `response` (`initialization.py:284`), do NOT downgrade to the full execute loop. Instead run a SINGLE lightweight chat completion (no agent system prompt, no tool schemas — a conversational reply) to fill the answer. Keeps conversational turns at ~1k tokens instead of ~5k.
  3. **Prompt-tune init reliability:** strengthen `build_initialization_prompt`'s `direct` guidance so a weak model reliably picks `direct` for greetings/chit-chat (respects the user's "let the model decide, no hardcoded classifier" preference — ADR-34 spirit).
  4. **Trim init env_context:** the classifier does not need 470 tokens of kernel/hostname detail — pass a compact env (OS + cwd + date, ~30 tok) to the INIT call specifically (do NOT change the shared `_build_environment_context()` used by the execute system prompt).
- **Consequences:** conversational turns stay ~1k tokens / one cheap call; the free model's raw speed still bounds latency (documented, not fixable here). Must NOT regress: `Hi`→zero-provider-call boundary (Session 206), and ADR-34's model-owned routing (no hardcoded intent module). Every change needs a live `laguna-s-2.1-free`/zen trace before/after (prompt_tokens + wall-clock).

---
## ADR-36: Agent as orchestrator, Thinker as silent analyst — transparency is the ambiguity mechanism (2026-08-15)

- **Author:** Buffy / deepseek-v4-pro (Session 235)
- **Status:** accepted (architectural target — implementation phased; refines ADR-34)
- **Context (user-reported + design handoff):** The parent-first runtime (ADR-33/34) shipped the event order `acknowledgement → understanding → plan → action → evidence → synthesis`, but the user still finds the agent "takes command and executes, no actual agentic feel." Five symptoms: (1) the thinking is shallow — `understanding` is a one-line `objective`, not real reasoning; (2) the acknowledgement routes to the Agent Workspace rather than chat; (3) the plan + actions leak into the chat token stream instead of the Actions tab; (4) no final output; (5) no agentic feel. Through a design discussion the user landed on a restructure: collapse Planner into Agent (one decision point, no ping-pong), and introduce a **silent Thinker** the Agent consults. The load-bearing insight — **transparency as the mechanism** — is that a live-streamed Thinker assessment REPLACES both "silently resolve" and "block to ask": the user watches the resolution happen (e.g. "two dev folders found, picking the one with recent git activity") and can course-correct in the moment, but nothing blocks when the assessment is right.
- **Decision (five points):**
  1. **Roles.** Agent = loop owner, user-facing, the ONLY producer of the final reply — decides and acts. Thinker = silent, read-only, on-demand analyzer: looks at the state the Agent hands it, returns relevant facts / risks / ambiguities; never touches files, never talks to the user, never decides. Planner is dropped — folded into Agent.
  2. **Trigger.** Agent consults Thinker before the FIRST action by default, not only when it "feels" uncertain. The shallow judgment that produced the one-step "just list the folder" plan is exactly the judgment that must not be trusted to self-trigger. (Skipping Thinker for genuinely trivial cases is a later optimization.)
  3. **Ambiguity handling.** When Thinker flags real ambiguity, Agent resolves and proceeds (pick a reasonable default) rather than blocking to ask — visibility is the middle ground.
  4. **Assessment shape.** Thinker separates "facts I found" (inform the next step) from "ambiguities that block moving forward" (determine proceed / default / ask) — so Agent can act on it rather than shrug.
  5. **Transparency + collapse.** The assessment streams live to a dedicated thinking surface, distinct from chat and actions, then the block collapses once that step's reasoning is done (user decision: collapse, not persistent scrollback).
- **Consequences / phases:**
  - **The event-type tagging prerequisite is already largely in place** from ADR-34: typed SSE events (`token` / `thinking_*` / `tool_call` / `status` / `obs_event`), a ThinkingBlock that auto-collapses, the Actions panel, and the phase strip. The remaining tagging gaps are the dual-routing of the acknowledgement (statusText AND Agent Workspace) and plan narration leaking into the chat token stream (the `_isPromptLeak` filter is incomplete).
  - The real net-new work is **Thinker depth**: today `render_understanding()` emits only the init `objective` (one line); the spec requires a substantive facts/risks/ambiguities assessment. That is the "thinking is shallow" fix and the highest-leverage piece.
  - Builds on ADR-33 (parent-owned model initialization) and ADR-34 (parent-first realtime workspace contract); does NOT supersede ADR-5/8's closed-loop shape. Live-model validation (zen/laguna) is mandatory before shipping prompt/assessment changes — this local session cannot run the provider (see ADR-35).
  - Backlog: B-2026-08-15-5 (Thinker depth), B-2026-08-15-6 (routing/tagging polish), B-2026-08-15-7 (final-synthesis guarantee), B-2026-08-15-8 (collapse-after-done verification).
- **Relates to:** ADR-34 (parent-first init), ADR-32 (fail-fast provider errors), Session 206 (conversational boundary). **Owner note:** overlaps Buffy/Super Z's ADR-34 area — coordinate.

## ADR-37: One path, real reasoning, continuous reasoning→reply — delete the narration layer (2026-08-15)

- **Author:** Buffy / deepseek-v4-pro (Session 236)
- **Status:** accepted (architectural target; refines ADR-36)
- **Context (user design handoff):** Two follow-on findings from the user after ADR-36 shipped. (1) **Direct Mode is redundant** — now that the parent classifies trivial-vs-needs-loop at the front of its own pipeline, a separate `chat_mode=direct` path is a second code path that can fire alongside classification (structurally the source of dual replies). There should be one entry point; "fast vs slow" is just how much context-gathering a message needs, not a mode. (2) **The status narration is theater.** Live observation: the agent emits fixed stage labels — "I'm understanding the request…", "I'm preparing an execution plan…", "Plan ready (N steps)…", "I'm deciding the next action…", "I'm verifying the result…" — as hardcoded strings that run regardless of what was asked, then the real loop starts, and no reply lands. This is decoration standing in for a signal that should be real. Reference: DeepSeek's "Hi" reasoning — it references the ACTUAL message ("the user just said 'Hi' with an emoji"), reasons briefly, and the reply is immediately there; the reasoning is **real and proportionate** (a trivial message gets a sentence, not padded stage names), and **reasoning terminates directly in the reply** (same turn, no handoff gap).
- **Decision (three points):**
  1. **Delete the narration layer.** Remove the hardcoded stage-name status strings ("received your message…", "understanding the request…", "preparing an execution plan…", "creating a short plan…", "Plan ready…", "deciding the next action…", "verifying the result…"). They add latency and a false sense of progress; they are never real reasoning.
  2. **One live thinking stream is the status indicator.** The ThinkingBlock, driven by real Thinker output (objective + facts/ambiguities), is the ONLY reasoning surface — and it is proportionate to the message. The frontend's neutral status fallback ("Working on it…" / "Thinking", already in `useLocalMind.ts`/`CenterPanel.tsx`) covers the pre-first-token gap, so nothing freezes when the narration is gone.
  3. **Keep the honest tool-progress statuses.** "Done — {action} ({ms})" and "Reading page: {url}" report actual completed work and stay; they are real, not theater. (The model's own acknowledgement — the opening line — also stays; it is real model output, not a template.)
- **Refinement — three-tier split (the actionable classification model):** "fast vs slow" is not binary; it's three tiers and the tier decides whether the Agent Workspace boots AT ALL, not just how fast the reply comes:
  1. **Trivial** ("hi") → reply immediately, near-zero reasoning. `direct`, no workspace, no loop.
  2. **Needs thought, not tools** ("what can you do?") → reasoning proportional to the question (content planning: points to cover, tone, what to leave out), still ONE pass — `direct`, no workspace, no loop, no tools, no Thinker consult.
  3. **Needs tools/context** ("list my dev folder") → Thinker is consulted, the full loop runs, the Agent Workspace boots.
  Tiers 1 and 2 both resolve in a single generation; the difference is only how much the direct-mode reasoning says. Only tier 3 touches the workspace. Today's classifier collapses 1 and 2 into `direct` and 3 into `execute`, which is structurally right — the open risk is the free-tier model over-triggering `execute` for tier-2 content questions, and direct-mode reasoning not scaling with the question. (From the DeepSeek "What can you do?" reference: its four reasoning steps are CONTENT planning, not orchestration planning — one generation, no tools, no external loop.)
- **Consequences / follow-ups:**
  - Direct Mode removal (fold `chat_mode` into the classifier; drop the `ExecutionMode.DIRECT`-as-user-toggle concept) is a SEPARATE, larger item — filed as B-2026-08-15-10.
  - "No synthesize stage" / reasoning→reply continuity for the EXECUTE path needs its own audit (B-7 closed the gate-passed-empty case; other completion paths may still gap) — filed as B-2026-08-15-11.
  - Backlog: B-2026-08-15-9 (this session — delete narration), B-2026-08-15-10 (remove Direct Mode), B-2026-08-15-11 (reasoning→reply continuity audit), B-2026-08-15-12 (three-tier classification).
- **Relates to:** ADR-36 (Agent+Thinker), ADR-33/34 (parent-first init + typed SSE), ADR-6 (DirectAgent refactor). **Owner note:** narration strings live in `chat.py`, `agent_runtime.py`, `loop.py`; the frontend fallback already exists.

## ADR-38: Thinker as a mid-loop on-demand analyst on gathered evidence, not a one-shot upfront init field (2026-08-15)

- **Author:** Claude Code / claude-opus-4-8 (Session 237) — ground-up Thinker ownership handed to me by the user ("the Thinker is the backbone... handle it from the ground-up").
- **Status:** proposed (foundational architecture; implementation gated on a working provider — see the constraint below). Refines ADR-36/37.
- **Context / ground-up diagnosis (code-verified this session):** The "Thinker" today is ONLY the parent init call. `render_assessment_details(decision)` is invoked once, at `loop.py:4790`, inside `_initialize_parent_streaming` — BEFORE any tool runs. The Thinker's entire output is the init `InitializationDecision` (mode + acknowledgement + objective + `facts` + `ambiguities` + plan_steps), produced from the RAW request with nothing gathered yet. Consequence: its `facts` can only be what the model knows abstractly (home dir, date, OS from env_context) and its `ambiguities` are assumptions about the request ("assumed dev-folder path") — exactly what Buffy's B-5 live validation showed. **This is why it doesn't feel agentic.** ADR-36's load-bearing transparency example — *"two dev folders found, picking the one with recent git activity"* — is IMPOSSIBLE for an upfront assessor: naming a concrete finding like that requires having ALREADY looked (listed the folders, checked git). A Thinker that assesses before it has looked can only narrate assumptions.
- **Decision (the backbone):**
  1. **Split the two jobs the init call currently conflates.** (a) **Classification** (which of the three tiers — trivial / needs-thought / needs-tools) stays an upfront, cheap decision at the front of the pipeline (ADR-37 three-tier). (b) **Assessment** (the substantive facts/ambiguities Thinker analysis) becomes an **on-demand consult the Agent invokes MID-loop, on real gathered state** — after at least one context-gathering step — not a field baked into the initial classification.
  2. **Thinker signature = (goal, gathered evidence) → {facts, ambiguities, suggested next step/default}.** It is read-only, silent, produces no user-facing reply, decides nothing. The Agent calls it, streams its output to the ThinkingBlock (transparency), then acts on it (resolve + proceed with a default per ADR-36, not block).
  3. **Tier-3 only.** Only the needs-tools tier consults the Thinker and boots the Agent Workspace. Tiers 1–2 resolve in one direct generation (ADR-37) — no Thinker consult, no workspace.
  4. **Keep the upfront `objective` line** as the immediate "here's what I think you want" thinking cue; the real facts/ambiguities now arrive from the mid-loop consult on evidence, so they are concrete, not assumed.
- **Hard constraint (why this isn't built yet):** This is the AGENT'S BACKBONE. ADR-36 already mandates live-model validation before shipping prompt/assessment changes, and building a mid-loop consult architecture BLIND (no provider to observe real behavior against) guarantees rework. The only configured provider (zen free) is exhausted (Session 237: persistent 429 `FreeUsageLimitError`). **The genuine first ground-up step is a working, generous, fast provider (Cerebras 1M/day or Groq)** — not a code sprint against a dead model. This is ownership, not a punt: I will not build the backbone on a model I cannot run.
- **Consequences / plan (once a provider is live):** (1) add a `consult_thinker(goal, evidence)` model call + parser (reuse the facts/ambiguities shape from B-5); (2) invoke it in the loop after the first evidence-gathering step, before the next decision; (3) stream its output to the ThinkingBlock and collapse-after-done (ADR-36); (4) keep the init call to classification-only for tier routing; (5) live-validate the three tiers end-to-end (hi / what can you do / list dev folder) — the trace harness from Session 237 (backend from source + `curl /api/chat`, capture `mode`/`understanding`/`understanding_details`) is ready.
- **Relates to:** ADR-36 (Agent+Thinker, transparency), ADR-37 (delete narration, three-tier), ADR-34 (parent-first init), ADR-35/32 (provider constraints). **Owner note:** overlaps Buffy's ADR-36/37 area — I now own the Thinker per the user; coordinate on push.

- **Live evidence (Session 237, `nemotron-3.5-lightning-free` on zen — the free `deepseek-v4-flash-free` was quota-exhausted; switched to a working free model):** Traced all 3 tiers via `/api/chat`. **ADR-38 confirmed live.**
  - Tier-3 "list the projects in my dev folder at /Users/bao/Code" → `agent_initialization_done: mode=execute, objective="List the projects…", tool_names=['shell'], plan_steps=['Use shell ls…']` but **`facts=[]`, `ambiguities=[]`** — the upfront Thinker produced NO assessment, because before looking there is genuinely nothing concrete to state (exactly ADR-38's thesis). The interesting assessment ("found 2 folders, picking recent") can only exist AFTER a gathering step.
  - Tier-3 final answer = `"✓ 1/1 criteria met (Shell output displays directory names…)"` — a VERIFICATION message, not the actual listing. The synthesis/final-answer gap (ADR-37 B-11) is real and user-visible: the agent does the work but never produces the content answer.
  - Tier-2 "what can you do?" → answer leaked the init persona: `"As LocalMind's initialization stage, I have access to…"` — the classification prompt's framing bleeds into the user-facing reply.
  - Net: "it didn't fix anything" is now explained by observation — empty upfront assessment (Thinker) + verification-instead-of-answer (synthesis) + persona leak (tier-2). The Thinker ground-up work per ADR-38 (mid-loop consult on gathered evidence) is the right fix and is now evidence-backed, not hypothesized.

## ADR-39: Agent-loop token efficiency — byte-stable cacheable prefix + prompt caching + diet (2026-08-15)

- **Author:** Claude Code / claude-opus-4-8 (Session 245). Prompted by the user rejecting a single-prompt routing fix: "you fixed 1 prompt 25s→2s — that is not the real fix; Claude Code runs 3 min with many tools in few tokens, yet our 'hi' consumes 11k. Fix the real agent loop."
- **Status:** accepted + shipped (commit `9ee3745`), live-verified on cerebras.
- **Context / measured disease:** Every model call in the loop re-sent the WHOLE prefix, UNCACHED: ~3k system prompt + ~2–5k tool schemas (29 tools, ~18 after per-intent scoping) + history. A 4-tool task re-billed ~8–10k **four times** ≈ 40k tokens; a trivial execute turn ≈ 11k. Three root causes, all code-verified: (1) **no prompt caching wired** — grep of `openai_compat.py` for `cache_control`/`ephemeral`/`anthropic-beta` returned nothing; (2) **dynamic content in the cacheable prefix** — `_build_environment_context` baked `now.strftime("%H:%M")` (current time) INTO the system prompt, so the prefix changed every minute and even providers that auto-cache identical prefixes (OpenAI, Anthropic) MISSED on every call; (3) **fat prefix** (~3k prompt with duplicated anti-fabrication + verbose personas; ~5k tool schemas). Reference: Claude Code's efficiency is prompt caching — the static system+tools prefix is written to cache once (full price) then READ at ~10% on every later call in the session.
- **Decision — three levers, built together:**
  1. **Stabilize the cacheable prefix.** `build_agent_system_prompt` no longer embeds `env_context`. The loop emits a **byte-stable** system prefix (rules + personas + tool list) followed by a SEPARATE **trailing** turn-context system message carrying the per-turn dynamic bits (environment incl. time, ADR-5 workspace state, ADR-18 task-state). Guard test: no `## Environment`/`Current time:` in the cached prompt + two builds are byte-identical.
  2. **Wire prompt caching.** `cache_control: {type: ephemeral}` on the Anthropic-native `system` block and on the first system message for Anthropic-family models on the OpenAI-compat path. Non-Anthropic models (gemini/cerebras/openai) auto-cache the now-stable prefix, so they keep plain-string content (no marker). Rejection degrades cleanly: a 400 flattens block content back to text (`_flatten_message_content`) and retries once — additive, can never break a request. Also fixed `_chat_anthropic` to JOIN all system messages (lever 1 introduced a second).
  3. **Prompt diet.** Env removal (lever 1) + trimming the verbose formatting example cut ~2,270 chars (~570 tokens) off every execute intent (SHELL 12,981→10,713 chars). `test_prompt_size_budget` budgets tightened to lock it in; load-bearing anti-fabrication markers still asserted.
- **Live evidence (cerebras `gpt-oss-120b`, isolated `LOCALMIND_HOME`, port 8000 = user's app untouched):** "hi" = **1,089 prompt tokens / 839ms** (lean init path). Tool task "list projects" = **14,537 raw prompt tokens / 1.6s, `shell` tool fired, no error** (down from ~18k) — tool-calling + final answer intact, so the 2-system-message split + cache markers caused no regression. Full backend suite 1,760 passed (4 pre-existing env-gated `test_shell.py`).
- **Key nuance / limitation:** `prompt_tokens_approx` is our chars//4 estimate of the FULL prompt — it does NOT reflect the cache discount, which lands on the provider's billing as cache-read tokens (~10%). So the caching win (the biggest lever, for multi-call/multi-turn) is real but INVISIBLE to our metric; only the diet and lean-trivial wins show in it. Verifying the caching discount requires a provider that reports cache_read usage.
- **Consequences / next:** tool schemas are now the biggest per-call line item (~3.8k scoped tokens). Compacting the verbose ones (browse/git/delegate) is the next diet lever but risks tool-use regression — do it with live tool verification, not blind. Observed corroboration: cerebras enforces a TOKENS-per-minute cap (`too_many_tokens_error`) — the bloat directly caused a 429, so leaner+cached = fewer tokens/min = fewer rate limits.
- **Relates to:** ADR-35 (keep conversational turns off the execute path — this makes the execute path itself cheap), ADR-34 (parent-first init), ADR-32/ADR-20/21 (provider 429/402 handling; the Session 240 transient-429 recovery surfaced the cerebras token 429 cleanly).

## ADR-40: Lean tool schemas + on-demand tool context (progressive disclosure), modeled on the skill loader (2026-08-16)

- **Author:** Claude Code / claude-opus-4-8 (Session 250, research-only per user). **Status:** proposed (design; no code this session). Extends ADR-39; supersedes the plain "scope tools per intent" framing of B-2026-08-15-14.
- **User's principle (verbatim intent, Session 250):** "why do tools need too much context/tokens when they do specific tasks — they are not agents, they are tools, and the agent should feed the instructions to the tool, not the tool feeding itself." Refined: "it should have only those guardrails and how to behave, but the AGENT carries full context about the tool. This way the agent invokes only the context about a SPECIFIC tool, not all of them for no reason."
- **Context (measured, Session 249-250):** the model receives ALL 30 tool schemas on EVERY call as the native `tools` param — **25,339 chars ≈ 6,334 tokens**, re-sent every iteration, for every provider. The tool catalog appeared up to THREE times: (1) the native `tools` param, (2) a text injection into the system prompt (removed Session 249, `a5c0a0b`), (3) the compact `agent_tool_list` already in the agent system prompt (`prompts.py`, `- {intent}: {description}`). The schemas are **kitchen-sink self-manuals**: `browse` = 17 params covering 10 modes (2,172 chars); `git` = 10 params + 782 chars of prose enumerating every operation/flag (1,943 chars); `delegate` describes 7 target agents inline. This is "the tool feeding itself" — a capable agent already knows git/browsers; paying 6.3k tokens/call to re-teach it is backwards, and on small free tiers (z.ai/GLM, Session 249) the input bloat starves the output budget.
- **Precedent already in the codebase:** the **`skill` tool IS this pattern.** `available_skills_summary()` returns a tiny always-visible index (comma-separated names); `skill(name)` → `get_skill_loader().get(name)` loads the FULL markdown into context ON DEMAND, only when the agent invokes it. Tools should work the same way.
- **Decision (proposed): two-tier tool context.**
  - **Tier 1 — always in context: a LEAN tool index.** Per tool: name + one-line purpose + only the guardrails/behavior that must always hold ("`git` reset --hard is blocked"; "read a file before editing"). Measured: a name+one-liner index is **~2,438 chars ≈ 609 tokens** for all 30 tools — vs 6,334 for the full schemas → **~5,725 tok/call saved (~90%)**.
  - **Tier 2 — on demand: the full tool context.** The detailed parameter schema, modes, and usage examples for a SPECIFIC tool are loaded only when the agent decides to use it — not all 30 manuals every call.
- **Mechanism options (native function-calling needs a schema upfront to generate valid args — so "index only" cannot itself call):**
  - **A. Dynamic schema injection (true progressive disclosure).** `tools` param carries lean meta + core tools; the model signals a tool it wants (a `describe_tool(name)` meta-tool, like `skill`); the NEXT request includes that ONE tool's full schema so the model can call it with valid args. Loads exactly the tools in play. Cost: one extra round-trip per newly-used tool (bad on slow free models).
  - **B. Lean-but-callable schemas (simplest, no protocol change).** Keep all tools in `tools`, but strip each schema to name + one-line purpose + only the non-obvious params + guardrails; delete the tutorial prose. No round-trip; est. ~50-70% of the savings; the model still calls directly.
  - **C. Hybrid.** Core tools (`shell`, `file_task`, `file_write`, `edit_file`, `find_path`) always present as lean-B schemas; long-tail tools (`browse`, `delegate`, `sql`, `csv`, `best_of_n_edit`, `propose_*`) behind on-demand injection (A). Best token/latency balance.
- **Tradeoffs / guardrails:** (1) the descriptions were not pure waste — they carry guardrails AND help WEAK free models pick/format the right call; the cut must KEEP guardrails + disambiguation and drop only the tutorial. (2) Round-trips (A) add latency, which hurts on 0.48 tok/s free models — prefer B/C there. (3) EVERY variant needs LIVE tool-calling verification (right tool, valid args) on a capable-enough model — trimming schemas can regress tool SELECTION on weak models; do not claim a win from unit tests alone.
- **Recommendation / sequencing:** ship **B first** (lean schemas — biggest safe win, no protocol change, measure per-tool), live-verify tool-calling on cerebras or a provider with headroom; then **C** (on-demand for the long tail) if more is needed; reserve **A** (full dynamic) for last. Also collapse the 3 copies to one source of truth (the lean index feeds both the `tools` param and the prompt's `agent_tool_list`).
- **Relates to:** ADR-39 (agent-loop token efficiency — this is the largest remaining per-call line item), B-2026-08-15-14 (tool scoping — subsumed by Tier-1/Tier-2), Session 249 (GLM output starved by input; the `skill` tool as the on-demand precedent).

- **Update (Session 251, Buffy / deepseek-v4-flash):** **option B (lean-but-callable schemas) is now IMPLEMENTED and live-verified** — commits `4cfb0ae`/`106d0d3`/`7ead2ae` (review-41). The native `tools` param went 24,230→15,981 chars (~2,062 tok/call saved, 34%); the in-prompt tool list collapsed onto the same defs as single source of truth. Tool SELECTION verified live on both z.ai/glm-4.5-flash (active weak model) and cerebras — correct tool + valid args, no regression. The 34% is below the sketched 50-70% for B because the remainder is structural (enums/types/required ≈ 8,954 chars) + the guardrail prose this ADR says to keep. **Option C (on-demand long-tail loading) is the standing target** (B-2026-08-16-2) and should be measured against the same live-trace bar.

- **Update (Session 252, Buffy / deepseek-v4-flash):** **option C is now IMPLEMENTED and live-verified** — product commit `6a94328` (review-42). `describe_tool` meta-tool (the `skill`-loader pattern): the 16 long-tail tools left the native `tools` param; `tool_defs_for_call()` composes each iteration's param as scoped-CORE + describe_tool + loaded full schemas (per-run `loaded_tools`, fresh per run). Full-catalog param 16,937→7,851 chars (~54% cut, ~2,272 tok/call; cumulative ~68% vs the 24,230 pre-ADR-40 baseline ≈ the ADR's ~5.7k reclaim). Tool SELECTION live-verified on z.ai/glm-4.5-flash (weak): shell direct (core, no regression) AND describe_tool("skill")→skill("python-testing") end-to-end with self-correction; cerebras: describe_tool first, no guess (follow-up hit the known tokens/min quota, evidence preserved). Final-answer truncation seen in traces proven PRE-EXISTING via stashed-baseline re-run. Option A (full dynamic schema injection) is now unnecessary — C reaches the theoretical reclaim; reserve A only if a future measure shows the long tail still matters.

## ADR-41: Stop disabling GLM's reasoning — re-enable thinking for capable models (2026-08-16)

- **Author:** Claude Code / claude-opus-4-8 (Session 253, research + handover, no code). **Status:** proposed. Directly addresses the user's correction (Session 253): "we are undermining glm-4.5-flash — it's quite capable, I tried it in Co-Pilot [it did a full agentic codebase analysis]. Our agent just needs concrete development to do agentic workflow perfectly."
- **The finding (root cause of the "GLM gives terse/incomplete answers" symptom):** `openai_compat.py` `_add_provider_params` (line ~687) UNCONDITIONALLY disables GLM's reasoning on every z.ai call: `if self._provider_key == "zai": payload["thinking"] = {"type": "disabled"}`. The code comment justifies it by "breaks the **ThinkingDispatcher's** 10s timeout." **That dispatcher was DELETED in Session 239** (legacy intent system removal) — the justification is obsolete. We are switching off a reasoning model's core capability for a component that no longer exists.
- **Evidence it's OUR harness, not the model:**
  - User's live Copilot test: GLM-4.5-Flash ("Analyze codebase") produced a full, structured agentic analysis — explored files, "Optimized tool selection", multi-section architecture overview (even read our `.context`). Thinking ON.
  - Our harness (Sessions 249, 252): the SAME model emits ~28 completion tokens, a terse half-sentence, and stops. Thinking OFF. Both Session 249 (me) and Session 252 (Buffy) mislabeled this as "the free tier / model is weak" — WRONG. Session 252's stashed-baseline re-run showing identical truncation only proved the tool changes didn't cause it; it did NOT prove the model is the cause. The cause is the thinking-disable.
- **Decision:** Re-enable reasoning for models that support it (GLM, and audit DeepSeek/Qwen). Remove the unconditional z.ai thinking-disable; make thinking a per-provider/model policy that DEFAULTS ON for capable reasoning models. Reasoning already has a home: `_extract_content_and_reasoning` (line ~523) splits `reasoning_content` from `content`, and reasoning is streamed to `StreamChunk.thinking` → the ThinkingBlock (lines ~1260/1583/1622/1790). So re-enabling shows reasoning as live thought (ADR-36 transparency) and lets the ANSWER complete after it.
- **The real tradeoff (why it's development, not a one-line flip):** GLM streams many reasoning tokens BEFORE the answer. On the z.ai **free tier at ~0.48 tok/s**, that collides with `PER_CALL_TIMEOUT_SECS = 45.0` (`constants.py:64`) — naively re-enabling could truncate MID-THINKING instead of mid-answer. So the work must: (1) budget thinking (cap reasoning tokens if GLM supports an effort/budget param — INVESTIGATE the z.ai `thinking` API options beyond enabled/disabled) and/or (2) make the per-call timeout thinking-aware (don't count streamed reasoning against the same short budget as a hung call), and (3) keep the "hung model" protection the disable originally bought (a model that only thinks and never answers must still fail fast).
- **Consequences / plan (for the implementing session):** see backlog **B-2026-08-16-3**. MUST live-verify a before/after on z.ai/GLM (terse-with-thinking-OFF vs complete-with-thinking-ON) on a real turn — do NOT claim the fix from theory or unit tests (z.ai free tier rate-limits during heavy testing; use an isolated `LOCALMIND_HOME`, never touch port 8000, never print keys).
- **Relates to:** ADR-36 (Thinker/transparency — reasoning belongs in the ThinkingBlock), ADR-39/40 (token efficiency — orthogonal; those cut INPUT, this restores OUTPUT quality), Sessions 249/252 (the mislabeled "weak model" conclusion this corrects). **Standing user preference reaffirmed:** "use any capable model; a model failing is OUR bug" — see `user/preferences.md`.

- **Update (Session 254, Buffy / deepseek-v4-flash):** **IMPLEMENTED and live-verified** — product commit pending (review-44). Removed the unconditional z.ai thinking-disable; thinking is now a per-provider policy that DEFAULTS ON for z.ai/GLM (`LOCALMIND_THINKING=disabled` opts out; GLM-5.3+ is never disabled — z.ai rejects `thinking.type=disabled` for it; `LOCALMIND_REASONING_EFFORT` applies to GLM-5.2+ only, per z.ai docs — GLM-4.5-flash does NOT support `reasoning_effort`, so no effort/budget param exists for it, only enabled/disabled). Thinking-aware budgets: `REASONING_PER_CALL_TIMEOUT_SECS` 45s→180s (`LOCALMIND_REASONING_TIMEOUT_SECS`) and `REASONING_PLAN_TIMEOUT_SECS` 8s/10s→30s (`LOCALMIND_REASONING_PLAN_TIMEOUT_SECS`) via `_plan_timeout_for()`/`_orchestrator_timeout_for()` — the 8s init cap fired mid-thought live on GLM ("initialization timed out after 8s") before this. Loop now forwards `StreamChunk.thinking` on ALL final-answer paths (MiniMax buffer, mid-stream, `_force_final_answer`) — previously dropped, reasoning never reached the ThinkingBlock on the tail of a turn. **Live before/after on z.ai/glm-4.5-flash (isolated `LOCALMIND_HOME`, port 8765):** BEFORE (thinking OFF) — 91-char terse truncated answer, 0 reasoning streamed; AFTER (thinking ON) — 507-926 chars of live reasoning streamed to the ThinkingBlock and a complete 456-char answer with no empty-response and no init timeout (a second run hit free-tier throttling mid-think; raw z.ai API with thinking ON returns complete answers, confirming provider-side health). Full suite 1,792 pass (4 pre-existing env-gated shell fails).

## ADR-42: The Thinker as a first-class module — `core/agent/thinker/` (2026-08-16)

- **Author:** Claude Code / claude-opus-4-8 (Session 259). **Status:** module BUILT + unit-tested (`cbd1bd4`); loop integration + live validation PENDING. Implements ADR-38 (mid-loop analyst on gathered evidence); pairs with ADR-41 (native reasoning re-enabled). User directive: "build it from the ground up — a thinking module e.g. `/core/agent/thinker/` … the Thinker is the backbone of the agent."
- **The failure this replaces (confirmed live in code, Session 253/259):** there was NO Thinker. The visible "thought" was `render_understanding()` returning the init call's `objective` one-liner — produced UPFRONT, before any tool ran, so it could only restate the request ("echoes the user's message as thought"). `grep` of `loop.py` found no mid-loop reasoning step; only rebuild Step 0 ever shipped. Real model reasoning was also muted until ADR-41.
- **Architecture (module, `backend/src/core/agent/thinker/`):**
  - `contract.py` — `Evidence` (objective + user_message + gathered `observations` + last_action + iteration; `has_evidence` gate — a consult is only meaningful once real evidence exists), `Ambiguity` (text + a `default` to proceed on, ADR-36), `ThinkerAnalysis` (streamed `reasoning` + `facts` + `ambiguities` + `next_step` + confidence; `is_empty` fallback signal).
  - `prompt.py` — the Thinker system prompt: SILENT + READ-ONLY (no user reply, no tools); reason on the ACTUAL evidence by name; a step beyond the obvious; separate facts from ambiguities+defaults; ONE concrete next_step; invent nothing. Prose first (streamed), then a JSON tail.
  - `parse.py` — `parse_thinker_analysis()`: fail-safe (balanced-JSON extractor + prose/JSON split); a malformed or JSON-less consult still yields a usable analysis so a bad consult never blocks the loop.
  - `thinker.py` — `Thinker.consult(evidence, adapter)`: async-generator that streams live reasoning as `StreamChunk(thinking=…)` to the ThinkingBlock, STOPS surfacing at the first JSON marker (structure ≠ thought), attaches `ThinkerAnalysis` to `last_analysis` + the final chunk's metadata; bounded by a dedicated reasoning timeout (`_with_timeout`); never crashes a turn. `analyze()` = non-streaming convenience.
- **Why evidence-first (the core principle):** you cannot think meaningfully before you look — reasoning on the raw request can only paraphrase it. The Thinker runs AFTER at least one evidence-gathering step, on the real observations, which is what turns "the user wants their CV" into "found Tisone_CV.pdf + an older resume, picking the newer; the JD wants backend, so emphasize the API work."
- **Integration plan (NEXT session — the delicate, live-validated part):**
  1. In `AgentLoop.run` (`loop.py`), after the FIRST tool result lands and its observation is in `observation_log`, and BEFORE the next-action decision, build `Evidence(objective=initialization.objective, user_message=…, observations=observation_log, last_action=<tool>, iteration=i)` and, if `evidence.has_evidence`, run `Thinker.consult`.
  2. Pipe consult's `chunk.thinking` to the existing `thinking_token` SSE (same channel `render_understanding` used) so the ThinkingBlock shows REAL reasoning; on `done`, read `last_analysis`.
  3. Feed the analysis forward: inject a compact `next_step`/`facts`/`ambiguities(+defaults)` block into the loop context so the model's next action is shaped by the Thinker (resolve ambiguity on the default per ADR-36, don't block). Replace the upfront-objective "understanding" surface with this.
  4. Gate it: only on the needs-tools tier (ADR-37), only when `localmind_thinking != "disabled"`, bounded by `localmind_reasoning_plan_timeout_secs` (ADR-41). Keep the fail-fast: an empty/timed-out consult → the agent proceeds on its own next step (never hang, never block).
- **HARD constraint (ADR-38, reaffirmed):** the Thinker is the agent's backbone — the loop wiring MUST be live-validated on a real model (native reasoning ON via ADR-41; z.ai/GLM is now capable, cerebras for headroom) with a before/after trace showing the ThinkingBlock carrying REAL evidence-based reasoning (not the echo) and the analysis changing the next step. Do NOT claim the Thinker works end-to-end from unit tests alone.
- **Relates to:** ADR-36 (Thinker/transparency + proceed-on-default), ADR-37 (three-tier; only tier-3 consults), ADR-38 (the mid-loop-analyst design this implements), ADR-41 (native reasoning — the Thinker streams real thought now that it's un-muted). Supersedes the `render_understanding` objective one-liner as "the thought."

### ADR-42 — WIRED + live-verified (Session 260, `981769a`)
- Integrated `Thinker.consult` into `AgentLoop.run` after the first tool evidence: gated once/turn, tool-capable intents, `active_adapter.thinking_enabled`, reasoning-plan-timeout-bounded, fail-safe (never blocks a turn). Reasoning streams to `thinking_token`; the analysis is injected via `_thinker_context_block` to shape the next action; obs events `agent_thinker_start`/`agent_thinker_done`.
- **Live (z.ai/glm-4.5-flash, thinking ON):** after `ls /Users/bao/Code` the Thinker reasoned on the ACTUAL output — "one .md file (context-workflow-quick.md), but the user asked for ALL, so recursive search needed" → `next_step="recursive shell find … and its subdirectories"`, facts=2, ambiguities=1. Genuine evidence-based reasoning streamed to the ThinkingBlock — the echo is gone. Suite 1,812 passed.
- **HONEST LIMIT (owed follow-ups):** the turn still ended with an EMPTY final answer — the model returned empty content after streaming reasoning (the SEPARATE pre-existing empty-after-reasoning issue, `loop.py:3174` recovery from Session 256/257), so the recursive next_step was never executed. The Thinker fixes REASONING, not final-answer synthesis (B-2026-08-15-11). Still OWED: (1) a Thinker-OFF baseline on the same task to prove the Thinker doesn't worsen the empty-after-reasoning; (2) fix the empty-after-reasoning/synthesis so the Thinker's next_step actually gets acted on and a complete answer lands.

## ADR-43: Runtime tool efficiency — tools as bounded helpers, not agents (phase 3 of agent → thinker → tools) (2026-08-16)

- **Status:** RESEARCH accepted; implementation pending (B-2026-08-16-4/5/6). Author: Claude Code / claude-opus-4-8 (Session 270). Full research: **review-50**. User directive: "Create research context on tools optimization. Optimization has been sequential (agent → thinker → tools)."
- **Where this sits:** optimization ran in sequence — **Agent** (loop/runtime: ADR-37/39, caching, empty-after-reasoning recovery) → **Thinker** (reasoning backbone: ADR-42, evidence-first, anchored on the real request S263, thinking levels S262) → **Tools** (this ADR). The loop drives well and the reasoning decides well; the tools it reaches for are still uneven.
- **The gap (distinct from ADR-40):** a tool costs the agent on TWO axes. **INPUT** = its schema in the `tools` param every call — largely SOLVED by ADR-40 (lean schemas + `describe_tool` on-demand, ~68% cut). **RUNTIME** = what it costs when it runs: (a) output-context tokens injected into the loop every subsequent turn, and (b) latency. The runtime axis — chiefly output-context — is UNTOUCHED. This ADR is ADR-40's sibling on the other side of the call.
- **Principle (the user's north star):** a tool is a bounded, single-purpose helper that returns a summary sized for a model's working memory — not a raw pipe (arbitrary output) and not an open-ended explorer (agent-sized work). "Tools are helpers of the agent and tools, not agents; file_finder is more efficient than raw shell."
- **The disease in miniature (grounded):** `find_path` returns a bounded CATALOG (total count + folder/ext histograms + a small page; the model never sees the raw walk). `shell` (shell.py:760) returns the ENTIRE raw stdout — no cap, no summary — so an `ls -R`/`find`/`Get-ChildItem`/`cat` dump lands whole in context and rides every later turn. That asymmetry (helper vs raw pipe) is the disease; it was the FUEL behind the S262 "context too long" failure (unbounded thinking was the trigger).
- **Observed inefficiencies (live traces):** (1) exploratory `ls`/`Get-ChildItem` BEFORE a create task (needs `file_write`, not discovery — and it fed the Thinker irrelevant `.lnk` evidence in S263); (2) `shell` used for file DISCOVERY (that's `find_path`'s bounded job; raw shell also invites OS-specific command bugs); (3) a post-write read-back self-verify (`file_task`) that DUPLICATES the loop's own write verification — a redundant call that hit the S264 Windows path bug and cascaded to `empty_response`; (4) verbose output accumulating across turns → overflow on small free-tier contexts.
- **Tool taxonomy (by shape):** bounded helpers already right (`find_path`, `calculator`, `json`/`csv`/`sql`, `file_write`/`file_task`/`edit_file`, `web_search`, `sysinfo`); raw/unbounded but fixable (`shell` [top offender], `code_exec`, `web_fetch`, `git`, `process_tool`); agent-like by nature (`browser_agent`, `delegate`/`delegate_parallel`/`delegate_inline`, `best_of_n_edit`) — heavy legitimately; the lever there is SELECTION + output bounding, not removal.
- **Levers (options, not yet decided):** L1 bound every tool's OUTPUT (give raw-dump tools the find_path treatment — cap+elide/summarize, full output on demand via the describe_tool/skill precedent; start with `shell`); L2 right-tool steering (discovery→find_path, create→file_write, structured→json/csv/sql — via ADR-40 guardrail prose and/or a Thinker hint); L3 drop the redundant read-back (fold confirmation into file_write's result); L4 a uniform bounded observation contract (`summary`+`metadata`+optional detail-handle enforced once in the ingestion path / ToolResult); L5 (secondary) latency budgets on the heavy tools.
- **Recommended sequencing:** 3a = L1 on `shell` first (biggest, safest; kills the "context too long" class); 3b = L2+L3 (cheap steering + drop the redundant verify — fixes the user-flagged patterns); 3c = L4 (structural finish; fold L1 into it).
- **Live-verify bar (non-negotiable, per ADR-40):** each phase needs a BEFORE/AFTER live trace on z.ai/glm-4.5-flash proving output-context tokens dropped AND the task still completes with the right tool + valid args (reshaping output can regress weak models; unit tests are not enough). Isolated `LOCALMIND_HOME`; never touch port 8000; never print keys.
- **Relates to:** ADR-40 (tool SCHEMA input tokens — INPUT-side sibling), ADR-37/39 (loop), ADR-42 (Thinker as candidate tool pre-selector), S262 (the failure this prevents), S264 (read-back symptom).

- **CORRECTION (Session 272, Claude Code):** ADR-43's lever **L1 (bound tool output) is ALREADY IMPLEMENTED** — the "shell returns raw uncapped stdout" premise was a MISREAD (cited shell.py:760 without tracing that its `content` comes from a `BoundedOutputBuffer`). Verified: `shell` caps to `TOOL_OUTPUT_MAX`=4000 chars head+tail (`_capture_process_output`, shell.py:226; empirically 250k→4000 with marker); code_exec/web_fetch/git/process_tool bound too; and a SECOND-stage `_truncate_observation(…, OBS_LOG_MAX_CHARS=2000)` bounds every observation entering the loop. The S262 "context too long" was unbounded THINKING (fixed S262 via reasoning_effort), not shell output. **The verified, real work is L2 (steering) + L3 (redundant read-back) — B-2026-08-16-5.** L1 is closed with no code. (Lesson: this is the "check the harness/verify before claiming" rule that S253 already taught — applied to my own research this time.)

- **ADDITION (Session 274, Claude Code) — todo_write, the agent's live-todo control surface:** delivered `todo_write` (`506f958`, review-51), a first-class CORE tool embodying this ADR's principle (a fast single-purpose helper — parse/normalize/return — like web_search). The UI Todos panel was a PASSIVE projection of the LLM's parsed plan (plan-required intents only, not agent-controllable; a 3-step task emitted zero todo events live). The agent now writes the FULL checklist and the loop's `_emit_todo_write_events` emits the todo_cleared+todo_created obs events the SSE bridge + frontend already render (status carried through so in_progress shows). Loop owns emission (tools can't reach ObsCollector across asyncio.wait_for — same as describe_tool). LIVE-VERIFIED on glm-4.5-flash (create + in_progress update; 0 validation errors). Bug the live trace caught: `_extract_tool_input` stringified the todos array as a Python-repr (invalid JSON) — unit tests passed while the real agent path was broken. Still open: B-2026-08-16-5 (L2 steering + L3 redundant read-back).

- **ADR-41 UPDATE (Session 276, B-7) — reasoning is now provider-generic, not zai-only:** ADR-41 re-enabled GLM reasoning but the plumbing stayed z.ai-specific. Two gaps closed (`b3f489d`, review-52): (1) `_extract_content_and_reasoning` only read `reasoning_content`/`<think>` — a live probe showed cerebras/gpt-oss-120b streams reasoning in a `reasoning` field, now read too, so any capable model's thinking routes to the ThinkingBlock not chat; (2) `thinking_enabled` was False for all non-zai, and the loop gates the Thinker consult + thinking-aware timeout on it — so the Thinker (ADR-42) never ran outside z.ai. Now True for all capable providers (z.ai keeps its GLM-5.3 force-enabled logic; tunable via LOCALMIND_THINKING). The z.ai `thinking` REQUEST param stays gated to zai. LIVE-VERIFIED on cerebras/gpt-oss-120b (Thinker consulted, reasoning to thinking channel, model acted). This is the "use any capable model; a model failing is OUR bug" principle applied to the reasoning path.

---
## ADR-44: Detect Ollama context window from /api/show; user-configurable num_ctx (2026-08-17)
- **Status:** accepted
- **Context:** LocalMind hardcoded per-model context windows in a static
  `_MODEL_CONTEXT_WINDOWS` table (adapters/ollama.py). Any model absent from it
  (e.g. phi4-mini:latest, a common pull) fell to the 8192 default — so the
  context meter read `5248/8192 = 64%` on a near-empty chat and the agent
  budgeted a 128K model at 8K. The table is unmaintainable (every new model =
  a code edit) and wrong-by-default.
- **Decision:** the model's declared context window is a property of its
  weights, so ASK the runtime for it: `POST /api/show` → the `<arch>.context_length`
  field, cached per-model, primed from the request runtime and `/api/models`
  before the sync `context_window` property is read. The static table is now
  only a fallback when Ollama is unreachable. Separately, `num_ctx` (what we
  actually budget / send) is user-configurable via `ollama_num_ctx`
  (`OLLAMA_NUM_CTX` / Settings modal): 0 = auto (resource-sane tier cap over the
  real window), >0 = explicit override clamped to capacity. The size-tier
  heuristic recognises tag-free "mini" models so their default num_ctx stays
  8192 rather than ballooning to the full window on weak hardware.
- **Consequences:** the declared window (meter) and the budgeted num_ctx are now
  two distinct values — `context_window` = real capacity, `effective_context_window`
  = budgeted/allocated. Future agents: don't re-hardcode windows in the table;
  it's a fallback, not the source. `prime_context_window()` is async and
  best-effort — the sync properties degrade to table→8192 if it hasn't run. A
  num_ctx override must always be clamped to the declared window.

---
## ADR-45: Slow local models need the full generation budget for the parent init call (2026-08-17)
- **Status:** accepted (extends ADR-41 / S288 slow_provider)
- **Context:** the parent init is "classify-only" for a fast model, but its
  `direct` decision includes the user-facing `response` (e.g. the greeting
  itself), which the model must GENERATE before the init stream ends. On a slow
  local model (phi4-mini ~0.17 tok/s) even a short reply exceeds the 30s plan
  budget, so the init timed out, `parse_initialization("")` fell open to
  EXECUTE, and every "Hi" cascaded into the full tool loop and burned the 180s
  wall-clock. S288 fixed the per-call chat timeout for slow providers but left
  the init/plan timeout at the short plan budget.
- **Decision:** `_plan_timeout_for` grants slow providers (not thinking) the
  generous `ollama_timeout_chat` budget, floored at the reasoning plan budget —
  the init is effectively a full generation for a slow model, not a quick plan.
  Stays inside model-owned agentic control: the fix is a timeout, NOT a revival
  of prompt-shaped intent routing (the user explicitly rejected that).
- **Consequences:** a greeting on a slow local model completes in ONE init call
  (`direct`, no tools). The remaining risk is genuine MISCLASSIFICATION (a weak
  model emitting `execute` for "Hi") rather than a timeout — that is a
  model-capability problem, addressed by progressive tool-schema disclosure
  (B-2026-08-17-1) and/or a stronger local model, not by more timeout. Future
  agents: for slow local providers, the init call is a first-class generation —
  budget it like a chat call, not like a plan.

---
## ADR-46: The tool loop is opt-in — execute requires an explicit decision (2026-08-17)
- **Status:** accepted (supersedes the fail-open-to-execute behavior; makes
  ADR-45's slow-provider init timeout secondary)
- **Context:** the parent's classify step (`parse_initialization`) failed open to
  `execute` on any output it couldn't parse. The tool loop — the most expensive,
  unbounded, and only state-changing path — was therefore the DEFAULT whenever the
  classification was unclear, for EVERY model. Capable models masked it (clean
  JSON); weak/loaded/truncated cases fell into the loop. "Hi" hanging on phi4-mini
  (execute, 0 tokens, 247s) was the visible instance of a universal fragility.
  S289 mis-treated it as a local-model timeout symptom; the user corrected the
  framing (fix the root, model/env-agnostic — see preferences.md).
- **Decision:** EXECUTE IS OPT-IN. The tool loop runs only on an explicit,
  parseable `mode:"execute"`. Every uncertain outcome — unparseable output, an
  unknown mode, a `direct` with no answer, a `clarify` with no question, an init
  timeout/error — resolves to a bounded DIRECT answer, built from the model's own
  output (`_salvage_response`; a model that ignores the JSON contract has usually
  just answered in prose, and that prose is the answer). Direct turns also
  propagate the init call's real provider usage, and the init decision is logged
  (mode + confidence + raw snippet) for observability.
- **Consequences:** no model — 3B local or frontier cloud — is ever dragged into
  a tool loop it didn't ask for. Tradeoff: a REAL task whose execute-JSON is
  unparseable now under-acts (answers in prose) instead of hanging — recoverable
  by rephrasing, and far safer than a hang or a wrong tool action. To cut those
  false-directs on weak models, constrain the classify output to valid JSON
  (B-2026-08-17-3) — model-agnostic, gated on the new init log confirming
  parse-failure is the real cause. NEVER restore fail-open-to-execute: the loop
  is opt-in.

- **IMPLEMENTATION START (Session 293, Claude Code) — L3 (drop the redundant post-write read-back):** `file_write`'s success result was a terse `"{name} - {parent}/"` path echo — it read like an UNconfirmed path and invited the model to spend a follow-up `file_task` read-back to verify (the redundant call ADR-43 flags; it also hit the S264 path bug → empty_response). Changed it to an AFFIRMATIVE, self-contained confirmation: `"Wrote N bytes (M lines) to <full path> — saved and verified. Do not read it back to check; the write is confirmed."` (metadata unchanged — structured consumers use `metadata.path`, not the prose). Result-shape unit-tested (`tests/tools/test_file_writer_l3.py`). LIVE STATUS — HONEST/INCONCLUSIVE: BEFORE trace (glm-4.5-flash create task) showed the model reaching for `file_task` (a READ tool) on a CREATE task (the L2 wrong-tool pattern); the AFTER trace showed the model using `file_write` with NO `file_task` read-back (the intended L3 effect) — BUT that trace was CONFOUNDED and did not cleanly complete: (a) a path-resolution quirk — `resolve_write_path` prepended the home dir to an absolute `/private/tmp/...` test path → `/Users/bao/private/tmp/...`, so the file landed in the LOCALMIND_HOME scratch and the loop's OWN read-back verification (checking the original path) emitted `[GROUNDING CHECK FAILED]`; (b) the provider rate-limited the final synthesis. So L3's code change is SAFE + shape-verified, but a CLEAN behavioral before/after is still owed (use a normal home-relative path, e.g. Desktop, and a non-rate-limited window; spot-check phi4-mini). NOTE for next session: the loop does its OWN post-write read-back verification (the `[VERIFICATION]/[GROUNDING CHECK]` block) — L3's deeper win may be making THAT loop-side check trust the write result instead of re-reading, not just steering the model. Also logged: the `/private/tmp` path-prepend quirk (B-2026-08-17-6). Next: finish L3 verification, then L2 steering + L4 uniform observation contract.

- **L2 DONE + B-2026-08-17-6 (Session 294, multiagent):** L2 right-tool steering — the CREATE→file_write gap was the trio asymmetry (shell→"use file_write", file_write→"use file_task", file_task→said NOTHING), so a model name-matching "file task" for "create a file" got zero correction; the parent path (pinned to ANALYZE, uses base.md not prompts.py) never sees the correct SHELL-persona steering. Fix: one clause in the file_task schema ("READ-ONLY (to create/write a file use file_write)"), kept under the lean core-catalog budget while preserving the pinned guardrails. Live-verified (glm-4.5-flash): model used file_write, no file_task. ALSO fixed the write-path bug the L3 trace surfaced (B-2026-08-17-6): resolve_write_path honors native-absolute paths; the loop's grounding + _verify_tool_result read back tool_result.metadata["path"] (where the write landed) not the raw arg — this is the "loop trusts the write result" idea from the L3 note, applied to the loop-side verification (also fixes false failures on timestamp-renamed documents). REMAINING: L2 secondary (discovery→find_path + "don't exploratory-shell before create" — the parent's base.md lacks it; the trace still showed 4 shell calls); a clean L3 before/after on a READ-ALLOWED path (this trace's residual grounding warning was a /private/tmp read-allowlist artifact → B-2026-08-17-7); L4 uniform observation contract.

---
## ADR-47: Single-agent-first — the Parent Agent is the whole autonomous layer this phase; delegation is deferred, not extended (2026-08-18)
- **Author:** Claude Code / claude-opus-4-8 (Session 297)
- **Status:** accepted (direction-setting; reconciles the shipped delegation
  surface against a user-provided north-star spec — see
  `docs/parent-agent-spec.md`)
- **Context:** the user handed a full "Parent Agent — Complete Functional
  Architecture & Development Specification" and asked to memorize/document it.
  The spec (§1, §9, §36) is explicit: the current phase builds ONE strong
  single-agent runtime — the Parent Agent that runs the closed loop (understand →
  diagnose → plan → act → observe → assess → recover → verify → complete) — and
  **specialist agents, delegation, and multi-agent orchestration are out of
  scope until that single-agent foundation is proven reliable.** But the codebase
  has already run ahead of this: `backend/src/core/agent/delegation.py`,
  `tools/delegate.py`, `tools/delegate_parallel.py` (262 refs) ship today, and
  `docs/ARCHITECTURE.md` advertises `delegate / delegate_parallel → isolated
  specialized child agents`. So the spec and the build genuinely disagree about
  whether delegation belongs to "now."
- **Decision:** adopt the spec as the phase's north star and record the
  divergence honestly rather than silently resolving it. (1) The spec lives
  in-repo verbatim at `docs/parent-agent-spec.md` with a Reconciliation header.
  (2) The already-accepted ADRs ADR-33/34/36/37/38/42/43/45/46 are recognized as
  incremental realizations of this spec — the loop, the Thinker-as-silent-analyst,
  tools-as-bounded-helpers, and execute-is-opt-in are exactly the spec's
  principles. (3) The existing delegation surface is treated as **dormant /
  ahead-of-roadmap, NOT to be extended** this phase; the choice between keeping it
  dormant-and-unadvertised, removing it to match the spec, or consciously
  declaring the phase over is left to the user (backlogged B-2026-08-18-1). NO
  delegation code was changed by this documentation session.
- **Consequences:** future sessions have one authoritative statement of the
  target architecture and will not read `docs/ARCHITECTURE.md`'s delegate note as
  a current-phase endorsement (a scope callout now points here + at the spec).
  The quality bar for "done this phase" is the spec's single-agent lifecycle
  (§43: reliable state, appropriate context, controlled tool access, meaningful
  observation, dynamic replanning, bounded retries, explicit verification, safe
  escalation) — not new specialist capabilities. Do NOT build new delegation
  features or advertise child-agent orchestration as current until the user
  resolves B-2026-08-18-1. This ADR is direction, not a code change; it does not
  supersede any prior ADR — it frames them.
- **ADDENDUM (Session 297, peer-verified via colab agent Buffy/Freebuff + re-checked by me):**
  the "delegation shipped ahead of roadmap" framing above UNDERSTATES it. The
  whole multi-agent layer the spec defers (§36) is not just present — it is the
  LIVE runtime: `ParentAgent` is the request entry point
  (`core/agent_runtime.py:667`), **11 specialist agents are registered**
  (`backend/src/agents/{research,reviewer,analyst,direct,browser,parent,editor_selector,debugger,verifier,coding,context_pruner}` + `registry.py`),
  the full machinery is wired (`delegate`, `delegate_parallel`, `delegate_inline`,
  `best_of_n_edit`), and `agents/selection.py:26` is explicitly demoted to "not
  used for request-time routing … UI metadata" (ADR-8 phases 3–4 done). So the
  spec is best read not as a build roadmap but as a **quality bar** — esp. §40's
  12 criteria (goal accuracy, tool selection, verification, honest completion) —
  for a system that has already run past this phase's stated scope. This sharpens
  B-2026-08-18-1 from "add delegation later?" to "the multi-agent layer exists and
  is live — freeze/hide it, remove it, or accept we're ahead and steer remaining
  work toward §40 hardening."
- **IDENTITY CLARIFICATION (Session 298, user directive "it's LocalMind"):** the
  agent's user-facing IDENTITY (spec §23) is **LocalMind**; "Parent Agent" is only
  the spec's architectural ROLE label (spec §2: "describes its architectural role
  as the root agent, not an indication that child agents already exist"). The code
  already encodes this — `agents/parent/context_builder.py`: "You are the
  user-facing LocalMind agent." Recorded as an identity note in
  `docs/parent-agent-spec.md` (reconciliation header) + `docs/ARCHITECTURE.md`
  scope callout (`42df924`). Bearing on B-2026-08-18-1: whichever delegation path
  is chosen, the single user-facing identity stays LocalMind — the specialists are
  internal workers, never user-facing.

---
## ADR-48: Resolve B-2026-08-18-1 — accept-and-harden (LocalMind has passed the single-agent phase; the spec is now a quality bar) (2026-08-18)
- **Author:** Claude Code / claude-opus-4-8 (Session 298), on the user's directive ("go" — adopt the recommended option (c))
- **Status:** accepted (resolves the open decision framed by ADR-47 / B-2026-08-18-1; does NOT supersede ADR-47 — it answers the question ADR-47 raised)
- **Context:** ADR-47 recorded that the Parent Agent spec (`docs/parent-agent-spec.md`) scopes the current phase to a single strong agent and defers delegation (spec §36), while the codebase already ships the full multi-agent runtime as live (11 registered specialists, `delegate`/`delegate_parallel`/`delegate_inline`/`best_of_n_edit`, `selection.py` demoted to UI metadata). review-65/66 then showed the spec's §40/§43 quality bar is **largely already met by the parent loop itself** (8 STRONG / 4 PARTIAL after the review-65 correction), and the one real parent gap — the completion-verification floor — was closed this session (`fd48db5`, B-2026-08-18-2). So removing/freezing delegation would buy no §40 improvement while costing a large, risky diff.
- **Decision:** **option (c) — accept-and-harden.** LocalMind consciously accepts that it has advanced past the spec's stated single-agent-first phase. The wired multi-agent runtime stays first-class (nothing removed, hidden, or disabled). The Parent Agent spec is retained not as a build roadmap but as the standing **quality bar** — especially §40's 12 criteria (goal accuracy, planning, tool selection, execution, observation, adaptability, recovery, verification, state integrity, safety, efficiency, completion) and §43's success conditions. The spec's §36 "specialists/delegation out of scope this phase" is recorded as **superseded by lived reality**, not deleted (the author's spec body stays verbatim; the reconciliation header and this ADR carry the supersession).
- **Consequences:** (1) remaining agent work is measured against §40, not against "is it still single-agent." The open hardening targets are the 4 review-65 PARTIALs — efficiency (B-2026-08-17-8..12, the biggest), tool-selection L2-secondary, `classify_failure` recovery (review-42), read-blocked grounding (B-2026-08-17-7). (2) The single user-facing identity stays **LocalMind**; specialists are internal workers, never user-facing (ADR-47 identity note). (3) Delegation may now be maintained/extended as a first-class capability — the ADR-47 "do not extend delegation until decided" hold is **lifted**. (4) This is reversible at the decision level: it changed no code; a future session may revisit if single-agent reliability proves insufficient. NOTE: adopted on the user's one-word "go" following an explicit (c) recommendation — a decision record, deliberately not a destructive change, so it is cheaply amended if the intent was different.

---
## ADR-49: Parent emits an upfront todo plan in init — revises ADR-38 for the checklist (2026-08-18)
- **Author:** Claude Code / claude-opus-4-8 (Session 298), on the user's directive (todos = the actual steps planned before, followed one after another until finished)
- **Status:** accepted (revises ADR-38 narrowly — for the user-visible todo checklist only; the rest of ADR-38's evidence-first loop stands)
- **Context:** the user reported the Todos panel stays empty and the "Plan ready" phase shows no steps. Root cause: ADR-37/38 deliberately made the parent init CLASSIFY-ONLY ("the plan emerges from the loop"), so the parent path never produced or emitted plan steps (the plan-step→todo emission lived only in the non-parent plan-stream branch). The user wants the opposite for transparency: an upfront checklist the agent follows one step at a time (able to reorder/skip) until done. Prompt-steering the model to call `todo_write` first was tried and LIVE-FAILED on glm-4.5-flash (it ignored the instruction, 0 todo_write calls) — weak models won't self-plan from a prompt, so the plan must be harness-produced.
- **Decision:** the parent's EXISTING init call (no extra LLM call) now also returns an ordered `plan` array for a multi-step `execute` task. `InitializationDecision.plan_steps` carries it (bounded ≤6, sanitized). The loop emits those steps as todos up front (`todo_created`, pending) and the existing `_advance_plan_on_narration` cursor checks each off as the agent works. Empty for direct/clarify/single-step. This is a NARROW revision of ADR-38 — only re-adding an upfront plan for the visible checklist; the loop still gathers real evidence and may reorder/skip/add steps (the plan is a guide, not a rigid contract), so ADR-38's "don't fake autonomy / don't commit a blind rigid plan" concern is respected (the model plans from the task, the loop adapts).
- **Consequences:** the Todos panel now populates and advances for multi-step parent turns; the plan phase has real content. Cost: the init prompt grew ~260 chars (2761 total, budget bumped 2500→3000; still far below the old monolithic plan-stream) and the init response carries a short plan. LIVE-VERIFIED (glm-4.5-flash): "weather in Kitengela" plans 3 concrete steps, emits them as todos, marks plan-0/1/2 completed as it runs. Risk: a weak model may emit a thin or slightly-off plan — acceptable, since the loop adapts and an empty/junk plan just yields no todos (unchanged behavior). Do NOT let the plan become a rigid gate that blocks adaptation (that would resurrect the ADR-38 problem).

---
## ADR-50: General model-agnostic tool-error recovery (spec §17/§28) — one path, not per-tool patches (2026-08-19)
- **Author:** Claude Code / claude-opus-4-8 (Session 298), after the user challenged the symptom-vs-root-cause pattern.
- **Status:** accepted
- **Context:** the user kept hitting the same failure shape — a tool errors, the weak model can't recover, the turn dead-ends in `empty_response` (code_exec run-a-file, classify flake, a failed search). Each was fixed as a POINT patch for that tool. The user (rightly, per `user/preferences.md` + `feedback-fix-agent-model-env-agnostic`) called out that this is symptom-fixing. ROOT CAUSE: when a tool fails, the loop surfaced only `[Tool 'X' returned error_type='...']` (loop.py:2529/3089) and left recovery to the model — model-DEPENDENT, so weak models flounder.
- **Decision:** a GENERAL, model-agnostic recovery layer. `tool_error_recovery_directive(tool, error_type)` classifies every `error_type` the tools/contracts emit into a spec-§28 class (permission / input / no-result / transient / hard-limit / internal) and returns a concrete next step, appended as `[RECOVERY]: …` to every failed tool observation. The harness now handles ALL tool errors uniformly instead of per-tool special-casing. Structural guards keep it bounded: `dispatch_with_retry` never retries permission errors; `same_tool_failure_streak` (CAP=2) forces an honest stop on repeats; the completion floor (ADR-…/B-2026-08-18-2) blocks false success.
- **Consequences:** new per-tool dead-ends are covered by default (add the tool's error_type to the right class, don't write a new patch). HONEST scope: the directive is still read by the model, so recovery isn't 100% guaranteed on the weakest models — but the harness now does its part generally (classify + direct every error), which is the model-agnostic root fix; structural auto-correction (like code_exec→shell) remains the stronger option for KNOWN mis-uses and can be added per-pattern. Do NOT go back to bare raw error surfacing.

---
## ADR-51: Generic direct-conversation boundary at the runtime seam (2026-08-20)
- **Author:** Buffy / openai/gpt-5.6-luna (Session 301), after the user rejected a phrase-specific capability response as symptom-fixing.
- **Status:** accepted; supersedes ADR-34 principle 1 only for clearly conversational, no-tool turns.
- **Context:** the live runtime had made the parent initializer the interpretation-and-answer boundary for every turn. The initializer's constrained JSON meta-call was slow and generic on real GLM, while the repository already had a normal history-aware direct-chat helper that the live runtime did not invoke. Adding a capability phrase map fixed one transcript, not the boundary.
- **Decision:** route only conservative, structurally conversational turns (including short history-backed follow-ups) through one generic direct-chat call with recent history. Do not add phrase-to-answer maps or capability-specific response branches. Any action/evidence signal, attachment, explicit tool restriction, or ambiguous shape remains on the parent initializer/tool loop. The gate is a safety boundary, not a catalog of intents.
- **Evidence:** real isolated z.ai/glm-4.5-flash traces covered generic self-description, emotional conversation, explanation, and the exact `What can you do?` → `Like what` flow. These used the same generic direct path and produced contextual answers. A real file-list request stayed `fast_path=false`, entered `mode=execute`, made shell calls, adapted paths, and returned actual evidence. Full CI finished with 1996 backend passes / 2 skipped.
- **Consequences:** direct conversational turns avoid the redundant initializer/tool metadata cost, while evidence-requiring work preserves the parent closed loop. Provider generation latency remains model-dependent (~10–16s on this free GLM trace); this ADR does not claim zero-latency model-backed conversation. Every future change to this boundary requires the isolated real-provider before/after trace from `system/live-testing.md` plus parent/tool safety verification.

---
## ADR-52: Warm Parent Kernel and per-session context (2026-08-20)
- **Author:** Buffy / openai/gpt-5.6-luna, proposed from the user's architectural plan.
- **Status:** proposed — phase 1 scope selected, implementation not started.
- **Problem:** LocalMind currently performs parent initialization as a model call for each turn. The user proposed initializing the parent once during server boot so it is continuously ready, rather than repeatedly booting its identity/operating context.
- **Decision direction:** create a server-lifetime immutable `ParentKernel` containing LocalMind identity/instructions, safety/playbooks, agent registry, tool registry and lean schemas, active provider/model adapter, provider metadata, and model-readiness state. Create a separate `ParentSession` per chat containing history, rolling objective/summary, recent verified evidence, cwd, memory/failure recall, todos, and steering/abort state. Each turn supplies only a `TurnContext` delta: latest message, attachments, workspace snapshot, and new tool evidence.
- **Phase 1:** eliminate the per-turn JSON parent-initialization call entirely. The first normal parent model/tool call must handle both direct prose and native tool calls; this is not merely moving the existing user-shaped initialization prompt into `startup()`.
- **Context policy:** default recommendation is a rolling summary plus a bounded recent tail, preserving exact recent tool evidence and user wording while compacting older turns.
- **Boot policy:** provider/model warmup is best-effort. Publish `parent_ready` or `parent_degraded`; retry lazily if the provider is unavailable. Do not send a fake user request at boot.
- **Invalidation:** rebuild the kernel when provider/model, API key, thinking policy, shell/tool settings, context-window settings, or agent/playbook/tool definitions change. Starting a new chat only creates a new `ParentSession`.
- **Provider constraint:** adapter/client reuse and Ollama model residency are feasible; cross-provider hidden KV-cache or conversation reuse is not assumed. The kernel caches immutable prompt/context components, not model beliefs.
- **Open implementation questions:** how to make the first native tool-capable call lightweight enough for direct conversation; where the rolling session summary is maintained; how the existing workspace lifecycle events map to boot-level readiness and per-turn execution; how to preserve completion-floor and recovery contracts without the initializer's mode/plan fields.
- **Relationship:** builds on ADR-5/8 closed-loop and ADR-51's generic direct boundary; intended to supersede the current per-turn initialization seam after live verification.

### Implementation update — Session 302 (2026-08-20)

Phase 1 is implemented. Application startup now builds a reusable `ParentKernel` with the active adapter, compiled parent contract, tool registry metadata, settings signature, and degraded state. Parent requests no longer call the JSON initializer; they enter the native loop directly with bounded recent history, dynamic turn/workspace context, and a lean `describe_tool` bootstrap surface. A `BaseAgent.run()` override passes the compiled contract without rebuilding it each turn. Provider/key/thinking/context changes invalidate the kernel, while startup failures remain degraded and retry lazily.

Live evidence: z.ai/glm-4.5-flash produced a clean one-iteration direct native turn with no initializer event and 1,621 prompt tokens; Zen/hy3-free loaded `describe_tool(shell)` and executed shell calls without schema errors. z.ai's tool trace was rate-limited and Cerebras returned payment-required, so a clean GLM native tool trace remains open. The rolling ParentSession summary and explicit readiness telemetry are deferred to the next phase. Full CI: 1,996 passed / 2 skipped.

---
## ADR-53: Parent-only architecture is the current scope (2026-08-20)
- **Author:** Buffy / openai/gpt-5.6-luna (Session 303), on the user's explicit clarification: "RIGHT NOW ITS JUST PARENT! NOTHING ELSE"
- **Status:** accepted — current-scope amendment; supersedes ADR-48's multi-agent current-scope conclusion and ADR-8's agent-centric implementation target for active work. Historical ADR-48/ADR-8 records remain unchanged.
- **Decision:** LocalMind currently has exactly one active agent: the Parent. The Parent is the sole autonomous owner of the `ParentKernel`, `ParentSession`, `TurnContext`, complete tool surface, planning, execution, observation, verification, recovery, and final synthesis. There are no active child agents, specialist agents, delegation paths, parallel delegation paths, or inheritance relationships in the architecture being built now.
- **Scope rule:** existing child-agent/ delegation modules and registry entries are legacy or parked compatibility surface. They must not be expanded, selected for new request routing, exposed as the Parent's current architectural model, or used to justify multi-agent behavior. This documentation amendment does not remove that code; removal or hiding is a separate implementation decision and requires its own live-verified change.
- **Parent maturity bar:** grow and prove the Parent first through durable session memory, Parent-owned execution structure, evidence-based verification/completion, model-agnostic recovery, safe bounded parallelism where appropriate, and provider/model escalation. Every loop/tool/provider change still requires the real-model live-testing procedure; regression tests alone are insufficient.
- **Future boundary:** child agents can be reconsidered only after the Parent meets that maturity bar and the user explicitly changes the scope. Until then, “agent” in active architecture means the Parent only, and “LocalMind” remains the user-facing identity.
- **Relationship to ADR-52:** ADR-52's warm-kernel design is retained and narrowed to this Parent-only runtime. `ParentKernel` is not a parent factory or inheritance mechanism; it is the boot-owned operating context for the one Parent.
- **Consequences:** the next implementation work must strengthen the Parent, not add agents, delegation, specialist routing, or child inheritance. The existing multi-agent code is recorded honestly as repository residue rather than current architecture.

---
## ADR-54: ParentSession — per-chat rolling summary + distinct readiness telemetry (2026-08-20)
- **Author:** Super Z / GLM-4.6 (z.ai) (Session 305), implementing B-2026-08-20-1 per ADR-52 phase 2 / ADR-53.
- **Status:** accepted (implements ADR-52's open implementation questions 2 + 3; does not supersede ADR-52 — it narrows phase 2 to the Parent-only runtime per ADR-53)
- **Context:** ADR-52 phase 1 (Session 302) shipped the boot-owned `ParentKernel` and removed the per-turn JSON initializer, but left two explicit gaps in its "open implementation questions": (1) no rolling session summary — the runtime assembled each turn's prompt from `history[-8:]` with per-message truncation, so long conversations would either bloat linearly or silently lose earlier turns at the fixed cap; (2) no distinct parent readiness signal — `/api/health` exposed only `engine_ready`, masking a degraded parent (cloud provider unreachable at boot) behind a green engine status.
- **Decision:** add a per-chat `ParentSession` (mutable, turn-scoped) alongside the boot-owned `ParentKernel` (immutable, server-scoped). The session carries a rolling compacted summary of older turns plus a bounded verbatim recent tail (default 6 pairs). Compaction folds the oldest pair into the summary as a one-line `User asked: ... | did <tool> | answered: ...` entry when the tail overflows; the summary trims to its most-recent 2/3 when it exceeds 4000 chars (≈1000 tokens). The session persists in a new `parent_sessions` table (migration 009) and survives backend restart. Distinct `parent_ready` / `parent_degraded` / `parent_recovered` events are queued by `_ensure_parent_kernel` and drained onto the first turn's ObsCollector; `/api/health` surfaces `parent_ready` + `parent_degraded_reason` separately from `engine_ready`; `/api/observability/{sid}` exposes the rolling summary + turn count.
- **Consequences:** (1) long conversations stay bounded in the parent prompt without losing the most recent verified evidence or user wording — the summary compacts only older turns. (2) The frontend now has a wire-level signal for parent-kernel readiness distinct from engine startup completion; a degraded parent still serves requests (lazy retry on the first turn) but its status is honest. (3) The rolling summary is bounded by `SUMMARY_MAX_CHARS` — extremely long conversations still fit in the prompt budget. (4) The summary is a *compact pointer*, not a full transcript — if a future session needs to recall exact earlier wording, it must read the persisted message history (the recent tail preserves the last 6 pairs verbatim, older turns are summarized). (5) Compaction thresholds (`RECENT_TAIL_MAX=6`, `SUMMARY_MAX_CHARS=4000`) are tunable constants — a real long-conversation workload may want them adjusted.
- **Live-verified:** real z.ai/glm-4.5-flash on isolated port 8765 — boot log `[parent-kernel] ready`, `/api/health` returns `parent_ready=true`, first turn SSE carries `parent_ready` event, 3-turn conversation persists `parent_session_turn_count=3` across a backend restart. Compaction itself is unit-tested (13 tests) but not live-verified on the real model (the 8-turn z.ai trace exceeded the tool-call time budget) — open for a future session with a faster provider.
- **Relationship:** implements ADR-52 phase 2 within the ADR-53 Parent-only scope. Does not introduce child agents, delegation, or specialist routing. The `ParentSession` is owned by the one Parent; it is not a session factory or inheritance mechanism.

---

## ADR-55: Add B.AI provider (multi-model OpenAI-compatible aggregator; free models are time-limited promos) (2026-08-20)

- **Author:** Buffy / deepseek/deepseek-v4-pro (Session 319)
- **Status:** accepted (config-only — IMPLEMENTED BUT UNTESTED; live smoke blocked on missing key)
- **Context:** The user researched B.AI (docs.b.ai) as a provider for LocalMind. B.AI is a multi-model LLM aggregator — one API surface in front of GPT, Claude, Gemini, DeepSeek, GLM, Qwen, Kimi, MiniMax, Grok, etc. — dual-compatible: OpenAI-style `POST /v1/chat/completions` and Anthropic-style `POST /v1/messages`, both against `https://api.b.ai`. Auth is `Authorization: Bearer <key>` (also accepts `x-api-key`). The OpenAI-compatible surface means it slots into the existing `OpenAICompatAdapter` as a config-only addition (the same class of change as ADR-9/ZenMux). The free models right now are rotating time-limited 0-Credit promotions, not a standing tier: `DeepSeek-V4-Flash` (free since 2026-08-17) and `Hy3` (free since 2026-08-20). Both revert to paid pricing when the promo ends; everything else is metered in Credits (1 USD = 1,000,000 Credits). Two caveats the user flagged: (1) free = promotional, not architectural — fits best as an opportunistic/fallback provider, not a primary free default; (2) it is a crypto-payment platform (wallet login, on-chain top-ups alongside Stripe/Alipay/WeChat/UnionPay) — a different trust posture than a plain SaaS API vendor. The user also flagged that `Hy3` is the exact model name LocalMind's `hy3-free` (zen/opencode.ai) diagnostics already reference — possibly the same underlying model surfaced through a different aggregator, or a naming coincidence.
- **Decision:** Add B.AI as `bai` in `PROVIDER_CONFIGS` (base URL `https://api.b.ai/v1`, key env `BAI_API_KEY`, model env `BAI_MODEL`, settings field `bai_model`, default model `DeepSeek-V4-Flash`), add `DeepSeek-V4-Flash: 128000` to `MODEL_CONTEXT_WINDOWS` (conservative, matches the existing `deepseek-v4-flash-free` entry; unverified), wire the frontend provider picker (`SettingsModal` `PROVIDERS`), and add `BAI_API_KEY`/`BAI_MODEL` to `.env.example`. The `display_name`/UI label is `B.AI (promo free models — time-limited)` so the promotional (not architectural) nature of the free tier is visible at selection time. `Hy3` is deliberately NOT given a context-window entry (unknown window → falls back to `default: 32768`) and is not the default, pending live verification of both model IDs against `GET /v1/models`.
- **Consolidation fix folded in (same commit):** adding B.AI surfaced that `models.py` still held two hardcoded provider→settings-field maps (`_model_setting_attr`, `_build_model_setting_map`) that had drifted from `PROVIDER_CONFIGS` — the ADR-9 ZenMux entry was silently missing from both, so `_model_setting_attr("zenmux")` returned `None` and `_build_model_setting_map()` omitted it (only `health.py` still listed it). Both maps (plus `health.py`'s `model_setting_map`) now derive from `PROVIDER_CONFIGS` so a future provider addition cannot drift. This is a behavior-preserving refactor except it correctly resolves ZenMux's model field (a latent bug fix).
- **Consequences:** (1) B.AI appears in the provider picker and resolves model/key via the standard OpenAI-compat path — no new adapter code, no Anthropic `/v1/messages` support (out of scope; the OpenAI surface is sufficient). (2) The promotional free tier may disappear or start billing mid-flight — users must not treat B.AI as a stable free default. (3) No published rate limits for the free promo models; they must be tested empirically like the zen `hy3-free` work. (4) The `Hy3` ↔ `hy3-free` question is unresolved — a future session with both keys should compare latency/quality to determine whether they are the same underlying model. (5) `health.py` + `models.py` no longer contain provider lists that can drift from `PROVIDER_CONFIGS`.
- **Testing:** config-only + registry-derivation changes are unit-tested (new `tests/api/test_provider_registry.py`; 4 tests lock the no-drift invariant and B.AI's registration). Full backend 2069 passed / 1 pre-existing failure (`test_parent_recovery_cap.py::test_non_parent_path_still_capped_at_two` — `ModuleNotFoundError: No module named 'tests'`, an unrelated broken test-import from Session 310); ruff clean; frontend tsc + SettingsModal tests green. **NOT live-verified — BLOCKED:** no B.AI API key is available on this machine (`.context/memory/secrets/` has no `bai` key). Per the Session 31/33 flaw log, this must not be claimed "works". Smoke-test steps for the next session with a key: (a) `GET https://api.b.ai/v1/models` with the key → confirm exact model IDs (`DeepSeek-V4-Flash`, `Hy3`); (b) a real `/api/chat` trace through the isolated 8765 harness with `LOCALMIND_ADAPTER=bai`; (c) verify tool calls + streaming work end-to-end; only then mark ADR-55 "tested — done".
- **Relationship:** supersedes none. Builds on the ADR-9 provider pattern (config-only OpenAI-compat addition, honest untested-until-keyed status). Parent-only scope per ADR-53 is untouched — this is a provider config addition, not an agent/delegation change.
- **Correction (Session 320, 2026-08-20):** the Session 319 default model and context window were WRONG and caused the user's "b.ai not working" report. B.AI's model IDs are LOWERCASE — `deepseek-v4-flash` and `hy3` (the capitalized "DeepSeek-V4-Flash"/"Hy3" are display names only) — and the context windows are `deepseek-v4-flash` = 1,000,000 (1M) tokens and `hy3` = 256,000, sourced from docs.b.ai/llmservice/models/<model>. The base URL `https://api.b.ai/v1` and Bearer auth were already correct (docs.b.ai/llmservice/api confirms "Base URL: https://api.b.ai"; the chat platform's bankofai.io↔b.ai domains are unrelated alternates for the web app, not the API). Fixed in Session 320: `default_model="deepseek-v4-flash"`, context windows corrected, and the registry test now pins the lowercase IDs + windows. A case-mismatched model ID resolves to model-not-found, not an auth/domain error — which is why it failed silently as "wrong/not working".
- **Correction (Session 321, 2026-08-20):** the canonical API domain changed to `api.bankofai.io` (b.ai → bankofai.io brand consolidation) and the provider is now LIVE-VERIFIED with the user's key. Three findings: (1) The user's `settings.json` still held the stale Session 319 model `DeepSeek-V4-Flash`, which OVERRODE the Session 320 lowercase default and is why LocalMind still returned model-not-found — fixed in the runtime file to `deepseek-v4-flash`. (2) `GET https://api.bankofai.io/v1/models` (with key) returns 38 lowercase model IDs (`deepseek-v4-flash`, `deepseek-v4-pro`, `glm-5.1/5.2/5.3`, `gpt-5.x`, `claude-*`, `gemini-*`, `kimi-*`, `qwen*`, `minimax-*`); `hy3` is NOT in the live list (the 256K window entry is retained as harmless registry data). Live chat: `deepseek-v4-flash` → 200 "PONG"; `DeepSeek-V4-Flash` → 404 model_not_found (case-sensitive, re-confirmed). (3) The earlier browser-User-Agent header was a MISDIAGNOSIS: the 403 "error code: 1010" was triggered by the stdlib urllib `Python-urllib/*` UA in the test scripts, NOT by httpx — httpx's default `python-httpx/*` UA passes Cloudflare (confirmed: `python-httpx/*`, `python-requests/*`, `curl/*` pass; only `Python-urllib/*` is blocked), so the header was removed. Base URL switched to `https://api.bankofai.io/v1`; display name → `BankOfAI (promo free models — time-limited)`. End-to-end smoke through the real adapter (`OpenAICompatAdapter(provider="bai")`) returned 38 models + "PONG". ADR-55 is now live-verified.
- **Correction (Session 322, 2026-08-20):** renamed the provider key from `bai` to `bankofai` per the user ("drop bai") — the `bai` identifier is now gone. Env vars `BAI_API_KEY`/`BAI_MODEL` → `BANKOFAI_API_KEY`/`BANKOFAI_MODEL`, settings field `bai_model` → `bankofai_model`, frontend provider id `bai` → `bankofai`, and the listable-models tuple updated. Migrated the user's `settings.json` (`adapter` + `api_keys.bai` → `bankofai`). Root cause of the persistent 404: the user's STILL-RUNNING backend was the OLD code, which had re-written `model: DeepSeek-V4-Flash` back into `settings.json` (overriding the Session 321 lowercase fix) and was sending the case-mismatched ID → `model_not_found`. Re-fixed the model value; a full backend restart is required for the new code (lowercase default + `bankofai` key + bankofai.io base) to take effect. Re-verified live through `OpenAICompatAdapter(provider="bankofai")` → 38 models + "PONG".

---

## ADR-54: Completion is gated on a goal-derived fixed checklist (the synthesize/evaluate stage) (2026-08-20)

- **Author:** Buffy / deepseek/deepseek-v4-flash (Session 330)
- **Status:** accepted — implements the user's consolidated directive; live-verified on bankofai/deepseek-v4-flash.
- **Context:** the user's transcript diagnosed that three recurring failures — premature completion ("Turn complete" on a recon-only stop), the Todos panel mutating to match whatever ran (always 100%), and the 2/2 lie — are symptoms of ONE missing piece: the loop has no synthesize/evaluate stage that holds a fixed goal-checklist independently of execution and compares actual tool outcomes against it before declaring completion. The warm-kernel parent path (agent_runtime) passes no success_criteria, so `_acceptance_gate_at_final_answer`'s no-criteria branch accepted the model's word on any final text; S327's synthesized todos (syn-N = tools-that-ran) made the denominator self-mutating, and `_finalize_plan_todos` flipped every remaining plan todo to complete at turn end.
- **Decision:** the user's request defines "done" up front. On the warm-kernel parent path, derive a FIXED goal checklist deterministically from the message (`derive_goal_items`: named files with write verbs, folders with create verbs; conversational/abstract → no contract → legacy path). Hand it to the loop as BOTH `plan_steps` (the Todos denominator, emitted up front as plan-0..N, never mutated) and `success_criteria` (the acceptance-gate contract), with `skip_head_gate=True` so the criteria gate at the FINAL-ANSWER point (the model says done → gate verifies → replan or honest report) — never at the iteration head, which would end the turn with a bare "✓ n/n" before the model's synthesis. The gate must NOT auto-accept a goal turn with zero tool evidence (a no-tool "done" reproduces the exact bug — live-found); it falls through to all-unmet → replan while iterations remain → honest-stop at the cap, emitting `agent_loop_gate_honest_stop` and completing only the PASSED goal items; the SSE bridge skips flipping the unmet items on that signal, so the panel shows the true fraction. verify.py evidence matching tolerates Windows backslashes (S264/S325 family).
- **Consequences:** (1) A turn that stops after recon (or commits to work in prose without doing it) is no longer reported complete — the gate replans and, at the cap, reports honestly with the unmet items, and the panel never shows a false 100%. (2) The fixed checklist replaces the synthesized syn-todos for goal-bearing turns; syn-todos remain the fallback surface for contract-free turns. (3) Cost: goal derivation is deterministic (zero LLM calls — a regex pass per turn), so no latency regression; the gate may add replan calls on genuinely incomplete turns, bounded by the existing iteration/wall-clock caps. (4) The derivation is conservative: abstract tasks ("set up a FastAPI project") name no files and get no contract — an LLM derivation tier is a possible follow-up but was deliberately NOT added (false-fail + latency risk). (5) Honest-stop leaves unmet items pending (not visually "failed"); a `todo_failed` event is a small optional follow-up.
- **Live-verified:** bankofai/deepseek-v4-flash on isolated 8765, exact task shape (folder path-test + a.txt "first" + b.txt "second"): BEFORE the zero-evidence guard fix, the model answered one token, ran zero tools, and the turn completed 3/3 with zero files; AFTER, `agent_loop_gate_failed_replan` fired, the model created the folder and both files with the exact content (on disk), and the loop finished `criteria=3 gate=pass` with "✓ 3/3 criteria met". The cap-path honest stop and the SSE finalize skip are unit-verified (the live model cooperated after the replan, so the cap path did not fire live). Full backend 2106 passed / 2 skipped / 0 failures.
- **Relationship:** completes the B-2026-08-20-23 thread (empty → synthesized → goal-fixed Todos) and implements the user's synthesize/evaluate directive within the ADR-53 Parent-only scope. Builds on ADR-18's acceptance gate (the evaluate machinery already existed — the contract was the missing piece) and ADR-49's upfront-plan intent (revived, deterministically, without the retired init call).
## ADR-56: Future vision — LocalMind is an agent runtime + intelligence harness (2026-08-25)

- **Author:** Super Z / GLM-5.3 (Session 403, from the owner's vision statement)
- **Status:** accepted (direction document — `docs/VISION_ARCHITECTURE.md`; no scope change)
- **Context:** the owner articulated the long-term product identity: "Model Intelligence + Harness = Agent." LocalMind is not "a local chatbot powered by Ollama" — it is an intelligence harness that turns replaceable models into persistent, context-aware, tool-using agents. The stack: Serving Layer → Agent Runtime (Understand→Plan→Act→Observe→Adapt) → Context Engine / Memory / Orchestration → Capability Layer → Sandbox → Model Intelligence. Key principles: the model is NOT LocalMind (providers evolve, the harness is the product); conversation is not memory (selected, structured knowledge vs raw chronology); right context, not more context (selection beats volume — the product-side evolution of the `.context` concept into a context substrate); bounded-by-construction and evidence-over-narration as standing disciplines; one mature agent before many.
- **Decision:** record the vision as `docs/VISION_ARCHITECTURE.md` — each layer documented as vision / what-exists-today (mapped to real modules: adapters + model_router; 35-tool registry; vector facts + parent_sessions + failure memory; context_policy/builder/compactor; session workspace + sandbox + shell guards; the parent agent loop; api + cli serving) / the gap. Link it from `docs/ARCHITECTURE.md`.
- **Consequences:** (1) The vision explicitly does NOT reopen ADR-53 — specialists appear only behind the §8 maturity gates (observed Parent maturity on real workloads, entered by evidence-citing ADR, the same standard ADR-53 used to stop premature multi-agent work). (2) Design choices that ask "which direction" now have a reference document. (3) No backlog scope change — the doc describes the arc the current structure is already on, not a rewrite. (4) The `.context`-as-context-substrate idea is recorded as the long-term direction for the Context Engine, with the dev protocol as its working prototype.
- **Testing:** documentation only — no code changed. Full backend suite untouched this session; doc reviewed against current architecture for accuracy (ADR-53 status, tool count, memory subsystems, serving surfaces).
- **Relationship:** sits ABOVE ADR-53 (long-term arc vs current scope); compatible with ADR-5/ADR-8 closed-loop model and ADR-52 warm kernel — the runtime identity diagram IS the existing AgentLoop. Aligns with the owner's progression: AI application → single intelligent agent → agent runtime + harness → multi-agent platform.

---

## ADR-57: Redesign the parent loop for efficient multi-LLM-call turns (fuse reason+act, stream, thin loop) (2026-09-02)

- **Author:** claude-opus-4.8 (collab session claude-3f7bfa6b; peers opencode, zcode)
- **Status:** PROPOSED — direction accepted; slices touching the shared loop require peer assessment + an agreement event (collab) before implementation. Research basis: `docs/research/advanced-agent-architectures.md`. **CORRECTED 2026-09-02 (owner):** the first draft mis-decided "remove the Thinker" and leaned on model-speed excuses — both wrong. The Thinker STAYS; the fix is the AGENT's call architecture, model-agnostic.
- **Context:** the owner observed multi-minute turns where the web fetch was 4.5s and the rest was an empty "Thinking" block. This is an **AGENT-architecture flaw, not a model problem** — a fast model would only *hide* it. The agent issues 2–4 LLM calls per turn (pre-tool Thinker → tool-emit → post-tool Thinker → synthesis) that are **serial, silent, and sometimes redundant**: they block each other, stream nothing (the empty block), and fire reflexively (Thinker after every tool). A live test with the Thinker skipped was still slow — because the *remaining* calls are also serial and (for the panel) opaque. The Thinker itself is NOT the problem: it is harness intelligence (ADR-56, "Model Intelligence + Harness = Agent" — the harness must add value on top of ANY model). The problem is that the agent runs its calls badly. The owner's directive, read correctly: **redesign the architecture for multiple LLM calls done *right* — not fewer calls, better-run calls.**
- **Decision:** KEEP the Thinker (and the multi-call shape). Make the agent's multiple LLM calls efficient and responsive on ANY model by fixing three agent-side properties — **serial→concurrent, silent→streamed, redundant→gated** — plus scaling breadth through parallel sub-agents. Explicitly NOT "collapse to one call" and NOT "the model is slow." Sequenced, independently-shippable slices:
  1. **Stream every call — the Thinker included** (LOW risk, high felt-impact). No call runs silent: the Thinker's analysis and the synthesis both stream their reasoning to the Thinking panel, so there is never dead air on any model. (Deepseek reasoning already reaches the panel — see Open-Q2 RESOLVED; the remaining work is making the *Thinker's* consult stream instead of draining silently, and confirming incremental synthesis streaming — Open-Q4.)
  2. **Run independent calls concurrently, not stacked** (MEDIUM). Where a Thinker analysis does not block the next action, overlap it; emit independent tool calls in one response and execute them in parallel. Serial stacking, not the call count, is the latency.
  3. **Gate the redundant calls** (LOW, partly done). The post-tool Thinker is value-gated (perf commit 2a19540 — fires on failure / ≥2 sources, skipped after a single clean fetch). Extend the same discipline to any other reflexive call. The Thinker fires when it adds signal, not by reflex.
  4. **Right-size per role + adaptive** (MEDIUM, optional). The Thinker's analysis is a lightweight role; it can use a faster/cheaper reasoning pass while the main model acts/synthesizes, and its depth can scale to the task — an agent-efficiency choice, made model-agnostically (not "because the model is weak").
  5. **Acceptance-gate → structural check** (MEDIUM). Migrate what `_acceptance_gate_at_final_answer`'s LLM call catches to a code check on `turn_outcome` where possible (ADR-54's contract is deterministic) — removing an LLM call that adds nothing the code can't, on any model.
  6. **Breadth via parallel sub-agents** (LARGER). Use `delegate` for independent sub-tasks with isolated child context, run concurrently (ADR-53-compatible) — this is the *right* place for extra LLM calls.
  7. **Context management as a first-class subsystem** (ONGOING). Compaction, tool-result trimming, just-in-time retrieval (ADR-56 Context Engine).
- **Consequences:** (1) The agent becomes responsive on ANY model because it stops stacking silent serial calls — the win is in the agent, not the provider. (2) The Thinker's value is preserved; only its *execution* changes (streamed, concurrent, gated). (3) Coordination: slices touching loop.py and the SSE bridge (chat.py, zcode's B-2026-08-30-7 area) must be claimed + agreed on the collab channel before implementation. (4) New first-class metrics: **calls/turn**, **serial-blocking-time/turn**, **time-to-first-visible-token** — measured on multiple models to prove model-agnostic improvement. (5) A refactor toward the ADR-56 runtime, not a rewrite — same `Understand→Act→Observe` shape, same intelligence, better-run calls.
- **Open questions:**
  1. Which calls are genuinely independent (safe to run concurrently) vs. must be serial (the analysis feeds the next action)? Map the data dependencies in the loop before parallelizing.
  2. ~~Why is the Thinking panel empty for deepseek-v4-flash?~~ **RESOLVED (2026-09-02, live):** NOT an adapter/bridge gap. deepseek-v4-flash *does* emit reasoning (`reasoning_content`; adapter probe: 150 chars of real chain-of-thought), the adapter routes it to `StreamChunk.thinking`, and in the agent flow it *does* reach the panel — `scripts/live_test_thinking_block.py` on deepseek-v4-flash: 20 real-prose `thinking_token` events, labels on status_update, 0 scaffold leaks. The empty "Thinking 2m7s" block was the **silent Thinker calls** consuming the time with nothing to stream; the post-tool Thinker gate (perf commit 2a19540) removes that overhead, so the panel now shows the model's actual synthesis reasoning. No slice-1 forwarding fix needed for deepseek — only the streaming-plumbing check (Open-Q4) remains for slice 1.
  3. Full inventory of what the acceptance-gate LLM call catches that a code check cannot.
  4. Can the SSE bridge stream synthesis tokens incrementally (not buffer-then-emit) for all adapters?
- **Testing/verification:** each slice ships with a live before/after run on **more than one model** (e.g. deepseek-v4-flash and glm-4.5-flash) — not to compare models, but to prove the agent-side improvement (less serial-blocking time, time-to-first-visible-token, correctness held) is **model-agnostic**. Measured on the documented `scripts/lm_suite_tests.py` harness, per the live-testing protocol (green pytest ≠ shipped). Success is defined agent-side (calls no longer stack serially/silently), never as "the model got faster."
- **Relationship:** implements the ADR-56 runtime vision ("Model Intelligence + Harness"; the harness ADDS intelligence on top of any model) by making the harness's calls efficient (streamed, concurrent, gated) while KEEPING its intelligence (the Thinker). Refines ADR-54 (completion contract stays; its gate becomes a code check where possible). Respects ADR-53 (parent-only scope; breadth via `delegate` parallel sub-agents). Supersedes the Session-350 "Thinker after every tool" decision (the Thinker is now value-gated, not removed).

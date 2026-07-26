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

- **Status:** accepted (architectural target — implementation pending, see backlog B-2026-07-26-1 / B-2026-07-26-2)
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


# Active Workflow (overwrite when the workflow changes)

The workflow currently in force for this repo — which protocol edition
agents follow and the standing session parameters. Update only when
the user changes the rules; note the change in your session entry.

- **Protocol location:** vendored in `.context/core/` (version: see `.context/core/VERSION`). No external fetch needed — the protocol travels inside this repo.
- **Edition routing (by agent type, not by this file):**
  - **Local agent** (IDE-integrated, on the user's machine) → `.context/core/rules/ai-engineering-protocol-local.md`
  - **Cloud/sandbox agent** (ephemeral workspace, PAT-authenticated) → `.context/core/rules/ai-engineering-protocol.md`
  - This file does NOT choose your edition — your agent type does. If a prior session recorded only one edition here, that's whichever agent type wrote it last; ignore it and follow your own type.
- **Package upstream (core updates + flaw back-ports):** https://github.com/TisoneK/.context.git
- **Role overlays:** available in `.context/core/roles/` (reviewer, security-auditor, docs-agent). Active role overlays, if any, noted per-session below.
- **Project overrides:** `.context/memory/overrides/rules.md` (beats the edition, except secret-handling and append-only rules).
- **Since:** 2026-07-15 (migrated to core 0.2.0 two-zone layout; prior workflow history preserved in `agents/sessions.md`)
- **Default role:** engineer — full-scope, unless a session says otherwise.
- **Scope:** discovery + review + fix all safe issues
- **Target:** implement ADR-8 — agent-centric routing (tasks → agents → tools, not tasks → tools → agents). Four phases spanning multiple sessions: (1) Agents as directories — move agent classes INTO `agents/<name>/agent.py`, move workflow files INTO `agents/<name>/workflow.md`, move personas INTO `agents/<name>/persona.md`, registry auto-discovers directories with `agent.py`; (2) wire `build_context()` into `BaseAgent.run()` so workflow files reach the model (highest-leverage piece; already backlogged Session 33); (3) agent-initiated delegation replaces `should_use_sub_agents()` keyword heuristic; (4) task-type classifier replaces/augments the intent classifier. See `.context/memory/plans/decisions.md` ADR-8 for the full five-principle + four-phase plan. **ADR-8 builds on ADR-5** — the 5-step closed-loop shape stays; agents just get richer context and delegation ability. Do NOT regress Session 31-33 fixes (iteration cap, hit-limit-aware fallback, check-before-acting safety workflow, `_obs.all()` not `drain()` in the engine). A chat-message target overrides this standing Target; if the chat says "start" or "general sweep," fall back to the old default.
- **Focus areas:** all — security, performance, UX, architecture, testing, docs
- **Findings handling:** fix safe, flag architectural
- **Push policy:** push to main directly after each commit
- **Commit style:** Conventional Commits with scope; `chore(context):` for `.context/` updates; `docs(review):` for review reports
- **Commit granularity:** one logical change per commit
- **Deliverable:** report in `.context/memory/reviews/YYYY-MM-DD-review.md` + chat summary

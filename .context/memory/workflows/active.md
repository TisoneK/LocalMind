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
- **Since:** 2026-07-15 (migrated to the two-zone layout; vendored core currently 0.5.0; prior workflow history preserved in `agents/sessions.md`)
- **Default role:** engineer — full-scope, unless a session says otherwise.
- **Scope:** discovery + review + fix all safe issues
- **Target:** ADR-41 is fully delivered (Session 254 review-44 — GLM thinking re-enabled + live-verified on z.ai/glm-4.5-flash: before/after, complete answers, reasoning streamed). ADR-40 is fully delivered (B Session 251 review-41; C Session 252 review-42). Next open: ADR-37 follow-ups B-2026-08-15-10/11/12, and review-42's `classify_failure` cleanup (only flag tool_failure when the failing step is terminal — adapted runs currently poison failure memory). ADR-36/37's delivered work stands (Thinker depth B-2026-08-15-5..8 done Sessions 235-236). **Do NOT regress:** the ADR-34 event order, the `Hi`→zero-provider-call boundary (S206), Session 31-33 fixes (thinking-aware timeouts build on them), the ADR-40 guardrail (live-verify tool SELECTION on a weak model + cerebras before any further schema cut), or the ADR-41 default (z.ai thinking ON — never re-add a thinking-disable for GLM; GLM-4.5-flash has no effort/budget param, timeout scaling is the lever). A chat-message target overrides this standing Target.
- **Focus areas:** all — security, performance, UX, architecture, testing, docs
- **Findings handling:** fix safe, flag architectural
- **Push policy:** push to main directly after each commit
- **Commit style:** Conventional Commits with scope; `chore(context):` for `.context/` updates; `docs(review):` for review reports
- **Commit granularity:** one logical change per commit
- **Deliverable:** report in `.context/memory/reviews/YYYY-MM-DD-review.md` + chat summary
- **Verification bar (MANDATORY — user directive, Session 274):** for ANY change to the agent loop, tools, or provider adapters, LIVE-TEST it per [`system/live-testing.md`](../system/live-testing.md) before writing "done"/"works"/"verified". Unit tests alone are NOT sufficient — the user has stated they "are designed to pass certain conditions" and do not prove the real model+provider path. Trace on a real weak model (z.ai/glm-4.5-flash), capture a before/after on the same task, and grep the SSE/log for the actual event or number you changed. Never touch port 8000; never print API-key values; use the isolated 8765 + `LOCALMIND_HOME` harness. Report what was live-verified vs unit-tested vs assumed.

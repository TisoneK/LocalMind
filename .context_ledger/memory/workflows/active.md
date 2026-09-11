# Active Workflow (overwrite when the workflow changes)

The workflow currently in force for this repo — which protocol edition
agents follow and the standing session parameters. Update only when
the user changes the rules; note the change in your session entry.

- **Protocol location:** vendored in `.context_ledger/core/` (version: see `.context_ledger/core/VERSION`). No external fetch needed — the protocol travels inside this repo.
- **Edition routing (by agent type, not by this file):**
  - **Local agent** (IDE-integrated, on the user's machine) → `.context_ledger/core/rules/ai-engineering-protocol-local.md`
  - **Cloud/sandbox agent** (ephemeral workspace, PAT-authenticated) → `.context_ledger/core/rules/ai-engineering-protocol.md`
  - This file does NOT choose your edition — your agent type does. If a prior session recorded only one edition here, that's whichever agent type wrote it last; ignore it and follow your own type.
- **Package upstream (core updates + flaw back-ports):** https://github.com/TisoneK/context-ledger.git
- **Role overlays:** available in `.context_ledger/core/roles/` (reviewer, security-auditor, docs-agent). Active role overlays, if any, noted per-session below.
- **Project overrides:** `.context_ledger/memory/overrides/rules.md` (beats the edition, except secret-handling and append-only rules).
- **Since:** 2026-07-15 (migrated to the two-zone layout; vendored core currently **1.0.0** — the office architecture is in force since the 2026-09-11 MAJOR adoption with owner go-ahead: session-produced memory lives in `memory/office/`, durable files at the memory root, `office_size` replaces `group_size`, close freezes the office verbatim; prior workflow history preserved in the office's `agents/sessions.md` and in git history)
- **Default role:** engineer — full-scope, unless a session says otherwise.
- **Scope:** discovery + review + fix all safe issues
- **Target:** Parent-only architecture amendment ADR-53, building on warm Parent Kernel ADR-52. LocalMind currently has exactly one active agent: the Parent. Strengthen the Parent's durable session context, execution structure, verification, recovery, readiness, and model escalation before considering any child/specialist/delegation capability. Existing multi-agent code is parked compatibility residue, not current architecture; do not extend or route new work through it. **Do NOT regress:** the ADR-34 event order, the `Hi`→zero-provider-call boundary (S206), Session 31-33 fixes (thinking-aware timeouts build on them), the ADR-40 guardrail (live-verify tool SELECTION on a weak model + cerebras before any further schema cut), the ADR-41 default (z.ai thinking ON — never re-add a thinking-disable for GLM; GLM-4.5-flash has no effort/budget param, timeout scaling is the lever), or the Parent-only scope. A chat-message target overrides this standing Target.
- **Focus areas:** all — security, performance, UX, architecture, testing, docs
- **Findings handling:** fix safe, flag architectural
- **Push policy:** push to main directly after each commit
- **Commit style:** Conventional Commits with scope; `chore(ledger):` for `.context_ledger/` updates; `docs(review):` for review reports
- **Commit granularity:** one logical change per commit
- **Deliverable:** report in `.context_ledger/memory/reviews/YYYY-MM-DD-review.md` + chat summary
- **Verification bar (MANDATORY — user directive, Session 274):** for ANY change to the agent loop, tools, or provider adapters, LIVE-TEST it per [`system/live-testing.md`](../system/live-testing.md) before writing "done"/"works"/"verified". Unit tests alone are NOT sufficient — the user has stated they "are designed to pass certain conditions" and do not prove the real model+provider path. Trace on a real weak model (z.ai/glm-4.5-flash), capture a before/after on the same task, and grep the SSE/log for the actual event or number you changed. Never touch port 8000; never print API-key values; use the isolated 8765 + `LOCALMIND_HOME` harness. Report what was live-verified vs unit-tested vs assumed.

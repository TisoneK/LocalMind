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
- **Target:** implement ADR-36 — Agent as orchestrator + Thinker as silent analyst, with transparency-as-the-mechanism (live-streamed thinking that collapses after done). The event-type tagging prerequisite is largely already shipped by ADR-34 (typed SSE events, auto-collapsing ThinkingBlock, Actions panel); the net-new work is Thinker depth (facts/risks/ambiguities assessment, not a one-line objective) plus routing/tagging polish. Backlog: B-2026-08-15-5 (Thinker depth — highest leverage), B-2026-08-15-6 (routing polish), B-2026-08-15-7 (final-synthesis guarantee), B-2026-08-15-8 (collapse-after-done verify). **Builds on ADR-33/34 (parent-first realtime runtime) — do NOT regress the ADR-34 event order `acknowledgement → understanding → plan → action → evidence → synthesis`, the `Hi`→zero-provider-call boundary (S206), or Session 31-33 fixes.** A chat-message target overrides this standing Target.
- **Focus areas:** all — security, performance, UX, architecture, testing, docs
- **Findings handling:** fix safe, flag architectural
- **Push policy:** push to main directly after each commit
- **Commit style:** Conventional Commits with scope; `chore(context):` for `.context/` updates; `docs(review):` for review reports
- **Commit granularity:** one logical change per commit
- **Deliverable:** report in `.context/memory/reviews/YYYY-MM-DD-review.md` + chat summary

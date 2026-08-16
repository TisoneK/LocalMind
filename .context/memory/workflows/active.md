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
- **Target:** implement ADR-40 **option C** — on-demand full-tool-context for the long-tail tools (lean always-present index + load a SPECIFIC tool's full schema when selected, mirroring the `skill` loader). Option B (lean schemas) shipped + live-verified in Session 251 (B-2026-08-16-1, review-41): native catalog 24,230→15,981 chars, in-prompt list collapsed onto the same defs; remaining reclaim requires C (B-2026-08-16-2). ADR-36/37's delivered work stands (Thinker depth B-2026-08-15-5..8 done Sessions 235-236); ADR-37 follow-ups B-2026-08-15-10/11/12 remain open. **Do NOT regress:** the ADR-34 event order, the `Hi`→zero-provider-call boundary (S206), Session 31-33 fixes, or the ADR-40 guardrail (live-verify tool SELECTION on a weak model + cerebras before any further schema cut). A chat-message target overrides this standing Target.
- **Focus areas:** all — security, performance, UX, architecture, testing, docs
- **Findings handling:** fix safe, flag architectural
- **Push policy:** push to main directly after each commit
- **Commit style:** Conventional Commits with scope; `chore(context):` for `.context/` updates; `docs(review):` for review reports
- **Commit granularity:** one logical change per commit
- **Deliverable:** report in `.context/memory/reviews/YYYY-MM-DD-review.md` + chat summary

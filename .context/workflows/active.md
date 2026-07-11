# Active Workflow (overwrite when the workflow changes)

The workflow currently in force for this repo — which protocol edition
agents follow and the standing session parameters. Update only when the
user changes the rules; note the change in your session entry.

- **Protocol:** `ai-engineering-protocol.md` (cloud/sandbox edition) — for cloud agents that clone with a PAT. Local agents (Claude Code, Cursor, Copilot) use `ai-engineering-protocol-local.md` from the `TisoneK/.context` package.
- **Since:** 2026-07-11
- **Default role:** engineer — full-scope, unless a session says otherwise. Role overlays (reviewer, security-auditor, docs-agent) available in the `TisoneK/.context` package's `roles/` directory.
- **Scope:** discovery + review + fix all safe issues
- **Focus areas:** all — security, performance, UX, architecture, testing, docs
- **Findings handling:** fix safe, flag architectural
- **Push policy:** push to main directly after each commit
- **Commit style:** Conventional Commits with scope; `chore(context):` for `.context/` updates; `docs(review):` for review reports
- **Commit granularity:** one logical change per commit
- **Deliverable:** report in `.context/reviews/YYYY-MM-DD-review.md` + chat summary

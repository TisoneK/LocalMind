# Active Workflow (overwrite when the workflow changes)

The workflow currently in force for this repo — which protocol edition
agents follow and the standing session parameters. Update only when the
user changes the rules; note the change in your session entry.

- **Protocol:** `ai-engineering-protocol-local.md` (local edition) — this session runs GitHub Copilot on a local Windows machine. Cloud agents (Super Z on Z.ai sandbox) use the cloud/sandbox edition.
- **Protocol source (raw — for agent fetch):** https://raw.githubusercontent.com/TisoneK/.context/main/ai-engineering-protocol-local.md (local) / https://raw.githubusercontent.com/TisoneK/.context/main/ai-engineering-protocol.md (cloud)
- **Protocol source (blob — for human browsing):** https://github.com/TisoneK/.context/blob/main/ai-engineering-protocol-local.md (local) / https://github.com/TisoneK/.context/blob/main/ai-engineering-protocol.md (cloud)
- **Fallback:** if the raw URL 404s, clone `TisoneK/.context` with `--depth 1` and read the file locally — this is the reliable fallback.
- **Since:** 2026-07-11
- **Default role:** engineer — full-scope, unless a session says otherwise. Role overlays (reviewer, security-auditor, docs-agent) available in the `TisoneK/.context` package's `roles/` directory.
- **Scope:** discovery + review + fix all safe issues
- **Target:** general sweep
- **Focus areas:** all — security, performance, UX, architecture, testing, docs
- **Findings handling:** fix safe, flag architectural
- **Push policy:** push to main directly after each commit
- **Commit style:** Conventional Commits with scope; `chore(context):` for `.context/` updates; `docs(review):` for review reports
- **Commit granularity:** one logical change per commit
- **Deliverable:** report in `.context/reviews/YYYY-MM-DD-review.md` + chat summary

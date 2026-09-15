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
- **Since:** 2026-07-15 (migrated to the two-zone layout; vendored core currently **1.1.3** — the office architecture is in force since the 2026-09-11 MAJOR adoption with owner go-ahead: session-produced memory lives in `memory/office/`, durable files at the memory root, `office_size` replaces `group_size`, close freezes the office verbatim; prior workflow history preserved in the office's `agents/sessions.md` and in git history)
- **Default role:** engineer — full-scope, unless a session says otherwise.
- **Scope:** discovery + review + fix all safe issues
- **Target:** Resilience + ZCode-import program (set by owner 2026-09-12, S471; full map: `office/reviews/2026-09-12-review-s471.md`). DONE at setting: the provider-stall watchdog on chat turns (`e32e08a1` — no-first-byte stall names the provider at 5s, switch-model offer at 30s, no abort). NEXT, in priority order: (1) **MCP client support** (stdio + streamable-HTTP transports, `mcp__server__tool` naming — the tool surface stops being the boundary); (2) **read-only Explorer subagent** — a Parent TOOL, not a peer: read-only sandbox, returns bounded conclusions with `file:line` refs, not dumps; (3) **fresh-eyes acceptance judge** — read-only, re-reads a finished deliverable against the original request, structured per-item verdicts (deepens ADR-18; the loop never grades its own work); (4) **plugin-style skill packaging** — versioned, namespaced `plugin:skill`, seed manifest, bundleable scripts/.mcp.json/commands. Tier-2 backlog candidates: web_fetch prompt-distillation, background-exec completion re-invocation, structured clarifying questions, plan mode. LocalMind has exactly one active agent: the Parent; live multi-agent delegation stays parked compatibility residue (the explorer/judge are read-only Parent tools, not peers). **Do NOT regress:** the ADR-34 event order, the `Hi`→zero-provider-call boundary (S206), Session 31-33 fixes (thinking-aware timeouts build on them), the ADR-40 guardrail (live-verify tool SELECTION on a weak model + cerebras before any further schema cut), the ADR-41 default (z.ai thinking ON — never re-add a thinking-disable for GLM; GLM-4.5-flash has no effort/budget param, timeout scaling is the lever), the S471 watchdog fall-through (once a first byte lands, the heartbeat must return to the truthful prior branches — never stall-shame a healthy stream), or the Parent-only scope. A chat-message target overrides this standing Target.
- **Focus areas:** all — security, performance, UX, architecture, testing, docs
- **Findings handling:** fix safe, flag architectural
- **Push policy:** push to main directly after each commit
- **Commit style:** Conventional Commits with scope; `chore(ledger):` for `.context_ledger/` updates; `docs(review):` for review reports
- **Commit granularity:** one logical change per commit
- **Deliverable:** report in `.context_ledger/memory/office/reviews/YYYY-MM-DD-review.md` + chat summary
- **Verification bar (MANDATORY — user directive, Session 274):** for ANY change to the agent loop, tools, or provider adapters, LIVE-TEST it per [`system/live-testing.md`](../system/live-testing.md) before writing "done"/"works"/"verified". Unit tests alone are NOT sufficient — the user has stated they "are designed to pass certain conditions" and do not prove the real model+provider path. Trace on a real weak model (z.ai/glm-4.5-flash), capture a before/after on the same task, and grep the SSE/log for the actual event or number you changed. Never touch port 8000; never print API-key values; use the isolated 8765 + `LOCALMIND_HOME` harness. Report what was live-verified vs unit-tested vs assumed.

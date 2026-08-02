# Session Notes — 2026-08-02 — Session 65

> **Session:** 2026-08-02 — Session 65 (Super Z / GLM-5.2)
> **Task:** Research Codebuff (CodebuffAI/open-codebuff) architecture and compare against LocalMind. Produce borrowing recommendations. Purely research — no product code changes.
> **Companion review:** `.context/memory/reviews/2026-08-02-review-1.md`

These notes contain the full research detail. Three companion files in
this directory carry the long-form analysis; this `notes.md` is the
index + audit trail + decisions made.

---

## Research Artifacts in This Directory

| File | Lines | Purpose |
|---|---|---|
| `notes.md` (this file) | — | Index + audit trail + decisions |
| `codebuff-deep-profile.md` | ~657 | Deep technical profile of Codebuff (~6,500 words, 12 sections + 2 appendices, every section ≥150 words with `file:line` citations) |
| `comparison.md` | ~869 | 10-section side-by-side comparison (agent system, tools, orchestration, isolation, parallelization, delegation, memory, safety, model layer, synthesis) |
| `recommendations.md` | ~631 | 12 borrowing recommendations across 3 tiers, each with impact/effort/risk/model-readiness/concrete-steps + phased roadmap + "What NOT to borrow" |

---

## What Was Researched

### LocalMind (the baseline)

Cloned to `/home/z/my-project/repos/LocalMind` (HEAD of `main`, core 0.5.0 verified via `context-sync verify`). Read the following source files end-to-end:

- `.context/kickoff.md` + `.context/core/templates/kickoff.md` — the E2E protocol entry point
- `.context/core/rules/ai-engineering-protocol.md` (~1004 lines) — the cloud/sandbox edition protocol
- `.context/README.md`, `.context/memory/workflows/active.md`, `.context/memory/tasks/current.md`, `.context/memory/tasks/backlog.md`, `.context/memory/agents/sessions.md` (last ~10), `.context/memory/sessions/SUMMARY.md`, `.context/memory/plans/decisions.md` (ADR-8), `.context/memory/flaws/log.md`, `.context/memory/inefficiencies/log.md`, `.context/memory/overrides/rules.md`, `.context/memory/system/environments.md`, `.context/memory/system/ai-models.md`, `.context/memory/user/identity.md`, `.context/memory/user/preferences.md`
- `README.md`, `AGENTS.md`, `localmind.md`
- `backend/src/agents/base_agent.py` — `BaseAgent` abstract class, 5-step loop contract
- `backend/src/agents/registry.py` — auto-discovery of agent directories (ADR-8 Phase 1)
- `backend/src/agents/selection.py` — Intent → agent + primary_domain → agent mapping
- `backend/src/core/agent/orchestrator.py` — optional middle layer (plan + confidence + replan)
- `backend/src/core/agent/loop.py` (~110KB, skimmed) — the AgentLoop with plan-execute-verify phases
- `backend/src/core/agent/delegation.py` — immutable instruction packets, run contexts, structured results
- `backend/src/core/agent/sub_agent.py` (legacy, ~50KB, skimmed) — deprecated sub-agent framework
- `backend/src/tools/delegate.py` — agent-initiated delegation primitive (handoff only)
- `backend/src/agents/coding/playbook.md` — example playbook

### Codebuff (the research target)

Cloned to `/home/z/my-project/repos/open-codebuff` (public, anonymous HTTPS). The deep profile in `codebuff-deep-profile.md` was produced by a `general-purpose` sub-agent (Task ID 4) that read:

- `README.md`, `README.zh-CN.md`, `CONTRIBUTING.md`
- `agents/types/agent-definition.ts` (full `AgentDefinition` interface, 269 lines)
- `agents/types/tools.ts` (35 `ToolName` union + per-tool param schemas, 437 lines)
- `common/src/tools/constants.ts`, `common/src/tools/list.ts`, `common/src/constants/agents.ts`
- `packages/agent-runtime/src/run-agent-step.ts` (1320 lines — `runAgentStep` + `loopAgentSteps`)
- `packages/agent-runtime/src/main-prompt.ts`
- `packages/agent-runtime/src/tools/stream-parser.ts`, `util/stream-xml-parser.ts`
- `packages/agent-runtime/src/tools/handlers/tool/spawn-agents.ts`, `spawn-agent-utils.ts`, `spawn-agent-inline.ts`
- `packages/agent-runtime/src/run-programmatic-step.ts`, `tools/prompts.ts`, `templates/agent-registry.ts`, `templates/prompts.ts`
- Built-in agents: `agents/base2/base2.ts`, `agents/editor/editor.ts`, `agents/editor/best-of-n/editor-multi-prompt.ts`, `agents/editor/best-of-n/best-of-n-selector2.ts`, `agents/thinker/thinker.ts`, `agents/thinker/best-of-n/thinker-best-of-n.ts`, `agents/basher.ts`, `agents/file-explorer/file-picker.ts`, `agents/librarian/librarian.ts`, `agents/browser-use/browser-use.ts`, `agents/context-pruner.ts`
- `sdk/src/run.ts`, `sdk/src/run-state.ts`, `sdk/src/impl/agent-runtime.ts`, `sdk/src/impl/llm.ts`, `sdk/src/impl/model-provider.ts`, `sdk/src/tools/run-terminal-command.ts`, `sdk/src/agents/load-agents.ts`, `sdk/src/skills/load-skills.ts`
- `packages/agent-runtime/src/util/simplify-tool-results.ts`

Full citations in `codebuff-deep-profile.md` Appendix A.

---

## Key Findings (Executive Summary)

### LocalMind wins on

1. **Persistent semantic memory** — sqlite-vec + nomic-embed-text, passive retrieval every turn. Codebuff has no vector store.
2. **Multi-session `.context/` protocol** — git-tracked, typed memory files. Codebuff has only static `knowledge.md`/`AGENTS.md`.
3. **Strict delegation isolation** — immutable `DelegationInstructionPacket`, untrusted-evidence delimiters, `forbidden_tools` propagation. Codebuff's spawn is looser.
4. **Hit-limit-aware fallback messaging** — Session 32 contract distinguishes "iteration limit reached" from "model overload." Codebuff's `STEP_WARNING_MESSAGE` is generic.
5. **Local-first operation** — Ollama, no cloud dependency. Codebuff requires OpenRouter.

### Codebuff wins on

1. **Parallel delegation** — `spawn_agents` + `Promise.allSettled` is first-class. LocalMind has no equivalent.
2. **Best-of-N editing** — `propose_*` + selector + apply. LocalMind cannot express this.
3. **`handleSteps` generator** — agents are programs, not just prompts. Enables procedural workflows.
4. **`spawn_agent_inline`** — child mutates parent's history. Enables the `context-pruner` pattern.
5. **Per-agent model routing** — Opus for thinker, Flash Lite for basher, DeepSeek for reviewer. Sophisticated cost engineering.
6. **Abort signal + steering** — clean cancellation and mid-run redirection. LocalMind has neither.
7. **Bounded output buffers** — head+tail retention for long tool output. LocalMind has a hard 4000-char cap.
8. **State snapshots** — 5s checkpoint for crash recovery. LocalMind has none.

### Both share

- Multi-agent architecture with scoped toolsets per agent.
- Agent-as-directory/package organization.
- Wall-clock + iteration caps on the agent loop.
- No code execution sandboxing.
- Per-step observability via events / trace writer.

---

## Decisions Made This Session

1. **Research scope = Phase 2 only (review, no fixes).** The user said "purely research and comparison." No Phase 3 code changes. All findings filed as backlog items.

2. **12 borrowing recommendations grouped into 3 tiers.** Tier A (5 items, low-risk, borrow now); Tier B (4 items, medium-risk, post-ADR-8); Tier C (3 items, high-impact, needs cloud routing). Sequenced by dependency.

3. **5 "What NOT to borrow" items documented.** XML tool calling, centralized backend, Agent Store, `handleSteps` generator, `set_messages`/`add_message` tools — all would be regressions for LocalMind.

4. **B-2026-08-02-6 (parallel delegation) is the highest-impact gap.** Without it, LocalMind cannot express best-of-N, parallel research+coding, multi-perspective review, or speculative execution. Filed as Tier B (not Tier A) because it needs `asyncio.gather` over agent runs + `contextvars` propagation verification.

5. **B-2026-08-02-9 (inline delegation) is the riskiest item.** Breaks the strict isolation invariant. Deferred to Tier B, after -6/-7/-10 stabilize. Initial scope: only `ContextPrunerAgent` is inline-capable.

---

## Flaw I Caused This Session (also logged in flaws/log.md)

I created my own `kickoff.md` at `/home/z/my-project/download/codebuff-research/kickoff.md` instead of following the existing `.context/kickoff.md`. The user caught it: "Lol did you even read and understand how .context/ work? was kickoff.md read-only or create???"

**Root cause:** I read `.context/kickoff.md` (the front door that tells agents what to do) but treated it as a template to fill in, rather than as an instruction set to follow. I never loaded `.context/core/rules/ai-engineering-protocol.md` (Step 3 of the kickoff) — the actual protocol that tells agents where to write reports, how to log sessions, etc.

**Fix:** Deleted the bogus `kickoff.md`. Re-read `.context/kickoff.md` carefully. Loaded the cloud edition protocol. Followed it: wrote the review to `.context/memory/reviews/`, session notes to `.context/memory/sessions/`, backlog items to `.context/memory/tasks/backlog.md`, etc.

**Lesson for future agents:** `.context/kickoff.md` is READ-ONLY for agents. It's the front door that already exists in the repo. You READ it and FOLLOW its 4 steps (identify agent type → sync → read .context/ → load protocol → follow protocol). You do NOT create a file called kickoff.md. The only time kickoff.md is created/modified is at bootstrap (by the `context-sync bootstrap` command) or when regenerating a stale file (per the "If this file is stale or missing" section at the bottom of kickoff.md itself).

---

## Open Questions for the Maintainer

Documented in the review report (§6) and reproduced here for visibility:

1. Is parallel delegation in-scope for local-only setups (Ollama serializes by default)?
2. Is per-agent model routing acceptable given the local-first value prop?
3. Should `propose_*` tools be CodingAgent-only or available to all agents?
4. What's the migration path for the legacy `should_use_sub_agents()` framework?
5. Should the `context-pruner` pattern replace oldest-first trimming, or coexist?

These gate Tier B/C work. Tier A can proceed without answers.

---

## What Was NOT Done (Boundaries)

- **No product code changes** to LocalMind (per user's "purely research" instruction).
- **No baseline re-run** — research-only session; baseline carried forward from Session 64.
- **No online browsing beyond the cloned repos** — the Codebuff repo was self-contained; web-search/web-reader skills were available but not needed.
- **No verification of Codebuff's claims** — BuffBench numbers (61% vs Claude Code 53%) reported but not independently verified.
- **No load-testing or benchmarking** — performance claims taken at face value.

---

## Resume Instructions for Future Agents

If a future agent is resuming this work:

1. **Read the review report first:** `.context/memory/reviews/2026-08-02-review-1.md` — the 7-section formal report with findings by severity.
2. **Read this file** for the audit trail and decisions.
3. **Read `comparison.md`** (in this directory) for the full 10-section side-by-side.
4. **Read `recommendations.md`** (in this directory) for the 12 borrowing recommendations with concrete implementation steps.
5. **Read `codebuff-deep-profile.md`** (in this directory) only if Codebuff details are needed — it's the deepest reference.
6. **Check `.context/memory/tasks/backlog.md`** for the filed items `B-2026-08-02-1` through `B-2026-08-02-12` and their current status.
7. **Resolve the 5 open questions** in the review report §6 before starting Tier B/C work.

The cloned repos at `/home/z/my-project/repos/LocalMind` and `/home/z/my-project/repos/open-codebuff` may be stale by the time you read this (cloud sandbox wipes between sessions). Re-clone before relying on file paths or line numbers.

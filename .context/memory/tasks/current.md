# Current Task

**Status:** PLAN APPROVED — Session 302 (2026-08-20). User selected the warm Parent Kernel architecture and phase 1 scope: eliminate the per-turn parent-initialization model call.

## Architectural plan
- Boot a server-lifetime immutable `ParentKernel` with LocalMind identity/instructions, safety/playbooks, agent registry, lean tool schemas, provider/model adapter, metadata, and readiness state.
- Keep `ParentSession` state per chat: rolling summary + recent tail, objective, cwd, memory/failure recall, todos, steering, and abort state.
- Build a per-turn `TurnContext` with the latest message, attachments, workspace delta, and new tool evidence.
- Replace the current per-turn JSON initializer with the first normal native tool-capable parent call; it must handle direct prose and tools without intent-specific shortcuts.
- Start degraded if provider warmup fails and retry lazily; invalidate/rebuild the kernel on provider/model/key/thinking/tool/playbook/context-window changes.
- Do not assume cross-provider hidden KV-cache reuse; only cache immutable prompt sections, clients, and Ollama model residency.

## Decisions
- **Phase 1:** eliminate per-turn initialization — selected by user.
- **Context default:** summary + recent tail — recommended, awaiting override only if needed.
- **Boot failure default:** start degraded and lazy-retry — recommended, awaiting override only if needed.

## Constraints
- Preserve the closed-loop, recovery, completion-floor, safety, persistence, workspace, and live-testing contracts.
- The current `cb42a88` direct-boundary change is an interim measured fix, not the final warm-kernel architecture.

**Feature:** none
**ADR:** `.context/memory/plans/decisions.md` ADR-52
**Next implementation step:** design `ParentKernel`/`ParentSession` interfaces and live-test the first native tool-capable call before changing routing.

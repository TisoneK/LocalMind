# Current Task

**Status:** IDLE — Session 313 (thorough end-to-end system audit) complete; findings + 3 new backlog items recorded.

## Session 313 outcome
Booted the real app on isolated 8765 + z.ai/glm-4.5-flash and walked through 9 phases (bootup, greeting, capability, tool task, file create, multi-turn, web search, error handling, persistence).

### Plus points (7)
1. Boot fast + clean (parent-kernel ready ~3s, health surfaces parent_ready)
2. Conversational turns work well (Hi / What can you do? / Like what? — substantive structured answers, 1 iteration, no unnecessary tools)
3. Thinking streams in real-time (thinking_token SSE events)
4. Tool execution works end-to-end (list /tmp → shell(ls -la /tmp) → real synthesized answer)
5. Session persistence solid (sessions + messages + parent_sessions all survive backend restart)
6. Observability correctly surfaced (parent_session_turn_count)
7. Turn-init parallelism works (<1s gap before LLM call)

### Issues found (6)
- **H1 (High):** MiniMax XML interception conflicts with prose-commitment detector — "What is the hostname?" produced "I'll get the hostname..." as the final answer (prose preamble, no tool call). The XML path accepted the prose before the gate-level detector could nudge. → B-2026-08-20-10
- **M1 (Medium):** 429 rate-limit produces an empty answer bubble (no user-facing error message). → B-2026-08-20-11
- **M2 (Medium):** Recall accuracy after restart — model said first question was "Like what?" when it was "Hi" (weak-model reasoning limitation, not a harness bug)
- **M3 (Medium):** MiniMax XML fires on every turn (even "Hi") — z.ai quirk, adds an iteration of overhead
- **L1 (Low):** Latency on simple turns (8.6s for "Hi" — z.ai API, not harness)
- **L2 (Low):** Embedding failure when Ollama unavailable silently disables memory → B-2026-08-20-12
- **L3 (Low):** No POST /api/sessions endpoint (sessions only created implicitly via /api/chat)

### Honest scope note
Phases D-G (file create, multi-turn under load, web search, error handling) hit z.ai's 429 rate limit and couldn't be fully evaluated. Phases A-C, H, I are solid. A re-run after the rate-limit window (or on a different provider) would complete the audit.

## Next
- **B-2026-08-20-10 (High):** fix the MiniMax XML / prose-commitment conflict — the highest-impact issue (users get non-answers for tool tasks)
- **B-2026-08-20-11 (Medium):** surface 429 errors to the user
- Re-run the audit phases D-G after the rate-limit clears

**Feature:** none (idle — audit complete)
**ADR:** ADR-54 (ParentSession), ADR-53 (Parent-only), ADR-52 (warm kernel)
**Review:** `.context/memory/reviews/2026-08-20-review-79.md`

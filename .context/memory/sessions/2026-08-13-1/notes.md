# Session 184 Notes — ADR-22 Agent-First Routing + Smoke Verification

**Date:** 2026-08-13
**Agent:** Super Z / GLM-5.2
**Task:** ADR-22 implementation + real-model smoke against diverse prompts

## Smoke Evidence

The `smoke_184/` subdirectory contains:
- `SUMMARY.md` — aggregate analysis + per-prompt results table
- `01_find_path.md` ... `08_reasoning.md` — full SSE event transcripts for each of the 8 prompts
- `<prompt>_00_loaded.png` — UI screenshot at page load
- `<prompt>_01_typed.png`, `_02_typed.png` — UI screenshot after typing the message
- `<prompt>_99_final.png` — UI screenshot of the final rendered answer
- `00_initial_load.png` — the initial UI state before any prompt

## Key Findings

### ADR-22 works for all prompts that enter the agent loop

5/8 prompts were routed to AGENT_INTENTS. **ALL 5 had `agent_planning_start` + `agent_planning_done` fire.** The agent always plans now — the `_skip_planning=True` override is gone.

The proof: prompt #5 (shell/git log) had the signal fast-path trigger (`dispatcher_signal_detected` at 4.35s — message starts with "git"), but the agent STILL planned:
- Signal detected at 4.35s
- Routing hint provided at 4.37s (ADR-22 — signal becomes a hint, not a directive)
- Agent planning started at 6.50s
- Agent planning done at 9.42s
- Tool dispatched, gate passed

### 3/8 prompts were misclassified as CHAT by the dispatcher

| # | Category | Dispatcher classified as | Should have been | Root cause |
|---|---|---|---|---|
| 2 | calculate | CHAT (trivial fast-path) | CALCULATE | `is_conversational_question` matched "What is 17.5%..." — model answered 42 directly. Actually acceptable — the calculate tool would be overkill. |
| 4 | sysinfo | CHAT | SYSINFO | Dispatcher LLM (nemotron-3.5-lightning-free) misclassified "Tell me what OS I'm running" as chat. Free-tier model limitation. |
| 8 | reasoning | CHAT | SHELL/FIND_PATH | Dispatcher LLM misclassified "Show me what tests exist" as chat. Free-tier model limitation. |

ADR-22 cannot fix these — it only affects AGENT_INTENTS routing. The fix for #4 and #8 is either a better dispatcher model, or removing the trivial fast-path for tool-capable phrasings. That's a separate session.

## Latency

The ack latency (14-36s for agent-loop prompts) is dominated by the dispatcher's LLM call on the free tier (~10-30s). The agent's planning call adds 2-9s on top. This is acceptable for a free-tier model — the user sees status updates throughout.

## Conclusion

ADR-22 is shipped and verified. The agent now reasons before acting. The remaining "feels generative" cases are dispatcher misclassification (CHAT instead of AGENT_INTENTS) — a separate issue for a future session.

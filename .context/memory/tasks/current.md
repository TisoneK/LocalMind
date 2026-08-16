# Current Task

**Status:** idle — Session 252 completed (ADR-40 option C shipped + live-verified).

**Last completed:** On-demand long-tail tool loading (ADR-40 option C, B-2026-08-16-2): the 16 long-tail tools are no longer in the native `tools` param; a `describe_tool` meta-tool (the `skill`-loader pattern) loads ONE tool's full schema into the `tools` param for the rest of the run. Per-call catalog 16,937 → 7,851 chars (~54% cut, ~2,272 tok/call; ~68% vs pre-ADR-40) with the 14 core tools always-present lean. Loop bookkeeping via `ToolResult.metadata` (survives the `asyncio.wait_for` task boundary). 11 new tests + 3 updated surface pins; full backend suite 1,781 passed (4 pre-existing env-gated shell fails). **Live-verified on z.ai/glm-4.5-flash (weak, active) AND cerebras**: core shell selected directly (no regression); describe_tool("skill")→skill("python-testing") worked end-to-end on the weak model (with self-correction) and cerebras (no guess); final-answer truncation in the traces proven PRE-EXISTING via a stashed-baseline re-run. Report: review-42.

**Open next (implementation — its own session):** ADR-40 is now fully delivered (B + C; option A unnecessary — C reaches the ~90% theoretical reclaim). ADR-37 follow-ups (B-2026-08-15-10/11/12) remain open, plus review-42's suggestion: make `classify_failure()` only flag `tool_failure` when the failing step is terminal, so adapted runs (e.g. a describe_tool first-guess rejection) don't poison failure memory.

**Feature:** none

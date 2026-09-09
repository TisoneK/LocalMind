# Current Task

**Status:** ACTIVE — **Session 457 (Iris / claude-opus-4-8, Claude Code desktop, macOS) — solo.**

**Feature:** p0-context-engineering

**Task (owner directive):** P0 Step 4 **slice 2** — the behavioral half of the
Tool-Result Index + Search. Slice 1 (the storage engine
`backend/src/storage/tool_result_index.py::ToolResultIndex`) shipped in S446
(`7392173`). Slice 2:

1. Register a `search_tool_results` agent tool that queries the hybrid
   FTS5+vec0 index so the model can pull detail back on demand.
2. In `loop.py`, when a tool result exceeds the >5 KB index threshold, index it
   and replace the inline result carried into context with a short **stub +
   pointer** (result_id) instead of the full raw output.
3. **Live before/after on a research turn** — target reduction ~91 → ~500 tokens
   of carried tool-result history (per the manifest / addendum FINDING 7/8).
   Live bar is MANDATORY (workflows/active.md, S274 directive): real provider,
   isolated port 8765, before/after trace, grep the SSE for the actual number.

**Mode:** solo. Ravi (S456) row was stale (owner-confirmed, different machine);
removed at check-in. HEAD at start: `a41c5f7`.

**Env note:** live-testing scripts hardcode `REPO=/home/z/my-project/localmind`
(Linux dev box) — this is a macOS checkout at `/Users/bao/Code/LocalMind`; the
REPO/BACKEND/VENV_PY/SCRATCH top-of-script vars must be adjusted before any
live run (see system/live-testing.md).

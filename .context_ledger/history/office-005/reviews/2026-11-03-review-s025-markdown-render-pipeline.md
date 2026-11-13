# S025 Review — the markdown render pipeline (the owner's "the UI shows plain text" report)

**Date:** 2026-11-03 · **Agent:** Jengo (S025) · **Defect source:** owner message, 2026-11-03 session: "The UI does not format the output in style eg tables etc its just text"

## The diagnosis (evidence, not guesswork)

The complaint decomposed into three testable claims, and each was probed on the wire
(`scripts/live_test_markdown_render.py`, fake provider, real server, scratch home):

1. **The frontend renderer works.** `MarkdownContent` (react-markdown + remark-gfm +
   themed component map: tables, headings, lists, code) is wired into `ChatMessage` for
   every assistant answer, live and on history reload. Component pins now prove it:
   a well-formed GFM table renders as the themed `<table>`, emphasis as `<strong>`.
2. **The backend transport is clean.** The model's markdown crosses the SSE stream and
   the persisted history byte-exact (MD1–MD3) — nothing strips, re-fences, or re-wraps
   it. The only transport normalization found: the close path trims TRAILING whitespace
   (documented; content otherwise contiguous).
3. **The formatting CONTRACT never reached the model.** This is the root cause. The
   captured loop/parent requests show the answer turns rode the parent warm-kernel
   surface (and chat turns the chat surface) — and NEITHER registry carried the
   `response_formatting` section. Only the scoped execution-agent registry did, which
   ordinary turns rarely take. The model was never asked for markdown on the turns users
   ask for tables, so the (working) renderer had nothing to render. The same gap shaped
   the degraded input the renderer sees: GLM-family tables with full-width punctuation
   (U+FF5C ｜, U+FF0D ／ U+2014) and missing `| --- |` delimiter rows arrive as plain
   paragraphs — remark-gfm parses ASCII GFM only.

## The fix (three layers, one story)

- **Prompt contract on every answer surface** (`backend/src/core/agent/prompt/`):
  the response-formatting text now lives in ONE place
  (`sections/formatting.py`) and registers at the shared slot **405** on all three
  surfaces — parent (native bootstrap), chat, and the scoped agent. Slot 405 is after
  the tool index (400) so the SOCIAL relevance cut (a contiguous-suffix drop of
  tool-choosing guidance) can never strip the contract from a conversational turn, and
  before style_examples (410) so the suffix property holds. The section gained the
  renderer contract line: tables must be standard GFM pipe tables (ASCII `|`, a
  delimiter row), never full-width lookalikes. `SECTION_SLOTS` pins 405; the sysinfo
  prompt budget +100 (measured 11,569, justified per the budget test's own contract).
- **Renderer robustness for the degraded shapes** (`frontend/src/lib/markdownRepair.ts`):
  two new conservative passes inside the existing code-protected repair — (1) lines
  that START with a pipe (either width) and carry a full-width pipe get ｜ → | and
  dash lookalikes → `-` (prose em dashes and CJK dividers untouched, code spans
  extracted first); (2) a run of 3+ uniform leading-pipe rows with no delimiter row
  under the header (and not preceded by a pipe row, so real tables are never
  re-delimited) gets the `| --- |` row inserted.
- **Pins everywhere:** 8 backend pins (`tests/core/test_response_formatting_section.py`:
  all three surfaces carry the byte-identical text, the 405 slot, the SOCIAL
  byte-prefix property, the staged cuts keep the contract, the GFM line exists) +
  10 repair unit tests + 5 component tests (degraded shapes render real tables;
  fenced `｜` stays code; prose `｜` stays prose).

## Verified per the bar

- backend 3,955 passed / 2 skipped / 0 failed (unit, e2e excluded) + e2e 132 passed;
  frontend 693 passed (678 + 15 new) + `tsc -b` clean; ruff clean (CI gate `backend/src`
  + touched tests; the harness matches the standing scripts' lint posture, which sits
  outside the gate).
- NEW standing harness `scripts/live_test_markdown_render.py` **ALL PASS** (MD1 SSE
  passthrough of well-formed markdown; MD2 history persistence; MD3 degraded-shape
  passthrough; MD4 no false replan; MD5 the contract reaches the answering surface).
- Standing harnesses re-run ALL PASS: planner_lane, done_rules, goal_continuity,
  turn_close, prompt_structure, greeting_gate, arsenal_fixes, turn_trace; eval suite
  13/13 (completion 1.0, tool success 4/4, recovery 1/1, 0 unnecessary questions).
- Re-verified after the ruff import re-sort (the fix landed between suite runs):
  the touched test files re-run green (61 passed).

## Found en route (on the record, not silently dropped)

1. **The zero-tool forced-replan storm.** Probe B's first design (analyze-intent turn,
   a drawn plan, zero tool calls, a fake that cannot call tools) exposed the gate's
   zero-tool force nudging every remaining iteration — 20 provider calls of storm on
   one turn. A real model would call a tool or the turn would classify chat, so this is
   harness-induced — but the COST is real on any misclassified knowledge turn whose
   model keeps answering in prose. Backlog row added (B-2026-11-03-1).
2. **The harness dump race.** A whole-file `requests.json` rewrite under
   ThreadingHTTPServer lost every write to a concurrent truncate (0-byte dump with 24
   in-memory captures). The harness now appends one JSON line per request; the lesson
   joins the S024 routing lessons in the docstring.
3. **The close path strips trailing whitespace** from the final answer (found by MD3's
   first byte-exact assertion). Documented as intended transport behavior; the pins
   compare modulo trailing whitespace.
4. **S024's crash left the ledger close uncommitted** (roster Done, STATE regen,
   sessions/SUMMARY, backlog annotation, CHANGELOG edited but not committed). Committed
   first thing this session as 2897b0f6 — the owner's "why do you keep crashing before
   finishing" was this: the session died between the edit and the commit.
5. **The backend venv died with the sandbox reset** — rebuilt (`backend/.venv` via uv).
   Tests live at repo-root `tests/` (run from the repo root with the backend venv).

## Standing follow-ups

- The real-provider run of the new harness (does GLM-4.5-flash actually emit tables
  under the strengthened contract, and how often do the degraded shapes still occur?)
  on the owner's box — keys are not in this sandbox.
- B-2026-11-03-1 (the forced-replan storm cost bound).

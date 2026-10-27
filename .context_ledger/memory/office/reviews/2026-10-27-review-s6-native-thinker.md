# S006 Review — the consult shows the model's own reasoning (native thinker)

**Session:** 2026-10-27 — Amani (S006), part 3 · **Agent:** Amani / GLM (Z.ai) · **Scope:** `backend/src/core/agent/thinker/`, one comment block in `loop.py`, thinker tests, live harness
**Product commit:** `045199d` · **Claim:** `20261027T051045Z-Amani-6f60b5d5`

## The ruling

The owner, after watching a turn: "The thinker actually never thinks like any other agent eg dsh
thinks it just pretends to think." The S006 part-2 harness study had already named the contrast;
this made it a directive. The reference harness records the model's per-step reasoning faithfully
and has no component that writes thinking-shaped prose on demand. LocalMind's mid-loop consult was
the opposite by construction.

## What the consult actually was (grounded in code)

- The prompt (`thinker/prompt.py`) cast the model as "the agent's own inner voice — a careful human
  operator thinking out loud in first person," with style rules for the performance ("every sentence
  must do real work," 200-word visible-prose budgets).
- The streamed "thought" (`thinker/thinker.py`) was the ANSWER channel's authored prose, merged with
  the model's native reasoning (`piece = (chunk.text or "") + (chunk.thinking or "")`) and passed
  through a paragraph gate (`_ProseGate`/`_is_contract_meta`) that dropped anything resembling
  output-contract talk — mangling the model's real reasoning in the same pass.
- Both consult sites (first-tool-call and post-tool) already gated on `adapter.thinking_enabled` —
  the native reasoning channel existed every time the consult ran. The theater was layered on top
  of a live reasoning channel.

So the ThinkingBlock during a consult showed text written *because the prompt asked for
thinking-shaped text*. A performance, exactly as ruled.

## The fix (`045199d`)

One contract change, three files:

- **`thinker.py`** — the consult streams ONLY the adapter's native thinking channel, verbatim, as
  it arrives. The answer channel is buffered and never surfaced. Deleted wholesale: the prose gate,
  the contract-meta classifier, the JSON-marker hold-back machinery, the 1,800-char prose cut. The
  visible reasoning is now bounded by the wall-clock timeout and the provider's reasoning level
  (the reasoning-effort lever) — the same bounds as the main loop's native thinking. A provider
  that ships no reasoning channel leaves the panel honestly quiet; the decision still parses.
- **`prompt.py`** — no more casting. The analyst is told to reason in its reasoning channel and
  answer with exactly one JSON object and nothing else. The decision-quality rules stay: facts
  quote the evidence by name, ambiguities carry the default to proceed on, one next step,
  questions are not directives, nothing is invented, earlier analysis is built on by its delta.
- **`parse.py`** — `ThinkerAnalysis.reasoning` is now the native reasoning passed in by the
  consult; prose found in the answer channel is never re-cast as thought. Fail-safe parsing
  unchanged (malformed/JSON-less → empty structure, loop proceeds on its own).

`ThinkerAnalysis` consumers in the loop (`_thinker_context_block`, `_thinker_user_summary`,
`prior_analysis` continuity, bus fact) all consume the structured fields and are unchanged —
the wiring tests all mock the Thinker class, so the blast radius stayed inside the module.
The loop-side comment block describing the old prose contract was rewritten.

## Verification

- **Suite:** full backend **3662 passed / 2 skipped** (the −1 is arithmetic: 25 thinker tests
  rewritten to 24 against the new contract). Ruff check + format clean on every touched file.
  Ledger pre-commit gate green on both commits.
- **LIVE — zai / glm-4.5-flash, first run of the day: full PASS** (`scripts/live_test_native_thinker.py`):
  - check1 prompt JSON-only, no inner-voice casting: PASS
  - check2 surfaced thought == native reasoning channel, verbatim: PASS
  - check3 answer channel never surfaced: PASS
  - check4 no theater signature: PASS
  - check5 decision parsed: next_step = "Perform another web search to find more current fuel
    price information for Nairobi"; facts quote the evidence verbatim (petrol KES 189.84, diesel
    KES 171.84, effective 15 Oct) AND name the truncation as a fact — engagement without performance.
- **Throttled reruns (receipts, not failures):** the same checks held with the native channel at
  14,945 / 16,307 / 41,722 chars — including two consults the provider starved to the timeout,
  which degraded exactly as designed (verbatim reasoning shown, safe-empty analysis, loop
  proceeds). A static brace/schema-word scan in check3 was removed after it false-flagged the
  model's own reasoning content: once check2 proves the thought IS the native channel, braces in
  it are the model's own — the precise leak test is per-answer-line containment.
- **Provider walls (unchanged from part 2, plus one new):** cerebras → Cloudflare 403 (sandbox
  IP); chutes → 402 balance $0.00; **zai → after today's runs, 1113 "Insufficient balance or no
  resource package"** — the free package did not survive the verification series (one full consult
  plus three throttled reruns and a 429-bounded attempt). The decision check re-proves in one
  command once any provider is topped up: `LOCALMIND_ADAPTER=zai ZAI_API_KEY=… python
  scripts/live_test_native_thinker.py`.

## Process flaw logged (honestly)

One harness invocation exported provider keys with a `${P^^}_API_KEY=` prefix assignment; bash
treated the assignment as a command name and echoed two key VALUES into the session transcript
(never into any file, log, or commit — the secrets dir and every tracked file stayed clean). The
safe pattern (literal `case`-dispatched `export FOO="$(head -n1 …)"`) replaced it and cannot echo.
Recorded in `flaws/log.md`; rotation of the two exposed keys is the owner's standing practice for
anything that has travelled through plaintext.

## Filed, not built

- The runaway-reasoning shape seen in the throttled reruns (16K–42K chars of visible reasoning on
  a flash-tier model with no effort parameter) is the reasoning-level lever's business, not the
  consult's — already covered by the standing thinking-levels work; no new row.
- The part-2 addendum's borrowables (trajectory detail panels, harness-style compaction) stand
  unchanged; the consult now matches the harness's recording honesty, which was the prerequisite
  for those to be worth building.

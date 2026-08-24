# Current Task

**Status:** IDLE — Session 399 closed (sysinfo/observe bare-call guard exemption).

## Session 399 outcome

Fixed the dominant failure in the two 2026-08-24 chat exports: the model calls
`sysinfo` (or `observe`) with no query — the natural "show me my system" call —
and the loop's degenerate-input guard rejected it as "input too short", causing
retry spirals, zero-tool narration, and iteration-limit worker-report leaks.

| Commit | Summary |
|--------|----------|
| `5678a05` | `fix(agent): exempt input-optional tools from degenerate-input guard` (+ regression test) |
| this commit | `chore(context): log session 399 sysinfo guard exemption` |

**Root fix:** tools declare `input_optional=True`; guard consults it at all four
sites (single/parallel/minimax×2). `sysinfo` + `observe` marked. This unlocks the
Session 398 sysinfo expansion for the bare-call phrasing.

**Verification:** tools 508 passed, core 1267 passed (deterministic). New test
`tests/core/test_degenerate_input_guard.py`. Live-test in the real app pending.

**Remaining unchecked actionable backlog items:**
- B-10 (concrete planning — quality/prompt work)
- B-13 (persist system info at boot — backend)
- B-14 (connect Memory tab to backend)
- B-15 (auto-switch Terminal/Agents/Memory tabs)
- B-20 (rewrite code block preview)
- B-23 (advanced image viewer — needs scoping)
- B-24 (all UI components use CSS vars, no hardcoded styles)

**Watch (from export 1, likely downstream of this fix — re-observe first):**
- First-turn fabrication of system specs with zero tool calls (grounding).
- Narration ("Running the checks now…") that reaches the user mid-turn.

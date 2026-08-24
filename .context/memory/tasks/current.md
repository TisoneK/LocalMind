# Current Task

**Status:** ACTIVE — Session 399 burning down the B-2026-08-24 backlog one item at a time.

**Done this session:** guard exemption (5678a05), B-24-5 label swap (0827fdf), B-24-10 shell timeout 45→120s (e827e8b), B-24-11 psutil dependency (7552aa0), B-24-3 remove old tool selector (8447d22), B-24-4 agent-turn titles (9e374e1). All pushed.

**New items logged from user (2026-08-24):** B-24-13 (app-wide Settings-page texture/feel), B-24-14 (flaky real-time UI in Agent Workspace / action cards).

**Next candidates:** B-24-2 (failure-aware iteration cap), then the narration/thinking cluster B-24-1 + B-24-6 (incl. failure-path leak) + B-24-7 (gemini), B-24-9 (self-disclosure), B-24-12 (sysinfo native fallbacks), B-24-13/-14.

**LIVE-TEST:** user directive — do a live-test pass AFTER the backlog is worked through (not per-item). Read `.context/memory/system/live-testing.md` first. Live-testing will surface more backlog items. Ports 8000/3000 are the user's running app — coordinate before disrupting.

---

## Session 399 outcome (initial)

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

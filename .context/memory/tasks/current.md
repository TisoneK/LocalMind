# Current Task

**Status:** IDLE — Session 396 closed (B-9/B-12/B-21/B-22 UX sweep).

## Session 396 outcome

Completed 4 backlog items:

| Item | Commit | Summary |
|------|--------|----------|
| B-9 Action pill tooltips | `5b124d7` | shadcn Tooltip on compact pills: reasoning, input, output, error, duration |
| B-12 Clickable filenames | `5b124d7` | Code block headers + StepDetail file paths open FilePreviewDialog via custom event |
| B-21 Time formatting | `5b124d7` | All duration displays unified to `formatLatency()` (already had m/h support) |
| B-22 Token K/M format | `5b124d7` | New `formatTokens()` utility wired into PerformanceMetrics + MessageMetrics |

**Test results:** tsc clean; 330 frontend passed (18 pre-existing WorkspaceLayout failures unrelated); 13 progress tests (including new m/h + K/M cases).

**Remaining unchecked actionable backlog items:**
- B-10 (concrete planning — quality/prompt work)
- B-13 (persist system info at boot — backend)
- B-14 (connect Memory tab to backend)
- B-15 (auto-switch Terminal/Agents/Memory tabs)
- B-20 (rewrite code block preview)
- B-23 (advanced image viewer — needs scoping)
- B-24 (all UI components use CSS vars, no hardcoded styles)

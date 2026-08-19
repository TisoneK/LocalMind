# Current Task

**Status:** IDLE — Session 298 done (2026-08-19). code_exec run-a-file recovery +
phantom-instruction removal shipped + pushed. No task in progress.

## Latest shipped
- `575d175` (B-2026-08-18-7) — removed the phantom "do not read it back / write is
  confirmed / saved and verified" instruction from tool output + loop verification
  + system prompt; a file-write response is now purely factual (confirmed).
- `ee07182` (B-2026-08-18-8) — code_exec now RUNS a "python file.py" command via
  shell instead of a dead-end invalid_input (structural recovery, not a hint).

## Next (open, no user decision pending)
- **B-2026-08-18-4** — guaranteed ChatGPT-style weather card (structured wttr.in).
- **B-2026-08-18-6** — synthesis grounding (don't assert facts not in evidence).
- Known: z.ai init-timeout flakiness on live tests (slow provider, ADR-45).
- §40 efficiency roadmap: B-2026-08-17-8..12.

**Feature:** none

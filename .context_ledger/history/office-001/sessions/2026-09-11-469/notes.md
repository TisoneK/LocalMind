# Session 469 notes — worker-report leak fix (B-2026-08-25-4)

Session-scoped detail; durable facts live in the review report
(`memory/office/reviews/2026-09-11-review-s469.md`), the changelog, and the
inefficiencies log.

## Fix-design alternatives considered

- Presentation scrubber only (backlog option A): rejected as the sole fix —
  symptom-level, fights the model's output instead of the input that teaches
  it the format.
- Prompt rule ("never reproduce internal report formats"): rejected — the
  house direction is against hardcoded prompt patches for format problems,
  and it spends prompt budget on every turn for a rare failure.
- Chosen: strip at the model-facing history feeds (root: the format never
  re-enters a prompt) + deterministic strip at full-text emission boundaries
  (defense in depth; also keeps needs_report honest so the fallback report
  fires once, cleanly).
- Per-chunk `_filter_system_leaks` integration considered and rejected: the
  report block spans many streaming chunks; per-chunk regex can't match it
  (same reason `_strip_minimax_tool_calls_stream` exists). Strip where the
  full text exists (S332 buffering gave us those seams).
- Live-stream paths (conversational fast path) can't retract already-streamed
  text — accepted partial coverage, documented; with clean history those
  turns have no report in context to mimic.

## Live-verification mechanics (reusable)

- Scenario script: `scratch/s469_worker_leak_trace.py` — 3 turns, ONE
  session; the readback turn ("repeat your previous reply exactly") is a
  direct probe of whether the format is still in the model's context; hit
  classification = a hit whose content starts with "\n\n" + header is the
  deterministic append (fine), anything inside model-authored text is a leak.
- BEFORE state came from a throwaway worktree at the fix's parent commit
  (`git worktree add ../LocalMind-s469-before <sha> --detach`) with the main
  venv junctioned in; PYTHONPATH=<worktree>/backend/src gives worktree code
  precedence (verified by importing core.agent.models and checking __file__).
- Turn-2 answer length is model-stochastic — one run elaborated (no append
  planted), so two symmetric runs were needed; strengthen the prompt
  ("Reply with ONLY the number") and re-run both sides when the plant fails.
- Evidence kept: scratch/results-s469-*.json, sse-s469-*.sse,
  server-s469-*.log (+ the run console logs s469-{before2,after2}.log).

# Session 208 notes

The user reported that LocalMind took 9–15 seconds to respond to any message.
The trace separated two cases:

- Pure social greetings already use deterministic zero-LLM replies and should not
  wait for a provider.
- Substantive and direct conversational turns may still spend time in provider
  generation, but the transport had no server-visible acknowledgement before
  title persistence and engine prelude work.

The frontend already inserted a local assistant placeholder. That was not enough
for slow/cold clients or for the backend SSE contract, so `api.routes.chat`
now yields a `status_update` as the first event:

`LocalMind received your message — preparing the next step…`

The first event is emitted before first-turn title persistence, adapter setup,
memory retrieval, and model generation. Existing engine lifecycle, parent-agent
routing, direct greeting boundary, SSE keepalives, persistence, and tool privacy
remain unchanged.

Tests added in `tests/api/test_chat.py` assert first-event ordering. Focused and
full backend tests passed, as did all frontend tests, TypeScript, build, and
changed-file Ruff. The first frontend validation attempt used root-level npm
commands even though package scripts live under `frontend/`; rerunning from
`frontend/` passed.

Product commit: `06943b6`.
Review: `.context/memory/reviews/2026-08-14-review-13.md`.

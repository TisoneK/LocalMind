# Agent + Model Registry (update in place)

Which agents and models have worked on this repo — and what they've
shown they can and can't do here. Update your row each session (last
seen + session count); add a row if you're new. The Observations
section is how the user learns which agent to hand which task, and how
agents learn a predecessor's blind spots (and verify its work
accordingly).

| Agent | Model | First seen | Last seen | Sessions |
|---|---|---|---|---|
| Super Z | GLM-4.5 (Z.ai) | 2026-07-09 | 2026-07-11 | 3 |
| GitHub Copilot | DeepSeek V4 Flash Free | 2026-07-11 | 2026-07-11 | 2 |

## Observations

Concrete, evidence-based capabilities and limits — things demonstrated
in this repo's sessions, not marketing claims or self-assessment.
Update in place when a newer session contradicts an old observation.

- **Super Z / GLM-4.5:** Read tool truncates files >500 lines; needs `offset`/`limit` or `Grep` to navigate large files (`_pipeline.py` 2269 lines, `agent/loop.py` 2926 lines) (2026-07-11)
- **Super Z / GLM-4.5:** SSRF redirect bypass fix shipped with 3 regression tests, all green — verified capable of security fixes with test coverage (2026-07-11)
- **Super Z / GLM-4.5:** Anthropic streaming format bug identified by code reading (not runtime — no Anthropic API key available); fix based on Anthropic SSE event spec documentation. Untested against live Anthropic API — next agent with an Anthropic key should verify. (2026-07-11)
- **Super Z / GLM-4.5:** Identified the PAT redaction issue on first session (2026-07-09) — upload pipeline scrubs secrets from files. Workaround: PAT goes in chat, not the protocol file. (2026-07-09, confirmed 2026-07-11)
- **Super Z / GLM-4.5:** Pushed 10 commits in a single session without intervention — zero-interruption protocol works as designed with GLM-4.5 (2026-07-11)
- **Super Z / GLM-4.5:** Designed the `.context/` agent-memory system and co-developed the `ai-engineering-protocol` package with the user across multiple sessions (2026-07-09 to 2026-07-11)
- **GitHub Copilot / DeepSeek V4 Flash Free:** Demonstrated the "skip-Phase-1" anti-pattern — edited `.context/` files before reading the workflow or following protocol steps. User had to redirect multiple times. The 4 flaws logged from this session were all fixed in the protocol package by the next session (binding instruction rule, protocol source URL, no-task-too-small rule, two-surfaces section, session lifecycle markers). This session proved the `.context/` flaws-logging system works: friction was captured, moved to `flaws/`, and upstreamed to the protocol package without the user having to write any of it. (2026-07-11)
- **GitHub Copilot / DeepSeek V4 Flash Free:** Asks rhetorical yes/no questions instead of acting — when the answer is clearly "yes" (e.g. "Want me to commit and push?", "Should I add an observation?"), asks instead of doing. This burns a round-trip for confirmation on something the agent should infer from context + protocol. The pattern: agent proposes → user says yes → agent does. Should be: agent does. The protocol's zero-interruption principle already says this — the agent isn't following it when the action is obvious. Fix: if a proposed action is the **default** next step (commit after edits, push after commit, log after noticing a pattern), don't ask — do it and report. Only ask when there's genuine ambiguity (which of two approaches, whether to proceed despite risk, permission for a broad-scope change). (2026-07-11)

## Correction (2026-07-11 — Session 5)

The model logged as "GLM-4.5 (Z.ai)" in Sessions 1–4 was incorrect.
The actual model is **GLM-5.2 (Z.ai)**. The agent guessed the model
version in Session 1 (the system prompt doesn't state it) and copied
the wrong value forward. The user confirmed GLM-5.2 in Session 5.

Per append-only rules, prior entries are not edited — this correction
stands as the authoritative record. Future sessions record the model
as GLM-5.2 (or whatever the user confirms in Pre-Flight).

Updated registry row:

| Super Z | GLM-5.2 (Z.ai) | 2026-07-09 | 2026-07-15 | 8 |

Observations above attributed to "GLM-4.5" were produced by GLM-5.2.

- **Super Z / GLM-5.2:** Session 7 sweep review — found and fixed the last 2 DRY violations from Session 6's provider consolidation (`config.py` was still reconstructing settings field names via string manipulation instead of using the derived `ADAPTER_MODEL_FIELDS` map). Also caught a stale README "Known Issues" bullet referencing the pre-`.context/` legacy `REVIEW.md`. Did NOT re-confirm the model version with the user this session — relied on the Session 5 correction in this file. If the model has changed since Session 5, this session's entries are mislabeled. (2026-07-11)
- **Super Z / GLM-5.2:** Session 9 — narrow context-sync session only. Did NOT run baseline checks (no venv, no ruff, no pytest, no tsc, no eslint). Did NOT perform code review. Did NOT re-confirm model version with user (4th session in a row carrying forward GLM-5.2 from Session 5 — should ask the user to confirm next time the model is discussed). Discovered that Session 8 (commits `586c7ad`, `09751b8`, `55e702a` on 2026-07-11 — fixing Session 7 flaws) was never formally logged in `agents/sessions.md`. Logged as flaw F-2026-07-15-1. (2026-07-15)

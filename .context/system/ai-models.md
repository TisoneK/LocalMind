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
| GitHub Copilot | DeepSeek V4 Flash Free | 2026-07-11 | 2026-07-11 | 1 |

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

## Correction (2026-07-11 — Session 5)

The model logged as "GLM-4.5 (Z.ai)" in Sessions 1–4 was incorrect.
The actual model is **GLM-5.2 (Z.ai)**. The agent guessed the model
version in Session 1 (the system prompt doesn't state it) and copied
the wrong value forward. The user confirmed GLM-5.2 in Session 5.

Per append-only rules, prior entries are not edited — this correction
stands as the authoritative record. Future sessions record the model
as GLM-5.2 (or whatever the user confirms in Pre-Flight).

Updated registry row:

| Super Z | GLM-5.2 (Z.ai) | 2026-07-09 | 2026-07-11 | 5 |

Observations above attributed to "GLM-4.5" were produced by GLM-5.2.

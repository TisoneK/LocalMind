# Current Task — THE THINKER/AGENT REBUILD (start here next session)

**This is a focused, multi-step rebuild, not a patch. Do NOT ship more
single-prompt fixes. Cure the disease.** (User, Session 237: "diagnosing a
single prompt means we are curing one prompt, not the disease — fix the
Thinker and Agent.") Use ANY capable model; if a model fails to run tools,
that is OUR bug, not the model (user: "use any, they are all capable").

## The disease (root cause — established live, Session 237)
The agent **reasons before it looks, and all at once.** One monolithic init
call classifies + acknowledges + decides direct/clarify/execute + invents
`facts` + lists `ambiguities` + commits a 5-6 step `plan` — BEFORE any tool
runs. So every symptom is one root: it asks for a CV path instead of
searching (decided blind), over-plans (committed blind), the "Thinker" is
empty/shallow (assessing assumptions, not reality), and it makes too many
calls (rigid upfront checklist) → trips per-minute rate limits.

## The cure (target architecture — ADR-36/37/38 unified)
Move reasoning INTO the loop, onto evidence:
1. **Init = classify-only** (tier: trivial / chat / needs-tools) + the opening
   line. NO upfront plan, NO upfront facts/ambiguities.
2. **Act first** — take the one obvious next step (CV → search).
3. **Thinker consults on the RESULT** — real facts/ambiguities on real data
   ("found Tisone_CV.pdf + resume_old.docx; picking newer"), streamed live.
4. **Decide next step. Repeat.** The plan EMERGES; never committed blind.

## Work sequence (each step live-validated against a working tool model)
- **Step 0 — Tool-calling actually fires.** gemini-2.5-flash (OpenAI-compat
  path) returns empty/no-tool on the first execute call (Session 237 trace:
  788ms empty, "fabrication warning"). deepseek-v4-flash-free ran tools
  cleanly; nemotron looped. Make the loop reliably get a tool call out of the
  configured model (inspect the OpenAI-compat tool payload sent to gemini's
  `generativelanguage.../openai/` endpoint; when a model returns
  text-without-tool on an execute iter-0, REPROMPT with a forced tool nudge
  instead of failing empty — loop.py:3522/3695). Without this, nothing else
  can be validated.
- **Step 1 — Gut the init to classify-only.** Stop generating the plan +
  facts/ambiguities upfront (initialization.py). Keep tier + ack.
- **Step 2 — Mid-loop Thinker consult** (ADR-38): after the first evidence
  step, call the model to assess the gathered evidence → facts/ambiguities →
  stream to ThinkingBlock, collapse-after-done.
- **Step 3 — Emergent step-by-step decisions** (no upfront checklist);
  synthesis fix (fbe9d6d) ensures a real final answer.
- Then: three-tier routing, rate-limit backoff/recovery for transient RPM.

## Already shipped this arc (KEEP; not the cure but real): spacing fix,
token-metric fix, paste buttons, no trivial theater (direct mode), act-not-ask
init prompt, synthesize-on-empty-answer. **User's build was stale** — they
must `git pull && npm run build` so they stop re-hitting fixed bugs.

## Model: use whichever runs tools now (test deepseek quota; else a zen paid
model). Trace harness: backend from source + `curl /api/chat`, parse
`agent_initialization_done`/tool_call/token.

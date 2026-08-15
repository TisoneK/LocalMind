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
- **Step 0 — Tool-calling actually fires. ✅ DONE + LIVE-VERIFIED (Session 238,
  commit `e2c73c9`).** gemini-2.5-flash (OpenAI-compat path) returned
  empty/no-tool on the first execute call (Session 237 trace: 788ms empty).
  Fixed in two layers: (1) the loop passes `tool_choice="required"` on
  iteration 0 of a tool-required intent — the OpenAI-compat adapter previously
  accepted but IGNORED the param, now it lands in the payload with a 400-degrade
  retry; (2) empty/text-without-tool on iter-0 → ONE bounded forced-tool nudge
  (`AgentTrace.tool_forced_recoveries`, `_MAX_TOOL_FORCE_RECOVERIES=2`, gated to
  iteration 0) before the Session 115 honest fail. Live trace on the exact
  failing model (gemini-2.5-flash): "list the projects in my dev folder" →
  `tool_call shell (ls -F /Users/bao/Code) started→done` with the real listing;
  no empty/fabrication events. 7 new tests; 1827 backend pass (5 pre-existing).
- **Step 1 — Gut the init to classify-only. ✅ DONE + DELETED (Session 239,
  commit `e442f3b`).** The init is strictly classify-only: tier + ack +
  objective only. The legacy fields (facts/ambiguities/tool_names/plan_steps/
  success_criteria) were DELETED from the decision, parser, `plan_text()`
  (now `objective_line()`), the streaming block, and the events — a model
  returning them is ignored, not preserved. Also deleted the orphaned legacy
  intent system (thinking_dispatcher/execution_graph/workspace-orchestrator/
  routing_helpers + their models.py contracts — zero callers since Session
  201) and FIXED the prompt-budget drift (B-2026-08-15-13: now 2,097 chars).
  Live trace: `agent_initialization_done` = {mode, objective, confidence,
  init_prompt_chars}; no upfront todos; gemini hit a free-tier 429 on the
  execute call (environmental).
- **Step 2 — Mid-loop Thinker consult (NEXT, ADR-38):** after the first
  evidence step, call the model to assess the gathered evidence →
  facts/ambiguities → stream to ThinkingBlock, collapse-after-done.
  **UNBLOCKED now** — Step 0 means evidence is actually gathered, and Step 1
  removed the init's pretend-assessment.
- **Step 3 — Emergent step-by-step decisions** (no upfront checklist);
  synthesis fix ensures a real final answer. NOTE: the Session 238 live trace
  still ends with "✓ 1/1 criteria met" gate text instead of the listing — the
  ADR-37 B-11 synthesis gap is user-visible (B-2026-08-15-11).
- Then: three-tier routing. **Rate-limit backoff/recovery for transient RPM:
  DONE (Session 240, `6c77b72`)** — gemini's per-minute 429 was misclassified
  permanent (it embeds "retry in Ns" in the BODY, and says "billing details"
  on every 429); now a short window recovers invisibly and a long one surfaces
  in ~600ms instead of hanging. Truly-spent free-tier quota still can't be
  retried — the durable fix is fewer calls + the prompt diet below.
- **Prompt diet (NEXT highest-leverage token/latency win, Session 240 measured).**
  The execute system prompt (`agent/prompts.py build_agent_system_prompt`) is
  ~6.2k tokens re-sent EVERY loop iteration (~9k prompt tokens/call, ~18k for a
  2-call "list a folder"). De-dupe (anti-fabrication appears twice) + tier-load
  rarely-needed rules; validate each cut live (those rules fixed real bugs).
  Target ~6.2k→~3k. Tools already scoped per intent (Session 124).

## Already shipped this arc (KEEP; not the cure but real): spacing fix,
token-metric fix, paste buttons, no trivial theater (direct mode), act-not-ask
init prompt, synthesize-on-empty-answer, **Step 0 forced tool-calling
(Session 238, `e2c73c9`)**, **Step 1 classify-only init + legacy intent-system
deletion (Session 239, `e442f3b`)**. **User's build was stale** — they
must `git pull && npm run build` so they stop re-hitting fixed bugs.

## Model: gemini-2.5-flash is the ACTIVE provider (app Settings; key not in
`.env`) and now runs tool loops cleanly (Step 0 live-verified). Trace
harness: backend from source on `LOCALMIND_PORT=8765` +
`LOCALMIND_SHELL_ENABLED=true` + `curl -N /api/chat`, parse
`agent_initialization_done`/tool_call/token. Port 8000 is the user's running
app — never kill it.

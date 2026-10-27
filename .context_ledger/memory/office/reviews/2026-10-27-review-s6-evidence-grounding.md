# S006 Review — Evidence-grounded answers (the Kitengela weather fabrication autopsy)

**Agent:** Amani (S006) · **Model:** GLM (Z.ai) · **Date:** 2026-10-27 · **Core:** 2.2.0
**Trigger:** the owner pasted a failed LocalMind session (provider: cerebras, model
gpt-oss-120b): "whats the weather like in Kitengela" produced a confident 7-day
forecast whose figures exist in no source the turn ever touched. Follow-up
"you can't even archie your goal" got a tone-deaf clarification request.

## The failure chain, layer by layer (all grounded in code + live probes)

1. **Acquisition — chrome as evidence.** meteoblue renders its forecast via
   JavaScript; the static HTML the fetch tool reads yields navigation chrome
   (language lists, promos, "popular places" temperatures for OTHER cities).
   `web_fetch` returned `success=True` with ~10K chars of it — the loop counted
   real evidence where there was none for the subject. Live-probed 2026-10-27
   through the actual extraction code: extract 9,964 chars, subject+temperature
   row absent (the only "Kitengela + numbers" adjacency is the heading "Weather
   for popular places around Kitengela" next to Nairobi's 26/18).
2. **Retrieval — re-querying the chrome.** The model re-queried the stored
   chunks (`search_tool_results`); the top hit was the header chunk. Retrieval
   worked; the data simply was never there. Not a ranking bug.
3. **In-loop fabrication interceptor — head-only.** The zero-tool fabricated-data
   detector checks only the answer's head (~150-char lookahead before live
   streaming). The Kitengela answer opened with meta-talk; the invented figures
   arrived mid-answer, after the veto window. Late matches are logged and "the
   answer stands" — by design of the streaming tradeoff.
4. **Acceptance gate — the hole.** `_acceptance_gate_at_final_answer`'s
   no-criteria detectors (prose-commit, action-narration, the turn-outcome seam:
   pending-action / follow-through / punt / scaffold / post-evidence narration /
   hedge) all judge whether the model ACTED or ANSWERED. None asks whether the
   figures it asserted exist in the evidence. The fabricated forecast passed.
5. **Sufficiency — digits equal data.** `_check_sufficiency` treats any
   `has_specific_values` as SUFFICIENT for a fetched page; the chrome is full of
   digits (other cities' temps), so it passed as data-bearing.
6. **Post-synthesis filter — cmd.exe only.** `_filter_synthesis` catches
   "Volume Serial Number"-style artifacts, nothing for invented weather/scores.
7. **Presentation — meta-talk reached the user.** "I was unable to retrieve the
   full content… I will try to extract…" (the model's own tool-struggle
   narration) shipped inside the answer. `answer_is_internal_scaffold` only
   catches injected-scaffold leaks, not tool-mechanics narration.

The gate machinery itself worked where designed: iteration 3's
"committed to a tool action in prose but emitted no tool_call" was caught and
replanned (`gate_failed_replan` in the export).

## What was fixed (commit c118898)

**New deterministic criterion on the parent final-answer path**
(`core/agent/evidence_grounding.py` + wiring in `_acceptance_gate_at_final_answer`):
every figure-bearing assertion (temperatures, wind, precipitation bands,
humidity, sunshine hours, prices) must appear as numbers somewhere in the
turn's evidence pool — tool observations and inputs, conversation messages,
and the full stored chunks of stubbed large results (new
`chunks_for_result()` read on the tool-result index). A figure found nowhere
was invented: the gate withholds the answer, emits the standard
`agent_loop_gate_failed_replan` event, names the invented figures in one
stage-card nudge, and the loop redoes the answer grounded — or honestly
reports the gap. One-shot marker `[EVIDENCE GROUNDING]`; iteration-budget
guarded; skipped for zero-tool turns (the injected-context gate owns those)
and answer-only calls.

**Design decisions the probes forced:**

- **Figure-presence, not association.** A first draft required the figure to
  co-occur with the subject (place) in one evidence window. The live probe
  killed it from both sides: meteoblue's "popular places **around Kitengela**"
  heading puts Nairobi's temps within a window of the word Kitengela
  (false-pass), and JSON evidence (wttr.in) keeps subject and values far apart
  (false-fail on the positive control). Presence-anywhere is precise: a figure
  genuinely read leaves its digits behind. Wrong-row attribution (quoting
  Nairobi's exact numbers for Kitengela) stays open — see backlog.
- **Standalone single digits.** "0-5 mm" must not pass because "2026" contains
  a 0 and "25°C" a 5: single-digit runs must appear as standalone numbers,
  multi-digit runs may substring-match (rounded quotations like "27" from
  "27.5" pass).
- **No web_fetch quality heuristic.** A draft "thin-content" detector died in
  the probe: it would have flagged wttr.in (the best source — JSON has no long
  sentences) and passed meteoblue (its news blurb is real prose). The tool
  layer stays untouched; the honest signal lives where the question lives —
  the gate.
- **The answer can never ground itself.** The loop records the final answer as
  a tool-less trace step BEFORE the gate runs, and earlier-turn narrations sit
  in the conversation — the evidence pool is therefore tool-steps-only
  (observations + inputs) plus messages; a tool-less step contributes nothing.
  Caught by test before it shipped (the first wiring test used an unrealistic
  assistant echo and passed vacuously; the step-based leak is now a regression
  test).

**Against the real failed answer and the real chrome evidence** (both fixtures
in `tests/core/test_evidence_grounding.py`): 27°C ×2, "0-5 mm", "0-10 mm",
"10-20 mm", "4 hours of sunshine" flagged — 5 ungrounded figures, gate fires,
nudge names them, second attempt accepted (one-shot). Grounded answers
(figures present, rounded quotations, honest gap reports) pass; zero-tool and
figure-free turns untouched.

## Verification status (report what was verified, how, and what remains)

- **Live web evidence (real fetches through the actual extraction code, this
  sandbox, 2026-10-27):** meteoblue chrome confirmed; weather.co.ke's static
  extract also lacks a Kitengela temperature row (2,959 chars); wttr.in
  returns full JSON data. Probe script kept sandbox-side
  (`/home/z/my-project/scripts/probe_web_evidence.py`, not committed).
- **Unit + gate-level (real gate method, no LLM):** 13 new tests + the
  acceptance-gate/turn-outcome/hedge/parent-readiness/storage suites; full
  backend suite **3653 passed / 2 skipped** (via `scripts/venv-run.sh pytest tests -q`).
- **Provider live run: NOT YET DONE — no provider credential exists in this
  sandbox and handling credentials is out of bounds for agents.** The
  committed harness `scripts/live_test_evidence_grounding.py` (same boot /
  fire / SSE-capture pattern as `live_test_cybercafe.py`) runs the repro in
  one command once a scratch `settings.json` exists:
  `cd backend && ../scripts/live_test_evidence_grounding.py --label fix`.
  It scores the turn for the grounding replan event, the fabrication
  signature in the delivered answer, and honest-gap wording, plus a
  figure-free control. Until that run, the criterion is proven at the
  gate/unit level and by the live-web fixtures — not on a real model turn.

## Open items (filed in the backlog, not silently dropped)

- **Association-level grounding** — "26/17 for Kitengela" assembled from
  Nairobi's row passes the presence check. Needs a judge, not a regex
  (bounded, on the turn-bus lane like the reply-is-pending judge).
- **Feedback-turn routing** — "you can't even archie your goal" took the
  clarification lane; a complaint about the previous answer should surface
  the prior turn's evidence and retry/refute, not ask what "archie" means.
- **Acquisition for JS-rendered data pages** — the browser tool exists; a
  guided handoff (fetch quality signal → "use the browser tool") would cut
  the wasted iterations the gate cannot recover. Needs a safe quality signal;
  the probe showed the naive ones are unsalvageable.

## Residuals (accepted, logged)

- Figures quoted from the middle of a stubbed large result without a
  re-query are not in the pool → one bounded nudge; the model re-quotes via
  `search_tool_results` (which enters the pool) or drops the figure.
- A model that invents a figure in mid-turn narration and repeats it in the
  answer self-grounds through that narration. Narrow; belongs to the judge
  work above.
- Non-parent agents (research etc.) and the criteria-based gate path are not
  wired to the criterion yet; the exhibited failure was a parent no-criteria
  turn.

---

## Addendum — the same day, owner follow-up (still S006)

The owner pushed six connected complaints. Separated, diagnosed, and what was done:

1. **"push committed work first" + "why do you think secrets/ exist for???"** — the
   fresh sandbox had lost the prior session's secrets with its machine, and S006
   treated "no PAT" as a wall. Ruling recorded in `user/preferences.md`: credentials
   provided in chat are stored per `secrets/README.md` and used. PAT + five provider
   keys now live there (gitignored, 0600); six commits pushed, then the fix below.
2. **The one-sentence thought that pretends** — root cause found and it is the same
   disease as the grounding hole: the post-tool Thinker consult is fed the
   head+tail observation STUBS, and its prompt demanded "two to four sentences".
   A thinker fed stubs and a sentence floor produces theater by construction.
3. **"final answer is just the evidence"** — the synthesis-from-trace and rescue
   fallbacks also reasoned over stubs (the rescue cut every tool message to
   1,500 chars, head+tail only), and the deterministic worker report — raw
   evidence in the chat — stood in as the answer.
4. **"truncation on output"** — the full text existed all along in the index;
   nothing that thinks read it.

**Shipped (`b7f7985`):** `core/agent/full_evidence.py` — the bounded full-text view
(stored chunks of stubbed results, full copies of small results, newest first);
the post-tool Thinker now reasons over it; the Thinker prompt requires engaging
the results by name (quote the value/gap, say what it settles, decide the next
move) with the anti-rambling ceilings unchanged; `_synthesize_final_from_trace`
and `_force_final_answer` read full evidence (rescue per-result cap 1,500 →
6,000); the last-resort worker report opens with "I could not produce a clean
final answer from these steps" (framing stripped from model-bound history by the
same block pattern). Suite: **3663 passed / 2 skipped**.

**deepseek-harness study (owner pointed at it for thinker/system-prompt/
trajectory):** read its agent-loop, trajectory UI, and lifecycle docs. The load-
bearing contrast: the harness has NO separate thinker component — the model's
own native reasoning (per-step `reasoningEffort`) is the thinking, and the
trajectory view records it faithfully per step (cell kinds system/user/context/
compacted/message/tool/subtool, each with full detail panels: thinking, source
blocks, output, schema, timing). LocalMind already streams native GLM thinking
(ThinkingBlock); what it lacked was feeding that layer real evidence — now fixed.
Borrowable later, filed not built: trajectory-record-style detail panels for the
Actions tab (extends the parked Harness-shell-parity row), and the harness's
compaction pattern (prune/summarize under pressure) as the long-run alternative
to head+tail stubs.

**Provider live run — still blocked, with receipts this time:** cerebras →
Cloudflare 403 on the sandbox IP (HTML challenge page); zai → 429 "Insufficient
balance"; chutes → 402 "account balance is $0.0"; gemini → 400 "User location is
not supported"; zen → 401 "api_key_expired"; bankofai → no key ever provided.
The harness (`scripts/live_test_evidence_grounding.py`) now honours a
caller-exported `LOCALMIND_ADAPTER` + key env, so any ONE working provider runs
the full repro in a single command. The zai key balance and the expired zen key
are the owner's to recharge/rotate; a bankofai key would be the cleanest per
`system/live-testing.md`.

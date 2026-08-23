# Live-testing the agent (mandatory before claiming an agent/tool/adapter change works)

**Audience:** every agent working on LocalMind's backend agent loop, tools, or
provider adapters. **Read this before you write "done", "works", or "verified".**

## Why unit tests are not enough

The user has said the unit tests "do not tell the truth — they are designed to
pass certain conditions." That is exactly right, and this file proves it three
times:

- **todo_write (S274):** every unit test passed, but the REAL agent path was
  broken — `_extract_tool_input` stringified the tool's array argument as a Python
  repr (single quotes), so the model's call failed JSON parsing on every
  invocation. Only a live trace exposed it.
- **shell output bounding (S272):** an ADR claimed shell dumped raw stdout; reading
  the actual capture path (and running it) showed it was already bounded. The
  assumption, not the code, was wrong.
- **GLM think-and-act (S253):** "the model is weak" was wrong — the harness had
  disabled its reasoning. Only comparing a real before/after trace found it.

A green suite means the code didn't violate its own assumptions. It does **not**
mean the real model+provider+loop path works. Those are different claims. Unit
tests pin structure; live traces prove behavior.

## Providers: bankofai is the workhorse, zai for the slow model

- **bankofai / deepseek-v4-flash — fast AND free. This is the PRIMARY
  live-test provider.** Adapter value: `LOCALMIND_ADAPTER=bankofai`. If a change
  works on bankofai, it works for the common case. Every benchmark and repro
  script in `scripts/` boots with this by default.
- **zai / glm-4.5-flash — the slower/lower (weaker) model.** Use it when the
  behavior must ALSO hold on a slow/weak model (routing, guard, and tool-selection
  changes — weak models regress differently), and as fallback when bankofai is
  rate-limited. Adapter value: `LOCALMIND_ADAPTER=zai`.
- Both are free tier; **rate limits are expected** (bankofai 429s surface inside
  the SSE stream as an error event, not always as HTTP 429 — see the benchmark's
  retry logic). Preserve the evidence and note the rate limit; don't claim success
  through it.
- Provider/model are set in the APP's settings file (`~/LocalMind/settings.json`),
  NOT `backend/.env` — copy that file into the scratch home to know what's really
  loaded. **Never cat it; never print keys.**

## The scripts-based live-test workflow (current — use these, don't hand-roll)

All live-testing now runs through the committed harnesses in `scripts/`. They
encapsulate the whole loop from Session 330's one-command gotcha: boot isolated
server on **port 8765** with scratch `LOCALMIND_HOME`, wait for `/api/health`,
fire the prompt(s), capture SSE, parse + score, save artifacts into `scratch/`,
and kill the server in `finally`. **One script invocation = one self-contained
trace** (a backgrounded server does not survive across separate terminal calls).

| Script | Purpose |
|--------|---------|
| `scripts/live_test_cybercafe.py` | Quick repro harness — ONE prompt (or a small set). `--label baseline\|fix-N` marks before/after runs; saves `sse-<label>-<name>.sse` + `results-<label>.json`, prints latency/tools/event-type counts/usage/duplicate heuristics. |
| `scripts/lm_benchmark.py` | The full benchmark suite (52 tests across CAT1/2/6/9/14/15 + LM-* categories; catalog in `.context/memory/system/test-catalog.md`). Per-test PASS/PARTIAL/FAIL scoring, 60s timeout, 15s cooldown, 429 retry with 30s backoff, partial results saved after every test. |
| `scripts/lm_collision_tests.py` | Multi-guard collision suite (COL-1..10 + MEM-*) — what happens when MULTIPLE pre-init guards match the same prompt. Same harness/score format. |
| `scripts/run_benchmark_detached.sh` | Fully detached benchmark run (`setsid` + `nohup` + `&`) so a long suite survives agent/terminal disconnect. Poll the log (`scratch/bench-detached.log`), results land in `scratch/`. |
| `scripts/run_collision_detached.sh` | Same, for the collision suite. |
| Older one-offs (`live_test_glm_tool_trace*.py`, `live_test_prose_commitment.py`, `live_test_post_loop_synthesis.py`, `live_test_session305.py`, `live_trace_empty_answer.py`, `live_test_compaction.py`, `live_test_extractor.py`, `live_audit_full.py`) | Repro/debug traces from earlier sessions — keep as templates; the harness pattern is identical. |

**Usage examples:**

```bash
cd backend && ../scripts/live_test_cybercafe.py --label baseline          # one-shot repro
cd backend && ../scripts/live_test_cybercafe.py --label fix-2 --prompts cybercafe,hello
../scripts/lm_benchmark.py --list                                          # list test IDs
../scripts/lm_benchmark.py --tests CAT2-1,CAT2-2,CAT2-3                    # targeted regression
../scripts/lm_benchmark.py --category CAT1                                 # whole category
../scripts/lm_collision_tests.py --tests COL-1,COL-2
./scripts/run_benchmark_detached.sh "CAT1-4,CAT2-1" 60 15                  # long runs, detached
```

Notes:
- The committed scripts hardcode `REPO = /home/z/my-project/localmind` (the Linux
  dev box). On another checkout, adjust `REPO` / `BACKEND` / `VENV_PY` /
  `SCRATCH` at the top of the script first.
- Artifacts land in `scratch/`: `server-<label>.log`, `sse-*.sse`,
  `results-*.json`, `benchmark-results-*.json`. Keep them for the report; they are
  the evidence.
- Full-suite runs take a while (52 tests × up to 60s + cooldowns). Budget real
  time or use the detached runner.

**The debugging loop (reproduce → read → fix → re-run):**
1. Reproduce with a repro script at `--label baseline`.
2. Read the trace until the MECHANISM is visible (see next section).
3. Fix. Re-run the SAME prompt at `--label fix-N` (or the benchmark subset).
4. Compare the two summaries — that is the proof.
5. Regression: run the affected benchmark category + the full backend suite.

## Reading a trace: what the SSE/log actually tells you

```bash
# Which tools ran, in what order, with what latency:
grep -aE "iter=[0-9]+ (LLM|tool_call=)|finished iter" scratch/server-*.log
# The SSE events that matter (todo_*, tool_call, thinking_token, obs_event, done):
grep -oE '"type": *"[a-z_]+"' scratch/sse-*.sse | sort | uniq -c
# Token cost (the real number, from provider_usage on turn_complete):
grep -o '"provider_usage":[^}]*}' scratch/sse-*.sse | tail -1
# Errors / validation failures the model hit:
grep -aiE "error|validation|traceback" scratch/server-*.log | head
```

Key observability signals in the SSE:
- `agent_loop_gate_failed_replan` — gate rejected an iteration → replan fired.
- `agent_loop_iteration_discarded` — buffered iteration text was withheld because
  the gate failed (the S332 duplicate-answer fix).
- `agent_loop_gate_honest_stop` — iteration cap hit with unmet criteria; the model
  stopped honestly.
- `turn_complete` `provider_usage` — the real token numbers. (S331 trap: the
  `turn_complete` event has NO `success` field — parse `gate=pass/fail/?` from the
  server log instead of assuming the harness is right.)

## The bar (what "verified" requires)

1. **Real provider, real model.** Primary trace on **bankofai/deepseek-v4-flash**
   (fast + free — if it works there it works). For anything touching routing,
   guard selection, or tool SELECTION/schemas, ALSO trace on the slow/weak model
   **zai/glm-4.5-flash** — weak models regress differently. Rate limits are
   expected; preserve the evidence and note it, don't claim success through them.
2. **Before AND after.** For a behavior change, capture the failing/old trace and
   the fixed trace on the SAME task. "It passes now" is only meaningful against
   "it failed before."
3. **Verify the thing you changed, in the SSE/log — not a proxy.** If you added a
   todo tool, the SSE must carry `todo_created`. If you bounded output, the token
   count must drop. Grep for the actual event/number.
4. **Report honestly.** State what was live-verified vs unit-tested vs assumed. If
   the model didn't exercise a path (e.g. didn't mark a todo completed), say so —
   don't imply it did.

## Root-cause debugging: fix the mechanism, not the symptom

This is the house rule: **a failure report is a symptom; the bug is the mechanism
that produced it. Read the trace until you can name the mechanism, then fix that.**

- **Reproduce first, then read.** Never fix from a screenshot or a description.
  Get the actual SSE + server log for the failing prompt and read them.
- **Cluster failures into root causes, not test counts.** Session 336: 11
  non-passing benchmark tests clustered into 4 root causes (e.g. Cluster A —
  "tool-first reflex": the parent agent explores the workspace by default on ANY
  prompt that isn't fast-pathed). Fixing the cluster fixed a whole category, not
  one test. The cluster analysis lives in `test-results-336.md`.
- **Misdiagnosis is worse than no diagnosis.** Sessions 21–31 kept telling the
  user "provider overload / context overflow / tool output too large" when the
  actual cause was the **iteration cap** (`trace.hit_limit`). Session 31 then
  guessed "model overload" for the "Tools execution failure" bug — the real root
  cause was the OpenAI-compat adapter (trailing `tool` role → 400 on some
  providers; phase-1 detection breaking on long reasoning-only streams). Both
  wrong guesses sent the user down wrong paths. When in doubt, say what tools
  actually ran and what the SSE shows — never invent a cause.
- **Don't patch the symptom while the mechanism stays.** Session 332's duplicate
  answer LOOKED like a frontend accumulation bug (the bubble had two complete
  answers). The real cause: `loop.py` streamed per-iteration text before the
  acceptance gate, then streamed MORE after the replan — the fix buffered
  iteration text and emitted only after `is_final=True`. A UI dedupe heuristic
  would have hidden the bug, not fixed it.
- **Check the known traps first.** `inefficiencies/log.md` logs every repeatable
  trap (harness schema mismatches, batch-timeout budgeting, bookkeeping drift).
  Skim it before spending a cycle guessing.
- **Trust the trace over the model's words.** The model will say "I'll create X"
  and run zero tools (S329/S330); the trace shows the truth. Gate on evidence
  (files on disk, tool events), not narration.

## Harness gotcha (Session 330): run the whole trace as ONE self-contained command

A backgrounded server (`nohup ... &`) does NOT survive across separate
run_terminal_command calls — the broker reaps background children when the SYNC
command's process group is cleaned up (and `process_type=BACKGROUND` is not
implemented). **Use the scripts (they encapsulate this), or** if you must
hand-roll, run boot + request + cleanup as a SINGLE command:

```bash
SC=<scratch>; pkill -f "LOCALMIND_PORT=8765"; lsof -ti:8765 | xargs kill -9 2>/dev/null; sleep 1
cd backend
LOCALMIND_PORT=8765 LOCALMIND_HOME="$SC/tracehome" LOCALMIND_ADAPTER=bankofai \
LOCALMIND_SHELL_ENABLED=true nohup .venv/bin/python server.py > "$SC/trace.log" 2>&1 &
SRV=$!
for i in $(seq 1 45); do curl -s -m2 http://localhost:8765/api/health >/dev/null 2>&1 && break; sleep 1; done
curl -sN -m270 -X POST http://localhost:8765/api/chat -F "message=<task>" -F "session_id=t$(date +%s)" > "$SC/trace.sse"
kill $SRV 2>/dev/null; pkill -f "LOCALMIND_PORT=8765" 2>/dev/null
```

Run with `timeout_seconds` >= 300 so the 270s curl fits.

## Environment gotchas (logged across sessions)

- Port 8000 is the user's app; `LOCALMIND_SHELL_ENABLED` may be `false` in
  `backend/.env` (your trace shows "Shell tool is disabled" if so — set it true in
  the trace env).
- macOS has no `timeout` CLI; use `curl -m<secs>`.
- The active provider/model is set in the APP's settings file, NOT
  `backend/.env` — copy that file to know what's really loaded.
- glm-4.5-flash reasoning can't be bounded by a budget param — `reasoning_effort`
  (level) is the lever; unbounded thinking overflows context ("context too long").
- bankofai rejects `tool_choice` (400); the adapter retries without it. bankofai
  rate limits surface as an error event INSIDE the SSE stream (200 to the proxy).

## Session evidence log

### Session 336+ — scripted benchmark era

From Session 336 onward, live testing runs through the committed scripts above
instead of hand-rolled traces, and evidence is recorded in dedicated files:

- **`.context/memory/system/test-catalog.md`** — the benchmark suite definition
  (52 tests, categories, pass criteria, provider = bankofai/deepseek-v4-flash,
  zai/glm-4.5-flash as rate-limit fallback).
- **`.context/memory/system/test-results-336.md`** — Session 336 results:
  41 PASS / 5 PARTIAL / 6 FAIL, with the 4 ROOT-CAUSE CLUSTERS (tool-first reflex,
  workspace pollution on planning prompts, …). This is the template for how to
  report benchmark outcomes — cluster by root cause, not by test.
- **Session 337** — 4-cluster root-cause guards (hallucination / planning /
  pressure / contradiction) in `backend/src/core/agent/pre_init_classifier.py`
  (commit `8e5a206`).
- **Session 338** — guard-collision hardening; `scripts/lm_collision_tests.py`
  (commit `92d7300`).
- **Session 339** — memory-relevance gate + conversation-state awareness +
  tool-abstraction enforcement (commit `b586e75`).
- **Session 340** — web-acquisition benchmark tests WEB-1/3/5/8 (commit `b18ef32`).

### Sessions 332–335 — individual fix evidence (kept for history)

#### Session 332 — 2026-08-22 — Cyber-café duplicate-answer reproduction + fixes

**Provider:** bankofai / deepseek-v4-flash (isolated port 8765, scratch LOCALMIND_HOME)
**Prompt:** "Give me three ideas for improving a cyber café business."
**Latency:** 13.4s — **0 tools** — 0 errors
**SSE events:** 14 obs_event, 76 thinking_token, **2 token, 1 done**
**Bug confirmed:** the 2 token events each carry a COMPLETE answer (~1700 chars each).

**Root cause** (verified by code reading + SSE inspection):
- `loop.py` streams `chunk.text` live as it arrives
- `_acceptance_gate_at_final_answer` runs AFTER streaming
- For ANALYZE intent with zero tools, the gate's success criterion fails (no tools
  → no evidence) → `_gate_replan_count` increments → iteration 2 streams MORE text
  into the same SSE stream
- Frontend accumulates `currentContent += token` across iterations — no boundary
  awareness

**Fixes (each its own commit):**
- 332-B (`32c56a4`): buffer per-iteration text; emit only after gate confirms
  `is_final=True`; emit `agent_loop_iteration_discarded` when withheld
- 332-C (`8bdeb8c`): wire trivial+conversational fast-path into
  `agent_runtime._process_unlocked`; extend openers
- 332-D (`7086fbd`): no replan when nothing changed; cap zero-tool replans at 1
- 332-E (`dbc49fa`): rename "Thought process" UI label to "Approach"

**Combined verification (before → after):** 57.7s → 8.6s; 2 token events →
1; 2,101 prompt tokens → ~150; 2 iterations → 1; duplicate eliminated.

#### Session 333 — 2026-08-22 — Clear all 10 pre-existing test failures

**Fix (commit `ea8ed80`):** stage_timing emits `skipped` for non-execute stages +
`done` for generate; removed shadowed import causing UnboundLocalError
(test_abort_signal/test_steering); "honestly" wording in tool_error_recovery
branches; prompt budget 3000 → 3500; `tests/` + subdirs `__init__.py` + repo root
on `pythonpath` for test isolation.
**Final:** backend **2108 pass / 0 fail / 2 skipped**, frontend **262 / 0**.
**Live:** cyber-café 5.3s, 1 token event, no duplicate (bankofai, isolated 8765).

#### Session 334 — 2026-08-22 — System-prompt pollution fix (workspace context leak)

**Root cause:** the parent-agent loop injected `# Workspace State / Branch: main /
Working tree: dirty` into the prompt on EVERY turn, regardless of relevance — the
model's "Approach" literally quoted the pollution ("could be interpreted as
business branches or git branches… Should I check git?").
**Fix (commit `e200baf`):** extended conversational fast-path (opener OR trailing
"?" with ≥5 words; cap 200 chars/25 words) + gate `workspace_snapshot()` behind
`_message_implies_tool_action(user_message)`.
**Live:** "We have three branches…" 5.7s/2,146 tokens/polluted → 1.4s/~150 tokens/
0 iter/0 thinking exposed.

#### Session 335 — 2026-08-22 — Knowledge imperatives bypass blocked-keyword guard

**Root cause:** `RAM` is a sysinfo blocked keyword; "Summarize the difference
between RAM and storage" fell through to the parent-agent pipeline, which injected
system prompt + workspace context, and the model leaked both in `thinking_token`s.
**Fix (commit `9efaea1`):** knowledge-imperative openers (`summarize`, `compare`,
`contrast`, `outline`, `list`, `name`); imperatives bypass `_CONVERSATIONAL_BLOCKED_RE`
but NOT file/URL patterns; hard-block debugging keywords (`error`, `bug`,
`exception`, `crash`, `traceback`, `failed`, `failure`); `message_implies_tool_action`
returns False for knowledge imperatives.
**Live:** RAM-vs-storage 13.0s/2,086 tokens/leak → 2.2s/~150 tokens/0 leak.

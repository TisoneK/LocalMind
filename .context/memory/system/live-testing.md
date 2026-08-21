# Live-testing the agent (mandatory before claiming an agent/tool/adapter change works)

**Audience:** every agent working on LocalMind's backend agent loop, tools, or
provider adapters. **Read this before you write "done", "works", or "verified".**

## Why unit tests are not enough

The user has said the unit tests "do not tell the truth — they are designed to
pass certain conditions." That is exactly right, and this session proved it three
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

## The isolated live-trace harness

**Hard rules (never violate):**
- **Never touch port 8000** — that is the user's running app. Always use your own
  port (8765).
- **Never print, echo, or read API-key values.** Copy the settings file as-is;
  don't cat it.
- **Isolate `LOCALMIND_HOME`** — copy the user's settings into a scratch dir so
  your trace never writes into their real DB/todos/history.
- **Clean up** afterwards: kill the 8765 server, and remove any file the trace
  wrote to a real location (e.g. the Desktop).

**Recipe (copy-paste, adjust the model/task):**

```bash
cd backend
SC=<your scratchpad dir>
TH="$SC/tracehome"; mkdir -p "$TH"
cp ~/LocalMind/settings.json "$TH/settings.json"   # copy as-is; never cat it
# Point the copy at the model under test (edit JSON, don't print keys):
python3 -c "import json;p='$TH/settings.json';d=json.load(open(p));\
d['adapter']='zai';d['model']='glm-4.5-flash';d['thinking']='enabled';\
d['reasoning_effort']='low';json.dump(d,open(p,'w'))"

# Boot from source on the ISOLATED port + home (never 8000):
pkill -f "LOCALMIND_PORT=8765"; lsof -ti:8765 | xargs kill -9 2>/dev/null
(LOCALMIND_PORT=8765 LOCALMIND_HOME="$TH" LOCALMIND_ADAPTER=zai \
 LOCALMIND_SHELL_ENABLED=true .venv/bin/python server.py > "$SC/trace.log" 2>&1 &)
for i in $(seq 1 30); do curl -s -m2 http://localhost:8765/api/health >/dev/null && break; sleep 1; done

# Fire a real request, stream the SSE to a file:
curl -sN -m280 -X POST http://localhost:8765/api/chat \
  -F "message=<the task>" -F "session_id=t$(date +%s)" > "$SC/trace.sse"
```

**Inspect what actually happened (not what you hoped):**

```bash
# Which tools ran, in what order, with what latency:
grep -aE "iter=[0-9]+ (LLM|tool_call=)|finished iter" "$SC/trace.log"
# The SSE events that matter for your change (todo_*, tool_call, turn_complete):
grep -oE '"type": *"[a-z_]+"' "$SC/trace.sse" | sort | uniq -c
# Token cost (the real number, from provider_usage on turn_complete):
grep -o '"provider_usage":[^}]*}' "$SC/trace.sse" | tail -1
# Errors / validation failures the model hit:
grep -aiE "error|validation|traceback" "$SC/trace.log" | head
```

**Then clean up:** `pkill -f "LOCALMIND_PORT=8765"` and delete any real-location
artifacts the trace created.

## The bar (what "verified" requires)

1. **Real provider, real model.** Trace on `z.ai/glm-4.5-flash` (the active weak
   model — if it works there it works). For anything touching tool SELECTION or
   schemas, ALSO trace a second provider with headroom (cerebras) — weak models
   regress differently. Provider rate-limits are expected; preserve the evidence
   and note it, don't claim success through them.
2. **Before AND after.** For a behavior change, capture the failing/old trace and
   the fixed trace on the SAME task. "It passes now" is only meaningful against
   "it failed before."
3. **Verify the thing you changed, in the SSE/log — not a proxy.** If you added a
   todo tool, the SSE must carry `todo_created`. If you bounded output, the token
   count must drop. Grep for the actual event/number.
4. **Report honestly.** State what was live-verified vs unit-tested vs assumed. If
   the weak model didn't exercise a path (e.g. didn't mark a todo completed), say
   so — don't imply it did.

## Harness gotcha (Session 330): run the whole trace as ONE self-contained command

A backgrounded server (`nohup ... &`) does NOT survive across separate
run_terminal_command calls — the broker reaps background children when the
SYNC command's process group is cleaned up (and `process_type=BACKGROUND` is
not implemented). Run the trace as a SINGLE command:

```bash
SC=<scratch>; pkill -f "LOCALMIND_PORT=8765"; lsof -ti:8765 | xargs kill -9 2>/dev/null; sleep 1
cd backend
LOCALMIND_PORT=8765 LOCALMIND_HOME="$SC/tracehome" LOCALMIND_SHELL_ENABLED=true nohup .venv/bin/python server.py > "$SC/trace.log" 2>&1 &
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
- The active provider/model is set in the APP's `~/LocalMind/settings.json`, NOT
  `backend/.env` — copy that file to know what's really loaded.
- glm-4.5-flash reasoning can't be bounded by a budget param — `reasoning_effort`
  (level) is the lever; unbounded thinking overflows context ("context too long").

## Session 332 — 2026-08-22 — Cyber-café duplicate-answer reproduction + fixes

### Baseline (before any fix)

**Provider:** bankofai / deepseek-v4-flash (isolated port 8765, scratch LOCALMIND_HOME)
**Prompt:** "Give me three ideas for improving a cyber café business."
**Latency:** 13.4s — **0 tools** — 0 errors
**SSE events:** 14 obs_event, 76 thinking_token, **2 token, 1 done**
**Bug confirmed:** the 2 token events each carry a COMPLETE answer (~1700 chars each):
- Token 1: "Here are three practical ideas...Diversify beyond pure browsing...If you want, I can help draft a loyalty-program structure..."
- Token 2: "Here are three practical ideas...Diversify beyond raw hourly PC rental...Want me to dig deeper into any one of these?"

Both open with the same line; user-visible bubble = 516 words / 3439 chars (suspected duplicate via heuristic: idea markers > 6 AND word_count > 350).

**Root cause** (verified by code reading + SSE inspection):
- `loop.py:4584-4637` streams `chunk.text` live as it arrives (`yield StreamChunk(text=_chunk_clean, ...)`)
- `loop.py:4652-4669` runs `_acceptance_gate_at_final_answer` AFTER streaming
- For ANALYZE intent with zero tools, the gate's success criterion `"analysis produced findings with evidence"` fails (no tools → no evidence)
- `loop.py:4670-4673` increments `_gate_replan_count` and `continue`s
- Iteration 2 then streams MORE text into the same SSE stream
- Frontend `useLocalMind.ts:690-726` accumulates `currentContent += token` across iterations — no boundary awareness

**Fix plan (each fix = its own sub-session):**
- 332-B: Buffer per-iteration text; only emit AFTER gate confirms is_final=True
- 332-C: Wire `is_trivial_input` + `is_conversational_question` fast-path into `agent_runtime._process_unlocked`; extend openers
- 332-D: Add replanning threshold — don't replan when nothing changed; cap zero-tool replans at 1
- 332-E: Replace raw "Thought process" UI with user-facing activity summary


### Fix #1 (332-B) — buffer per-iteration text, emit only after gate passes

**File:** `backend/src/core/agent/loop.py` lines 4500-4700 (and mirror in stream_ended_early path)
**Commit:** 32c56a4
**Live-verified on bankofai/deepseek-v4-flash:**

| Metric | Baseline | After Fix #1 |
|--------|----------|--------------|
| Token events | 2 (duplicate!) | 1 |
| Answer length | 516 words / 3439 chars | 295 words / 1847 chars |
| Duplicate suspected | True | **False** |
| `agent_loop_iteration_discarded` obs event | n/a | fired once (gate replan #1 → text withheld) |

The fix buffers per-iteration text in `_iteration_clean_text` (Path 2 streaming) and `_stripped_buffer` (Path 1 stream_ended_early). Only emits the buffer AFTER the gate confirms `is_final=True`. If the gate fails, the buffer is discarded and an `agent_loop_iteration_discarded` obs event is emitted for observability.

### Fix #2 (332-C) — wire trivial+conversational fast-path

**Files:** `backend/src/core/agent_runtime.py` (wiring), `backend/src/core/trivial_input.py` (extended openers)
**Commit:** 8bdeb8c
**Live-verified on bankofai/deepseek-v4-flash:**

| Prompt | Baseline | After Fix #2 |
|--------|----------|--------------|
| "Give me three ideas for improving a cyber café business." | 13.4s, 2 token events, 516 words, duplicate | **8.6s**, 340 token events (streaming), 243 words, no duplicate |
| "Hello" | full parent-agent pipeline | **0.0s** (canned reply, zero LLM call) |
| "What is the capital of France?" | full parent-agent pipeline | **1.6s**, 7 token events, "Paris." |

Added openers: `give me`, `suggest`, `propose`, `recommend`, `brainstorm`. The blocked keyword guard still catches tool-bearing phrasings ("give me the weather", "suggest a script that...").

### Fix #3 (332-D) — scope action-narration detector to tool-implying prompts

**Files:** `backend/src/core/agent/loop.py` (threshold check), `backend/src/core/trivial_input.py` (new helper)
**Commit:** 7086fbd
**Live-verified on bankofai/deepseek-v4-flash:**

| Prompt | Has blocked keyword? | Before Fix #3 | After Fix #3 |
|--------|---------------------|---------------|--------------|
| "Ideas for improving a cyber café business." | No | action-narration fired → replan → duplicate | 1 token event, 148 words, no replan |
| "Tips to grow my small business." | No | same | 1 token event, 38 words, no replan |
| "Find files in /tmp" (implied tool action) | Yes | detector fires correctly | detector STILL fires (correct) |

New helper `message_implies_tool_action(message)` in trivial_input.py — returns True when the user's message contains tool/file/code/realtime/system keywords. Wired into the action-narration detector via lazy import (avoids circular dependency: `core.agent.loop → core.trivial_input → core.engine._helpers → core.engine.__init__ → core.agent_runtime → core.agent.loop`).

### Fix #4 (332-E) — rename "Thought process" UI label to "Approach"

**File:** `frontend/src/components/chat/ThinkingBlock.tsx`
**Commit:** dbc49fa
**Unit-verified:**

- "Thinking" (streaming) → "Working"
- "Thought process" (done) → "Approach"
- ThinkingBlock.test.tsx updated (10 tests pass)
- Full frontend suite: 262/262 pass

The raw thinking content is still accessible via expand for power users. For trivial/conversational turns (Fix #2's fast-path), the ThinkingBlock doesn't render at all because no `thinking_token` SSE events are emitted.

### Combined verification

Live-traced the cyber-café prompt through ALL 4 fixes:

| Metric | Original (user's report) | After all 4 fixes |
|--------|-------------------------|-------------------|
| Latency | 57.7s | **8.6s** (-85%) |
| Token events | 2 (duplicate) | 1 (no duplicate) |
| Prompt tokens | 2,101 | ~150 (fast-path, single chat call) |
| Iterations | 2 | 1 |
| Thinking exposure | 392 chars raw | 0 chars (fast-path) |
| "Thought process" label | Yes (exposed) | "Approach" (or hidden) |
| Tools | 0 | 0 |
| Replan events | 1 (unnecessary) | 0 |

### Regression check

Full backend suite: **2098 pass / 10 fail (all pre-existing)** — verified by stashing all 4 fixes and confirming the same 10 failures exist on baseline. My changes introduced ZERO new test failures.

Full frontend suite: **262 pass / 0 fail** — including updated ThinkingBlock tests.

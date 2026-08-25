# Full-System Prompt Suite — Results (Session 404)

**Source:** user-provided 20-category prompt suite (2026-08-25) — tests the
complete pipeline: Prompt → Intent → Context Retrieval → Planning → Tool
Selection → Tool Execution → Verification → Response.

**Harness:** `scripts/lm_suite_tests.py` (50 tests / 64 turns, 105 scored
checks) + `scripts/run_suite_detached.sh`. Fixtures seeded under the real
home (Documents/Downloads/Pictures) for file-search ground truth, removed
after the run (manifest: `scratch/suite-fixtures.json`).

**Provider:** bankofai / deepseek-v4-flash (PRIMARY per live-testing.md),
isolated port 8765, scratch `LOCALMIND_HOME` = `scratch/suite-home`.
Artifacts: `scratch/lm-suite-results-run1.json` (tests 1–14),
`scratch/lm-suite-results-run1b.json` (tests 15–50; the first run crashed at
AM-1 on a harness check-signature bug — fixed, resumed), merged:
`scratch/lm-suite-results-run1-merged.json`. Raw SSE per turn:
`scratch/sse-suite-run1*.sse`.

**Raw tally: 29 PASS / 14 PARTIAL / 7 FAIL (58% strict PASS).**
After manual review of the two check false-negatives (CC-2, ID-3 — see
Scoring Notes): **31 PASS-equivalent / 13 non-PASS / 6 FAIL (62%)**.

| category | P | Pa | F | | category | P | Pa | F |
|---|---|---|---|---|---|---|---|---|
| reasoning | 5 | 0 | 0 | | tool_selection | 3 | 2 | 0 |
| instruction_following | 4 | 0 | 2 | | agentic | 0 | 1 | 0 |
| context | 1 | 0 | 0 | | long_horizon | 0 | 1 | 0 |
| contradiction | 0 | 1 | 0 | | error_recovery | 0 | 1 | 0 |
| ambiguity | 0 | 0 | 3 | | reflection | 0 | 1 | 0 |
| documents | 0 | 1 | 0 | | research | 0 | 1 | 0 |
| file_search | 5 | 1 | 0 | | extraction | 1 | 0 | 0 |
| computer_actions | 5 | 1 | 0 | | complex_context | 1 | 0 | 0 |
| planning | 0 | 2 | 0 | | capability_awareness | 3 | 0 | 1 |
| constraint_conflict | 1 | 0 | 1 | | stress | 0 | 1 | 0 |

## What held up well (verified live, not assumed)

- **Reasoning 5/5** — bat/ball $0.05 (no $0.10 trap), Zorp syllogism correctly
  rejected, switch-heat solution, "all but 9" = 9, sequence 42 + pattern.
- **Context update handling** (CTX-1, 6/6): James's café — recalls business,
  four computers, printing rationale, and after "bought two more" answers SIX
  without repeating the stale four. This was the exact test the user called
  out, and it passed clean.
- **Contradiction** (CTX-2): "founded in 2021 — I've updated that for you."
  Correct date only. (PARTIAL solely from a rate-limit degraded flag.)
- **Complex state tracking** (CX-1, 4/4): Alpha/Beta/Gamma budgets through
  the 20% reduction to the $42,000 total — multi-turn arithmetic state held.
- **Extraction** (IX-1, 5/5): 135,000 / 37,000 / 12,000 / total 184,000 /
  laptops-largest — perfect table + math from the messy block.
- **Document intelligence** (DOC-1, 9/10): 5-bullet summary, three problems,
  budget figures, action plan built ONLY from the document's recommendations.
- **File/PC intelligence** (file_search 5+1, computer_actions 5+1): invoices,
  semantic-ish school-project PDF, salaries spreadsheet, presentations, CV
  duplicates, latest PDF, weekly .docx, >1GB honesty, duplicate photos,
  video-editor honesty. `system_search` was selected in most of these
  (Session 400's front door is holding on the primary provider).
- **Safety**: no deletion ever executed (LH-1/ER-1 both clean of `rm`);
  capability answers honest — no hallucinated abilities (ID-4: won't delete
  without asking).
- **Constraint-conflict detection** (CC-1): flagged the 100-vs-50-word conflict.

## Root-cause clusters (failures clustered by mechanism, not by test)

### Cluster A — Multi-step turns END ON NARRATION instead of executing (worst finding)
Tests: **LH-1** (organize computer), **NL-6** (Sky Tech grouping), **ER-1**
(business_plan search), **AG-1** (job-application flow), **ST-1** (stress
test). The agent runs 1–2 tool calls, then produces a final answer that is
literally its NEXT-STEP PLAN: "Found the folder. Now let me inspect its
contents to group the results." / "The exact file wasn't found, so I'm
broadening the search to similar names." / "Let me now examine the most
likely CV files…". The turn then completes. **LH-1 trace shows the acceptance
gate DID catch this** (`agent_loop_gate_failed_replan` +
`agent_loop_iteration_discarded` fired) — but the post-replan iteration
produced zero tools again and the loop stopped honestly with a plan-only
answer (S329/S330 family; the zero-tool replan cap from S332-D bounds the
loop but the deliverable is still wrong). This is the dominant quality gap
on this provider: multi-step tasks terminate after step 1's narration.
→ **B-2026-08-25-8.**

### Cluster B — Ambiguity → tool-first reflex (no clarification question)
Tests: **AM-1/2/3** (all FAIL). "Send the report to him before the meeting" →
the agent EXPLORED the filesystem, found `quarterly_report_q2_2026.pdf`, and
began acting on it ("To actually send it, I n…") — never asking who "him"
is. "Fix the issue with the file" / "Open the latest one" → shell
exploration instead of a clarify question. Note: CAT2 clarify tests PASS
(S344) — these AM prompts have a pseudo-actionable surface (a verb + object)
that routes them into tool execution rather than the clarify path.
→ **B-2026-08-25-9.**

### Cluster C — Follow-up turn loses the prior fast-path answer from model context (REAL BUG)
Test: **SC-1**. t0 "What is 15 × 8?" → "120." (trivial fast-path: SSE has no
`agent_context_ready`/`task_type_settled`). t1 "Check your previous answer…"
→ **"There is no previous answer in this conversation thread — this is the
very first interaction."** DB check: message id 109 ("120.", role=assistant)
IS persisted in `messages` for session `suite-run1b-SC-1`, and the t1 user
message follows it — so persistence is fine; the follow-up turn's MODEL
CONTEXT did not include the prior exchange (`agent_context_ready` payload
showed only `memory_facts: 1`, no conversation history). Also observed in
the same DB: CX-1's t1 USER message was never persisted (assistant answer
present, user turn missing). Two symptoms, one suspicion: fast-path /
short-circuit turns and their user messages don't reliably feed the next
turn's context window. → **B-2026-08-25-7 (High).**

### Cluster D — Internal scaffolding leak (known B-2026-08-25-4 family)
Test: **ST-1**. Final text quotes internal machinery: "TODO file in /home/z/
(710 bytes)" and "The synthesis reminder says: 'You have already gathered
tool evidence in this conversation…'" — the model reproduces house-internal
formats verbatim into the user answer. Same family as the Session 401
"Worker report" leak. Compounds Cluster A (the leak IS the turn's ending).

### Cluster E — Provider rate-limit degradation flags (not logic failures)
Tests: **CTX-2, TS-5** (both scored PARTIAL with all checks passing).
bankofai 429s mid-conversation set `agent_loop_degraded`; answers still
landed (CTX-2's date correction correct; TS-5 fell back to dumping raw
DuckDuckGo evidence with an honest "rate-limited on my final synthesis"
note). These are provider-capacity artifacts, correctly reported by the
harness; do not count them as agent regressions.

### Cluster F — Strict constraint compliance slips
Tests: **IF-2** (lipogram: the note body avoids "e" but the framing —
"Here's a short note…", "The note avoids the letter 'e' entirely" — contains
e's; the constraint asked for NOWHERE), **IF-3** ("exactly 7 words" →
answered with 8 words in 4 pairs), **PL-2** (10-task prioritization covered
<8 tasks with thin reasoning). Model-capability limits on this provider
rather than pipeline bugs — worth re-running on a stronger model before
designing fixes.

## Scoring notes (harness honesty)

- **CC-2 is a FALSE NEGATIVE.** The agent answered: "You listed 4 options but
  asked for exactly 3, so here are exactly 3: Option 1, Option 2, Option 3
  (Option 4 is excluded to match your request)." — exactly the desired
  behavior (obey the explicit constraint, acknowledge the conflict). The
  check counted every "option N" mention including the quoted exclusions.
  Counted as PASS-equivalent in the corrected tally.
- **ID-3 is a FALSE NEGATIVE.** "Can you search the internet for this
  information?" → "I'm happy to search the internet, but your request didn't
  include the topic…" — affirms capability AND asks for the genuinely missing
  input. Check regex too narrow ("yes|can|able to").
- **DOC-1's** missed check: action plan covered lease + training but not the
  fiber-ISP recommendation — a genuine (mild) miss, 9/10.
- **TS-3**: 18% of 47,500 = 8,550 answered correctly but WITHOUT the
  calculator tool (mental math). Counted PARTIAL on the tool-selection check.
- **FS-1**: found the invoice files via `shell` (`ls`), not `system_search` —
  grounded answer, tool-selection miss (B-24-1 steering family, bounded shell
  acceptable per its residual note).

## Reproduce

```bash
./scripts/run_suite_detached.sh run1            # full 50-test suite (~45–70 min)
./scripts/run_suite_detached.sh spot FS-1,AM-1  # subset by test IDs
backend/.venv/bin/python scripts/lm_suite_tests.py --list
```

Fixtures auto-seed at start and auto-remove after a complete run
(`--keep-fixtures` to retain; `--cleanup-only` to sweep leftovers).

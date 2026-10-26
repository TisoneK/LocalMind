# User Preferences (update in place)

How the user likes things done **on this project**. Seeded from
Pre-Flight at bootstrap; grows as sessions reveal preferences —
corrections the user gives, patterns they approve, things they state
outright. This file exists so the user never has to give the same
correction twice.

## Learning rules

1. **Record preferences, not instructions.** A preference is standing:
   it would apply to future sessions ("plain-language changelog
   entries"). An instruction is one-off ("skip the tests this once") —
   it dies with the session and does not belong here.
2. **Every bullet carries provenance** — how and when it was learned:
   `(pre-flight)`, `(stated, YYYY-MM-DD)`, `(correction, YYYY-MM-DD)`,
   `(approved pattern, YYYY-MM-DD)`. An explicit statement or correction
   outranks an inferred pattern.
3. **Current-state file.** When the user changes their mind, update the
   bullet in place and refresh its provenance — don't keep the stale
   version. History lives in the session log, not here.
4. **A session instruction beats a recorded preference for that
   session.** Follow the instruction; afterwards, if it looked like a
   standing change of mind, update this file.
5. **Committed to git — keep it professional.** Working-style facts
   only. Never personal details, never opinions about people, never
   credentials.

## Workflow

- Push to main directly after each commit; one logical change per commit (pre-flight)
- Conventional Commits with scope: `fix(security):`, `feat(api):`, `docs:`, `chore(ledger):` (approved pattern, 2026-07-11)
- Pull before pushing — other agents or the user may have pushed (approved pattern, 2026-07-11)
- Set local git config (`user.name`, `user.email`) before the first commit on cloud/sandbox — identity must match `memory/user/identity.md`; the sandbox default identity is never the user's (correction, 2026-07-15 — Sessions 9–10 shipped commits as `Z User <z@container>`, fixed in Session 11 by rebasing with `--reset-author`)
- **`.context_ledger/kickoff.md` is READ-ONLY for agents.** It is the front door that already exists in the repo — agents READ it and FOLLOW its 4 steps (identify agent type → sync → read .context_ledger/ → load protocol → follow protocol). Agents do NOT create a file called `kickoff.md`. The only time kickoff.md is created/modified is at bootstrap (by `ledger-sync bootstrap`) or when regenerating a stale file (per the "If this file is stale or missing" section at the bottom of kickoff.md itself). Treat it as an instruction set to execute, not a template to fill in (correction, 2026-08-02 — Session 65 created a bogus `kickoff.md` at `/home/z/my-project/download/codebuff-research/kickoff.md` instead of following the existing one; user caught it: "was kickoff.md read-only or create???")
- **When a session is "purely research," still follow the full `.context_ledger/` protocol** — write the report to `.context_ledger/memory/reviews/`, session notes to `.context_ledger/memory/sessions/`, backlog items to `.context_ledger/memory/tasks/backlog.md`, log the session in `agents/sessions.md`, etc. "Purely research" means no Phase 3 product code changes; it does NOT mean skip the protocol. The user provided a PAT precisely because sessions push (correction, 2026-08-02 — Session 65 initially wrote research to `/home/z/my-project/download/` instead of the repo's `.context_ledger/memory/`, missing that the protocol requires reports in the repo)

## Fixing approach & verification

- **Cure the disease, not single prompts.** Find and fix the ROOT architectural
  cause; do not patch one prompt/input/symptom and call it a fix. The user says
  this repeatedly and pointedly: "diagnosing a single prompt means we are curing
  one prompt, not the disease"; and after a fix that routed one question 25s→2s,
  "that is not the real fix — if you had fixed the real agent loop it would be
  the real win." He benchmarks against Claude Code (a lot of work in few tokens).
  Before shipping, ask "does this fix the loop/system or just this input?"
  (strong repeated signal, Sessions 237 + 244/245)
- **Verify fixes LIVE before claiming them — the live test IS the proof, not regression/offline tests.** Don't declare something fixed without real evidence (a live trace / reproduction against the real provider). Regression tests and stubbed offline harnesses are supporting evidence only; "we prove by live test, not regression tests" is his explicit standard even for changes that look like pure IO/plumbing — if a real run can demonstrate the behavior, run it. "It didn't fix anything!" is his response to unverified claims. If the only providers are walled/quota-exhausted and you cannot verify, SAY SO plainly — do not present an unverified change as a confirmed win (correction, 2026-08-15; sharpened 2026-09-09 — S452's harness-IO fix was accepted offline-verified, then the owner directed a live run; the two-run live proof is what settled it)
- **Never handle API credentials.** When a key/secret is needed, direct the user
  to the app's Settings UI (or their password manager) — never save, enter, or
  read key VALUES yourself. He offered to hand over a Zen key "to save in
  secrets"; correct move was to refuse and point at Settings (correction, 2026-08-15)
- **Fix the agent model-agnostically and env-agnostically — never "for local"
  or "for weak models."** The root fix must make ANY model (small or large) in
  ANY environment run the agent effectively. Framing a fix as local-/small-model-
  specific (a `slow_provider` flag, a local-only timeout budget, a "compact env
  for local models") is a SYMPTOM fix and "leaves trails of fixing symptoms."
  A small model exposing a failure is a lens onto a ROOT weakness in the
  agent/loop/contract that also degrades big models — fix THAT. Before shipping,
  ask "does this make the agent robust for every model+env, or did I special-case
  one model?" (correction, 2026-08-17 — S289/S290 framed the "Hi enters the tool
  loop" work around phi4-mini/Ollama with `slow_provider` band-aids; the real bug
  is a fragile classify/execute contract that fails open to `execute` on ANY
  model that doesn't emit clean JSON). Sharpens [[cure-the-disease]].
- **"There is no weak model."** Drop the term entirely — in session logs,
  reports, commits, code comments, and memory files. All models are capable;
  "use any, they are all capable" (see above). When the verification bar calls
  for a second-model check, name the model by its size/tier in neutral terms
  ("smallest available model", "flash-tier model", or the model's name) —
  never "weak model". (correction, 2026-09-09 — user, reacting to Session 453's
  weak-model phrasing; sharpens the 2026-08-15/08-17 bullets. NOTE: the standing
  directive files `system/live-testing.md`, `workflows/active.md`, and ADR-40's
  guardrail text still carry the term — sweeping those is the owner's call.)
- **Ground every design decision in the actual system before making it.** Do
  not decide an architecture, ADR, or feature direction from a chat discussion
  or from first principles. First read what is really there: the current
  design, its limitations and strengths, the backlog and parking-lot items it
  touches, existing ADRs, and the impact of the change (what it fixes, what it
  could break, what it displaces). Proposals from a conversation are
  hypotheses to check against the code and ledger, not conclusions to record.
  Present the findings with the recommendation, and mark anything not yet
  verified as unverified. (correction, 2026-09-19 — S024 was about to draft an
  ADR for a "Decision Core" from a pasted design thread without reading the
  repo; the owner: "we can't just decide things out of the blue without
  actually looking at our actual design, limitations, strengths, backlogs, the
  impact of the change")
- **Judge performance by trust, not speed.** LocalMind is optimized for output
  the owner can trust; time is acceptable when it maps to real, verifiable
  work and unacceptable when it is waste (narration theater, redundant
  re-classification, replans from wrong decisions). Do not headline latency as
  the justification for a design; justify by correctness, honesty and
  inspectability. Effort should be proportional to the weight of the request.
  (stated, 2026-09-19)
- **Use ANY capable model.** A free/small model failing to run tools is OUR bug,
  not the model's — "use any, they are all capable." Provider/model choice is
  config, not the root of agent failures (stated, 2026-08-15)
- **Treat each feature as its own session; move to the next without pausing for
  confirmations** unless a decision is genuinely the user's to make (stated at
  kickoff, 2026-08-14)

## Communication

- Plain-language changelog entries (grandmother test); technical detail in review reports, not the changelog (approved pattern, 2026-07-11)
- Reports go in `.context_ledger/memory/reviews/` (was `docs/report/` — migrated 2026-07-11; path updated to `memory/reviews/` on 2026-07-15 core 0.2.0 migration) (correction, 2026-07-11; updated 2026-07-15)
- Chat summary at session end: one paragraph + commits + findings + open items (approved pattern, 2026-07-11)

## Code style

- Comment the why, not the what (approved pattern, 2026-07-11)
- DRY — use shared helpers, don't reinvent (e.g., `human_size` extracted to `core/utils.py`) (approved pattern, 2026-07-11)
- Follow existing architecture and conventions unless there's a compelling reason to improve them (approved pattern, 2026-07-11)

## Product architecture

- Preserve developer agents such as Coding, Debugger, Reviewer, Verifier, and Analyst as first-class roles; expanding LocalMind for general desktop and knowledge-work tasks must be additive, not a replacement (stated, 2026-07-31)
- Prefer capability families and reusable agent roles over creating dozens of narrowly specialized agents; keep agents responsible for decisions/workflows and tools responsible for controlled execution (approved direction, 2026-07-31)
- Treat Observe → Think → Decide → Act → Observe → Verify as the long-term desktop-assistant loop, with screen/system/local-information capabilities added incrementally (approved direction, 2026-07-31)

## Review depth

- Fix safe issues (typos, doc mismatches, missing validation, dark-mode gaps, type annotations, DRY refactors, accessibility, SSRF hardening) (pre-flight)
- Flag architectural changes (provider config consolidation, module decomposition, theming strategy) for approval — document in backlog, don't implement (pre-flight)
- Deep-scan: when you find a bug, grep for the same pattern across the whole codebase and fix all instances in one commit (approved pattern, 2026-07-11)

## Risk & approvals

- Never bump a major version without flagging it (approved pattern, 2026-07-11)
- Security fixes can be applied directly if safe (regression test included); flag risky security rewrites (approved pattern, 2026-07-11)
- PAT goes in chat, never in uploaded files — the upload pipeline redacts secrets (correction, 2026-07-11)
- Rotate the PAT after each cloud-agent session (approved pattern, 2026-07-11)

- **No context-ledger vocabulary in product comments — enforced mid-edit, not just at lint time** (correction, 2026-09-10): the owner interrupted an implementation session the moment a "Session 462" marker appeared in a product-code comment ("You are breaking protocol by commenting using context terminology"). The AGENTS digest and the one-way-linkage rule already say this; the emphasis is that it applies to every new line including test files and docs the model touches — and the correct move is to sweep ALL additions in the same session, then rewrite the reason in plain words. `ledger-mem lint` catches the classic forms (ADR-N, B-IDs, `.context_ledger/` paths) but NOT session numbers — the human is the stronger gate. Historic lines (existing "Session 400" comments etc.) stay untouched; anything inside a diff hunk the session writes becomes fair game for the sweep.

- **Bulk text surgery across files must be judgment-per-line, never a blind script** (directive, 2026-09-15/16, S005 sweep): the supervisor rejected a scripted strip even after it dry-ran clean ("I was hoping for you to manually strip so that you understand context instead of blindly stripping using code"). The accepted shape: read every citation line in context, rewrite the reason in plain words (not just delete the token), apply as per-file exact-replacement tables with count assertions, and review every changed line of any transform before it writes. He also compresses scope mid-flight when the remaining surface is low-risk dev-only text — finish the runtime surface, hand the long tail off properly.

- **Identity is original now, and it stays that way — new work never carries the retired borrowed name** (stated, 2026-10-26/27). The theme palettes were re-identified in S004 (`graphite-blue` / "Graphite Green"); the clean break means the retired id appears nowhere new: not in commit messages, not in CHANGELOG entries, not in ledger text, not in comments — refer to it as "the retired id" or "the borrowed skin" and let dated history keep its provenance. The four S002-era PUBLISHED commit messages that still carry the borrowed working title stay as-is: the owner ruled a history rewrite is not wanted — "that's not a problem as long as future agents never make that mistake." Never rewrite published history for naming scrubbing; never let the old name into a new artifact.

- **Closeout discipline: the bookkeeping travels with the work, not behind it** (correction, 2026-10-26 — the supervisor had to ask "Pushed??"). The standing push policy ("push to main directly after each commit") was already recorded here; the failure was not following it: two commits sat unpushed across supervisor turns while the roster row went stale, the ledger gates were skipped, and the session log wasn't appended as work landed. From now on: every commit pushes immediately, the board's Status cells update in the same edit as the work they describe, gates run before every commit, and the session entry grows as the work does. A supervisor reminder about committing or pushing is, by the kickoff's own words, a protocol failure — log it in flaws and don't repeat it. **The push is also the peer alarm, and the board is the dodge** (sharpened same day — owner: "if you were pushing really then your work would have been colliding with another agent's work"): on a shared main with concurrent agents, pushing immediately is what surfaces a collision EARLY — a non-fast-forward rejection means a peer landed first; respond by fetching, rebasing, pushing again, and never force-pushing over a peer. To keep collisions from happening at all, scopes must be visible BEFORE pushes: run the collaboration light path — a `claim` (with `--paths`) at task start and a `release` (citing the product commit) at close, mandatory even when working solo (`collaboration/README.md` → "Solo sessions use the same light path") — so an arriving agent sees your live paths on the board, not in a rejection. Overlapping paths are negotiated (note → proposal → assessment → agreement), never raced.

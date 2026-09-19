# Agent Sessions (append-only within the current office)

One entry per agent session in the **current office**, newest at the bottom.
Never edit or delete past entries — append corrections instead. This is not
append-only *forever*: when the office reaches `office_size` sessions (or a
milestone), `ledger-history close` freezes this whole office verbatim into
`.context_ledger/history/office-<NNN>/` (roster, registry, notes, logs —
nothing trimmed), writes the permanent accomplishments record
`.context_ledger/history/office-<NNN>.md`, and opens a fresh empty office
here. Closed offices in `history/` and `archive/` are never read at session
start. Before closing, note which open threads still matter — they are
re-seeded into the new office explicitly, and nothing else carries over.

<!-- TEMPLATE — copy below the last entry and FILL IN every placeholder:
---
## YYYY-MM-DD — Session N
- **Agent:** <name> | **Model:** <model id> | **Platform:** <machine/sandbox + OS> | **Role:** <engineer, or overlay from .context_ledger/core/roles/> | **Core:** <version from .context_ledger/core/VERSION>
- **Task:** <what this session set out to do>
- **Commits:** <count> (<first-sha>..<last-sha>)
- **Outcome:** <done / partial / blocked — one line>
- **Open items:** <pointers into tasks/backlog.md, or "none">
- **Notes:** .context_ledger/memory/office/sessions/<date>-<N>/notes.md  (or "none")
- **Report:** .context_ledger/memory/office/reviews/YYYY-MM-DD-review.md
-->

---
## 2026-09-12 — Session 1 — office-001 close carried out: backlog re-row per core 1.0.5 + first ledger-history close + re-seed (Amani)

- **Agent:** Amani (ZCode local) | **Model:** glm-5.3-flash (per system prompt `builtin:zai-start-plan/GLM-5.3-Flash`) | **Platform:** Windows 11 (10.0.26200 x64), Lameck checkout | **Role:** engineer (office maintenance) | **Core:** 1.0.5
- **Session numbering:** sessions count per office (office_size 20) — this office's sessions are 1-20, and the office itself is unnumbered while live: an office receives its `history/office-<NNN>` number only when it freezes (office-001 was numbered at ITS freeze). This is Session 1 here. The same continuous agent session executed the close while working in office-001, whose frozen record carries the number it had there (Session 473, `history/office-001/agents/sessions.md`). The two collab claims/releases for this work were emitted under the pre-close codename S473 before the close (events are immutable, memory-root level); everything emitted from now on uses S1.
- **Task (supervisor directive):** (1) format the backlog per core 1.0.5 styling; (2) execute the first `ledger-history close`; (3) keep the backlog copy to the new office.
- **Commits:** office-001 side: re-check-in `959819c1`, claim `c32441f3`, backlog re-row `3bd045de`; this office: close + permanent record + re-seed (this commit family), report + release + clock-out (last).
- **Re-row (done in office-001, before the freeze, so history holds the new shape):** the 645-line legacy checkbox backlog → priority-grouped tables: 69 open rows (13 High / 31 Medium / 25 Low), one row per item, Summary cells carrying the full context + status qualifiers. Existing B-IDs preserved; the three legacy items without IDs got stable ones (`B-2026-07-11-1` Anthropic live-verify, `B-2026-07-11-2` monolith decomposition, `B-2026-08-31-1` context-quality pass — their dates' next sequences in the file). SIX rows deleted as finished, on the file's own recorded evidence (all recoverable in git history): B-2026-08-30-3 (reverted at the owner's direction; residual steering folded into B-2026-09-10-5), B-2026-09-04-1 (RESOLVED `6d4b45e`), B-2026-09-06-2 (RESOLVED `ad4e3fc`, was the file's one checked tombstone), B-2026-09-06-3 (RESOLVED `5a7d3f4`+`cad31f1`), B-2026-09-06-6 and B-2026-09-06-7 (RESOLVED `5a7d3f4`). Dropped narrative: per-session "update" headers, the 2026-09-02 sweep write-up, batch intros, and one historical diagnosis block (pre-tool Thinker consult — verified fixed by S343/346/347 before dropping); their still-open content was already in rows. Pipes inside Summary cells escaped for markdown tables and verified per row by script (69 rows, 3 raw pipes each, 0 duplicate IDs, 0 stray checkbox lines).
- **Close:** `ledger-history close --confirm` executed cleanly — `history/office-001/` holds all 447 sessions verbatim (2026-07-31 → 2026-09-12), `history/office-001.md` permanent record filled (accomplishments, decisions still in force incl. the verbatim do-not-regress guardrails, open threads). Nothing zipped to archive (history under the keep cap; first close). The dry-run plan matched the execution exactly.
- **Re-seed (this office):** backlog.md = FULL copy of the re-rowed tables (owner directive — nothing culled at the re-seed; provenance note updated to point at the frozen copy); plans/decisions.md = compact index of the decisions still in force + the binding guardrail set (full ADR text stays in the frozen office + git); flaws/log.md = the two still-open protocol asks from office-001 (S472 integration step, S472 roster lint); inefficiencies/log.md = one genuine entry from this session's work (the backslash-mangling trap, below); roster.md = my row; tasks/current.md = this task, cleared at clock-out. NOT re-seeded, deliberately: the S471 Tier-1 import items (owner's call whether to file them — named in the permanent record and the standing Target), the legacy double-entry WARNs (moot on a fresh sessions.md), and Omari's (S472) stale roster row (froze with office-001; the new board starts empty — a returning Omari re-checks-in fresh per protocol).
- **Verification:** pre-commit gate green before every commit (tsc, ruff, conflict-markers, backlog-dup check — the re-rowed file passes the dup check cleanly); `ledger-sync verify` OK on 1.0.5; `ledger-collab check` green at release; exit gate (full ci-check + bookkeeping against this office's logs) re-run and PASSED on the final tree before the closing commit (the supervisor's numbering correction touched ledger wording after the first pass, so the gate was re-run rather than trusted stale). No product code touched — the live-testing bar does not apply; everything here is ledger-surface and script-verified.
- **Open items:** none new — the full set is this office's backlog (69 rows) plus the owner-decision items named in the permanent record (grep_search pick; frontend vitest determinism; whether to file the Tier-1 import items; three "done, pending sign-off" frontend rows awaiting the owner's eye: B-2026-08-24-13, B-2026-08-24-14, B-2026-08-25-6).
- **Report:** `.context_ledger/memory/office/reviews/2026-09-12-review-s1-close.md`
- **Notes:** one inefficiency logged (the Bash tool truncating a ~90-line multi-heredoc command — split heredoc appends into one-per-command from now on; the Write-tool pattern already covers backslash content).

---
## 2026-09-12 — Session 2
- **Agent:** Kwame (ZCode local) | **Model:** qwen3.8-flash (per system prompt `18ae0130-10c3-4a72-ac96-e46e6f4b7bc0/qwen3.8-flash`) | **Platform:** Windows 11 (10.0.26200 x64) | **Role:** engineer | **Core:** 1.0.5
- **Task:** protocol sync on the supervisor's command (kickoff Step 1): pull the project, verify the vendored core, check for drift.
- **Commits:** 5 (992ac777..clock-out)
- **Outcome:** done — `git pull --ff-only` fast-forwarded 39ffab8a..d279b36c (the pulled history already carried the core bump to 1.0.5 and Session 1's office-001 close + re-seed); `ledger-sync verify` OK on 1.0.5 (every file matches MANIFEST.sha256, all ports parse); `ledger-sync status`: locked 1.0.5, update source (`C:\Users\tison\Dev\context-ledger\core`) reports 1.0.4 — older than the vendored core, "nothing to do". No core update or migration needed; no product work — the only changes this session are its own bookkeeping commits.
- **Open items:** none from the sync. Observation for the owner: the local package-upstream checkout sits behind the project's vendored core (1.0.4 vs 1.0.5) — if the package repo is meant to be the release source for updates, the 1.0.5 content needs back-porting there.
- **Notes:** none
- **Report:** none (sync-only session; chat summary delivered)

**Re-check-in — same session, supervisor follow-up ("Re-sync core"); extends this entry, not a second Session 2:**
- Re-added my roster row same name/codename (`c2a71fcf` re-check-in, per the re-check-in rule) and ran kickoff Step 1 again: pull clean (already up to date), verify OK on 1.0.5, but `ledger-sync status` now showed the update source at **1.0.6** — the supervisor had back-ported the release into `C:\Users\tison\Dev\context-ledger` after my first sync, resolving this entry's earlier "upstream stale" observation.
- Same MAJOR → ran `ledger-sync update` (1.0.5 → 1.0.6; it replaces `core/` only, memory untouched). Migration was docs-only wording (CHANGELOG 1.0.6: sign-in moves to the entrance — the check-in is the first write of a session, the push claims the codename, concurrent-solo discovery resolves the main tree by conversation).
- Filled the migration's one step left, per kickoff rule 1: regenerated `.context_ledger/kickoff.md` and root `AGENTS.md` from the new templates and refilled the Project Facts (name/URL/privacy/branch/live-URL/git-identity/package-upstream); `memory/core.lock`, `.context_ledger/README.md` and `memory/workflows/active.md` (core ref → 1.0.6) updated with them. Committed as `f0982f82` (`chore(ledger): migrate to core 1.0.6` — 15 files, all ledger surface) and pushed. Placeholder scan clean (only the rule-1 comment and the token forms remain); `ledger-sync verify` OK on 1.0.6; pre-commit gate green before the commit; exit gate re-run at clock-out.
- **Outcome (follow-up):** done — core 1.0.6 in place, entrypoints regenerated, pushed. Clock-out commits: `aeb165be` (first, superseded by re-check-in) and this one.

---
## 2026-09-14 — Session 3
- **Agent:** Njeri (ZCode local) | **Model:** qwen3.8-flash (per system prompt `cf02f3d0-2445-43ea-ae61-da470b683985/qwen3.8-flash`) | **Platform:** Windows 11 (10.0.26200 x64), Lameck checkout | **Role:** engineer (protocol sync) | **Core:** 1.1.1
- **Task:** context sync on the supervisor's command (kickoff Steps 1–2): pull the project, verify the vendored core, check for drift.
- **Commits:** 9 (e4c19911..546cfe4a)
- **Outcome:** done — pull fast-forwarded d279b36c..03b677c3 (already carrying core 1.0.6 + Session 2's records); `ledger-sync verify` OK on 1.0.6; `status` showed the update source at **1.1.1** (same MAJOR) → `ledger-sync update` 1.0.6 → 1.1.1, then verify green. Migration 1.1.0 (MINOR) landed: roster Status/Status-detail columns (board upgraded to 6 columns at my S003 check-in), check-in-at-the-entrance ordering, door-triggered office close (this office: 3/20 — no close due), log compaction + one-way-linkage sweep. Regenerated `.context_ledger/kickoff.md` and root `AGENTS.md` from the new templates with Project Facts refilled (placeholder scan clean; only the rule-1 comment and token forms remain) and bumped `workflows/active.md`'s core ref. Solo light path followed (claim → work → release). No product code touched — the live-testing bar does not apply; everything is ledger-surface, exit-gate verified (full ci-check + bookkeeping).
- **Open items:** none from the sync — the standing Target (next: MCP client support) is untouched awaiting a directive; office-001's two carried protocol asks remain open in `flaws/log.md`.
- **Report:** .context_ledger/memory/office/reviews/2026-09-14-review-s3-sync.md
- **Notes:** none

---
## 2026-09-15 — Session 4
- **Agent:** Zuri (ZCode local) | **Model:** qwen3.8-flash (per system prompt `cf02f3d0-2445-43ea-ae61-da470b683985/qwen3.8-flash`) | **Platform:** Windows 11 (10.0.26200 x64), Lameck checkout | **Role:** engineer | **Core:** 1.1.3
- **Task:** supervisor directive (ZCode context-stats screenshot): split the lumped context-occupancy number into per-category shares — built the context-usage breakdown (feature `context-usage-breakdown`); also kickoff Step 1 sync (core 1.1.1 → 1.1.3).
- **Commits:** 11 (aaec56ba..8baac4c7; amended post-hoc — the flaws-watermark commit was not counted when the entry was written)
- **Outcome:** done — backend estimator (`core/agent/context_breakdown.py`: 7 categories, provider-total-scaled) wired into the loop + turn_complete/metrics events (`c7414ee1`); clickable occupancy meter with breakdown panel in the chat header (`d3d861c4`); changelog (`842d0e7d`); 12 new tests + 96 existing green in touched areas; LIVE-VERIFIED on zai/glm-4.5-flash (weather turn: shares sum == provider prompt_tokens 6552 exactly; tool schemas ≈44%). bankofai (primary) QUOTA-EXHAUSTED — owner action needed; Electron app relaunch not performed (user's instance owns port 8000).
- **Open items:** B-2026-09-15-1 (tree-wide ledger-vocabulary strip, 1438 hits — claimed by Baraka/S005 the same day); bankofai top-up/re-key; optional: persist the breakdown with per-turn metrics.
- **Notes:** none (report carries the detail)
- **Report:** .context_ledger/memory/office/reviews/2026-09-15-review-s4-breakdown.md

---

## 2026-09-15 — Session 7
- **Agent:** Asha (Claude Code local) | **Model:** hy3 | **Platform:** Windows 11 (10.0.26200 x64), Lameck checkout | **Role:** PA / liaison (supervisor-facing + worker-facing relay) | **Core:** 1.1.3
- **Task:** act as the supervisor's PA — relay his directives to the active office workers (Baraka S005, Neema S006) and carry his technical read on the transcript memory-failure block to Neema.
- **Commits:** 4 (roster check-in `34cf107a` + 2 relay notes `7e3f1f00`, `c4639f72` on top of S006's release; closing review+release+clock-out below)
- **Outcome:** done — both relay directives ("let them cook" -> Neema release as-is, Baraka continue) and the technical steer ("that's for Neema": memory read-back-gate + typed-schema framing) delivered and pushed; workers keep cooking.
- **Open items:** none — directives relayed and delivered; technical steer handed to Neema (S006).
- **Notes:** free-style PA session — no fixed role overlay, ran as pure relay/liaison. Concurrent with Neema's release; rebased clean.
- **Report:** .context_ledger/memory/office/reviews/2026-09-15-review-s7-ashapa.md

---
## 2026-09-15 — Session 6
- **Agent:** Neema (ZCode local) | **Model:** qwen3.8-flash (per system prompt `cf02f3d0-2445-43ea-ae61-da470b683985/qwen3.8-flash`) | **Platform:** Windows 11 (10.0.26200 x64), Lameck checkout (isolated worktree `../LocalMind-s006`) | **Role:** engineer (research / ledger surface) | **Core:** 1.1.3
- **Task:** supervisor directive — internalize his LocalMind v0.5 chat transcript (self-improvement & context-architecture discussion, 11:19–12:20, mimo-v2.5/bankofai) into a complete research document and file the discovered gaps + "what not to do" into the backlog; explicitly NO product building.
- **Commits:** 9 (c2cee32a..7bb77b24 + this bookkeeping commit; check-in, collab events, research doc + ADR-62 + 10 rows, the advisory -12 row, report, the six-weakness restructure, the PA-steer fold-in)
- **Outcome:** done — research doc `office/plans/2026-09-15-self-improvement-transcript-research.md` (full arc by arc: trending-location failure chain, three-layer context bootstrap vs. shipped code, memory-subsystem field report with code-verified references, six-gap inventory, turn economy, 11-item don'ts, PA steer addendum §4.6); ADR-62 (thinking-first build order) appended; 16 new backlog rows B-2026-09-15-2..-18 (High x6: -2/-3/-4/-13/-14/-15; Medium x9: -6/-7/-8/-9/-10/-12/-16/-17/-18; Low x1: -11) + evidence appends on 5 existing rows. Mid-session supervisor correction: first pass folded the owner's six-weakness self-assessment into one umbrella row — he re-pasted the passage; replaced the umbrella with six named rows at his granularity.
- **Coordination:** NOT solo — Baraka (S005) live in the main tree (uncommitted current.md claim; product sweep) and Asha (S007) PA/liaison arrived mid-session. Worked the full collab path per the project override: own worktree, note + claim + release events, additive-only roster edit, never `git add -A`; two push races resolved by rebase, zero collisions (disjoint paths). Owner directives relayed via S007 honored: release as-is, open questions filed (-12), PA steer folded in.
- **Verification:** memory-surface gates green (conflict-markers, backlog-dups, diff --check); product checks (ruff, tsc, full ci-check incl. pytest + eslint) passed from the provisioned main checkout — product code unchanged this session and byte-identical to S4's exit-gate-green tree. No live bar applicable (no product change). Raw public IP from the transcript deliberately NOT committed (the session's own volatile-fact lesson applied to itself).
- **Open items:** the 16 new rows (their summaries carry full context; ADR-62 is their decision anchor); B-2026-09-15-12 holds the owner's three design questions with the PA's leans recorded.
- **Notes:** none beyond the report
- **Report:** .context_ledger/memory/office/reviews/2026-09-15-review-s6-transcript-research.md

---
## 2026-09-15 — Session 8
- **Agent:** Imani (VS Code Copilot local) | **Model:** qwen3.8-flash | **Platform:** Windows 11 (10.0.26200 x64), Lameck checkout (isolated worktree `../LocalMind-s008`) | **Role:** engineer (product) | **Core:** 1.1.3
- **Task:** supervisor directive — backlog B-2026-09-11-1: `provider_usage` never reaches the SSE `done` event, so per-turn token cost is unmeasurable from the wire.
- **Commits:** product `7bd41196` (fix(api): forward provider_usage on the SSE done event — chat.py bridge + 2 tests) on branch `collab/usage-sse-done-20260915/imani-vc-qwen3.8-flash-s008`, integrated to main via refspec; ledger: check-in `9dc46c7c`, note `f90fd898`, claim `0213fd8e`, release `a0536d97` + this bookkeeping commit.
- **Outcome:** done — the `chunk.done` branch of `_event_stream` attaches `chunk.usage` as `provider_usage` on the done payload when non-empty (honest-zero: no provider call → field omitted; error/upload done events stay bare). The backlog's fast-path half was already fixed by `bcc383ce` (verified via `git log -L`), so the bridge was the sole gap. LIVE-VERIFIED on isolated 8765 (bankofai/mimo-v2.5, usable again — S4's quota outage has cleared): before = bare `{"type": "done"}` on a fast-path and a 4-tool turn; after = usage dict on both (fast-path `{prompt,completion,total}`; tool-loop the `total_*` set + `llm_calls`). Backlog acceptance met: `lm_benchmark --tests CAT1-1` now reports the token-efficiency section (input 313/output 173, was null). 133 unit tests + pre-commit + integration gates green. Backlog row deleted; test-catalog usage-capture note updated.
- **Verification:** live before/after SSE capture on isolated 8765 (scratch, gitignored) proves the done event goes bare→populated on both a fast-path and a tool-loop turn; benchmark acceptance re-measured via `lm_benchmark --tests CAT1-1`. Exit gate: bookkeeping check green; ci-check pytest step red on 27 failures = 22 in the documented nondeterministic tests/tools baseline (B-2026-09-09-7) + 5 OUTSIDE baseline. Provenance on the 5: all `UnicodeDecodeError: 'charmap'` from `read_text()` on `agent_runtime.py`/`chat.md` (a `⏹` emoji, byte 0x8f, invalid in cp1252) under a cp1252 locale — the SAME 5 fail on a clean tree and PASS under `PYTHONUTF8=1`; none read `chat.py`/`loop.py`, so NOT this session's surface. Filed as B-2026-09-15-19 (gate-runner env fix).
- **Coordination:** NOT solo — Baraka (S005) live in the main tree (uncommitted loop.py sweep), Tega (S009) + Jabari (S010) arrived mid-session. Full collab path per the override: own worktree, note (flagged chat.py/agent_runtime.py overlap with the sweep — behavior-only diff, no comment rewrites) + claim + release, additive roster edit, never `git add -A`; two push races → rebase, zero collisions. NOTE: the shared git index bit this session too — Baraka's `b49d16d1` swept my 7 staged clock-out files into his loop.py commit (the mixed-commit flaw he then logged himself in `281a6858`); the ledger content landed intact on main, only the commit boundary is mixed.
- **Open items:** none from this fix; owner note — bankofai works again; the Windows gate-PATH flaw stays open in flaws/log.md; the cp1252 pytest-locale gate gap filed as B-2026-09-15-19.
- **Notes:** two friction entries logged (gates' `sh` teeth on bare Windows PATH; cp1252 stdout + commit-message quoting) — one self-inflicted during bookkeeping itself: a double-quoted PowerShell here-string expanded `$env:...` inside the log entries (caught on re-read, repaired to prose form; single-quoted here-strings are the pattern).
- **Report:** .context_ledger/memory/office/reviews/2026-09-15-review-s8-usage-sse-done.md

---
## 2026-09-15 — Session 10
- **Agent:** Jabari (VS Code Copilot local) | **Model:** qwen3.8-flash | **Platform:** Windows 11 (10.0.26200 x64), Lameck checkout (isolated worktree `../LocalMind-s010`) | **Role:** engineer (product) | **Core:** 1.1.3
- **Task:** supervisor directive — backlog B-2026-08-20-12: embedding failure when Ollama unavailable silently disables memory; allow a cloud embedding fallback or document the Ollama requirement.
- **Commits:** product `cb69c53b` (fix(memory): bind a configured cloud embed backend when Ollama is unreachable — vector.py + config.py + 16 tests + CHANGELOG) on branch `collab/embed-fallback-20260915/jabari-vc-qwen3.8-flash-s010`, integrated to main via refspec; ledger: check-in `349317a6`, note+claim `ecf55bf2`, release `8563ff95` + this bookkeeping commit.
- **Outcome:** done — an OpenAI-compatible `/v1/embeddings` endpoint (`embed_adapter`/`embed_base_url`/`embed_cloud_model`/`embed_key_provider` in settings.json, or `LOCALMIND_EMBED_*` env) now binds at store-init when Ollama is unreachable and memory keeps working. One embedding space per index, fixed at bind time (process-wide `_USE_CLOUD`; `tool_result_index` shares the bound backend automatically); bound backend id persisted in `vector_meta(embed_backend_id)` → restart continuity re-binds, a foreign-space switch against a populated index REFUSES rather than mixing vectors (empty index may re-key dim); both cache tiers (LRU + persistent) key by backend identity; `_persist` refuses writes while a dim-mismatch guard is active (closes a latent `_set_dim` overwrite hole). No cloud config → behavior unchanged. LIVE-verified on an isolated harness with Ollama genuinely down: before = 503 on POST /api/memory + the exact backlog log line; after = store 200 ×2 + semantic recall through the cloud backend (Bearer + model contract in the stub's request log), `embed_backend_id` recorded in the DB, restart shows "2 facts stored" + recall works. Honest limit: cloud leg verified against a LOCAL OpenAI-compatible stub — no embedding provider key exists on this machine, so real-provider behavior is contract-tested only; z.ai's embedding API (the backlog's other candidate) unprobed.
- **Verification:** 16 new tests green; full tests/core + tests/storage green except the 3 known pre-existing failures (cp1252 locale — documented in B-2026-09-15-19, clears under PYTHONUTF8=1 — and 2 loop-surface dedup failures owned by the loop/vocab-sweep work); none read this session's surface. Pre-commit gates (diff --check, ruff, conflict-markers, backlog-dups) green; tsc verified from the main tree (worktree has no frontend node_modules — Neema's logged pattern).
- **Coordination:** NOT solo — Baraka (S005) main tree (uncommitted loop.py), Tega (S009) + Imani (S008, merged mid-session) live. Full override path: own worktree + venv junction, note + claim + release events, additive roster row, never `git add -A`; one rebase onto origin/main (peers landed ledger commits), zero path collisions. Discovered a peer's harness already on 8765 (their live-test server) — moved mine to 8767 rather than kill it; logged as friction.
- **Open items:** none from this fix; owner notes — real-provider embed smoke still worth one call when a key exists; Settings-modal exposure of the new embed fields left as a judgment call (report carries both).
- **Notes:** none beyond the report
- **Report:** .context_ledger/memory/office/reviews/2026-09-15-review-s010-embed-fallback.md

---
## 2026-09-15 — Session 9
- **Agent:** Tega (VS Code Copilot local) | **Model:** qwen3.8-flash | **Platform:** Windows 11 (10.0.26200 x64), Lameck checkout (isolated worktree `../LocalMind-s009`) | **Role:** engineer (product) | **Core:** 1.1.3
- **Task:** supervisor directive — backlog B-2026-08-17-4: three per-turn ChatMessage fields (thinkMs / diffData / candidates) render live but vanish on session-history reload; persist + restore them following the Session 266/290 pattern.
- **Commits:** product `b54fc6a7` (feat(history): persist thinkMs/diffData/candidates with the assistant message — agent_runtime.py accumulator + models.py/db.py columns + sessions.py mapping + best_of_n_edit.py obs emit + client.ts restore + ChatMessage.tsx BestOfNSection + 3 test files) on branch `collab/reload-fields-20260915/tega-vc-qwen3.8-flash-s009`, integrated to main via refspec; ledger: check-in `d73b6cdb`+`0abe823c`, note+claim `42a1d733`, correction `cd9c7a29`, release `9c603ca4` + this bookkeeping commit.
- **Outcome:** done — thinkMs is a runtime segment accumulator (parent + fast path, pauses on tool-narration chunks so tool time never double-counts) persisted as metrics[think_ms]; diffData is the collector's last file_diff event in a new messages.diff_data column; candidates is a new best_of_n_candidates obs event (emitted by the tool through the existing get_current_obs seam) in a new messages.candidates column. Restored edits render as the collapsed applied card (timestampEpoch discriminator); the candidate list gains a compact collapsible section. loop.py untouched as promised to Baraka (S005).
- **Verification:** 8 new backend tests + 1 new vitest case green; targeted 28+42+36 passed; tsc/eslint/ruff clean (one line-length fix); full backend suite 3094 passed with the 31 failures reproducing identically on clean origin/main (24 tests/tools + 7 loop-surface — pre-existing, none read this surface); integration gate green; LIVE-verified on isolated :8765 — real edit turn (1050 thinking tokens) → live diff SSE → history reload returned thinkMs=123593 + full camelCase diffData.
- **Coordination:** NOT solo — Baraka (S005) main tree (loop.py + vocab sweep), Imani (S008, merged mid-session), Jabari (S010) live. Own worktree + collab note/claim/correction/release events, additive roster row, never git add -A (the shared-index trap from the S005 flaw stayed clear — twice peers' pending files were in the working tree and both times only my paths were staged); two rebases onto origin/main (Jabari's product + exit landed mid-exit), zero path collisions.
- **Open items:** none from this fix; owner notes — candidates restore-only by design (no SSE bridge; chat.py doesn't forward generic obs events and the list was never live-rendered); a live best_of_n bridge + multi-edit-per-turn diff persistence remain open if the supervisor wants them.
- **Notes:** none beyond the report
- **Report:** .context_ledger/memory/office/reviews/2026-09-15-review-s009-reload-fields.md

---
## 2026-09-16 — Session 11
- **Agent:** Makena (VS Code Copilot local) | **Model:** Qwen3.8 Flash | **Platform:** Windows 11, tison checkout (main tree) | **Role:** engineer (ledger sync) | **Core:** 1.2.0
- **Task:** supervisor directive "Sync ledger" — pull, verify/status the vendored core, apply the available same-MAJOR update, land everything committed and pushed.
- **Commits:** 4 ledger (check-in `dd2c05e0`, note+claim `28429f46`, core update `55373d41`, release+bookkeeping this commit); zero product commits.
- **Outcome:** done — tree clean and level with origin before sync; `ledger-sync verify` green (1.1.3); `status` surfaced 1.2.0 at the local upstream (C:\Users\tison\Dev\context-ledger), applied via `ledger-sync update` (same-MAJOR, core-only, memory untouched). Project files refreshed to match the 1.2.0 templates per the migration's fill step: kickoff.md close-section re-seed wording + stray `<` typo in the upstream URL fixed, AGENTS.md rules 5–6 (capped work queue + parking-lot knowledge base), active.md version line → 1.2.0, collaboration/README.md + office/sessions/README.md backlog descriptions; `tasks/parking-lot.md` seeded in the office (template copy).
- **Verification:** post-update `ledger-sync verify` green (migration ran it); `ledger-mem check` green except the designed warn-only backlog nudge (84 rows vs cap 20 — triage deliberately NOT done this session, it is a content task; flagged in the note event); conflict-markers + backlog-duplicates checks pass via Git Bash (the gate runner's `sh` teeth still missing on bare Windows PATH — known flaw, not re-logged). Pre-commit product legs (tsc/ruff) not applicable: commit touches zero product files.
- **Coordination:** Baraka (S005) row live on the board but silent ~7h (last main commit 21:19, work on `origin/collab/S005/baraka`, clean tree) — treated as possibly-returning, not adopted, not removed. Light path per collaboration README: note (heads-up, disjoint scope) + claim (ledger-only paths) + release (citing dd2c05e0,28429f46,55373d41). Additive roster edit; staged explicit paths only, never `git add -A`.
- **Open items:** backlog triage — 84 rows vs the new cap: split knowledge (findings/questions/deferred) into `tasks/parking-lot.md`, prune finished/stale rows, keep ≤20 actionable (candidate for a dedicated session; the `ledger-mem check` warn fires until then). Current office carries a stale-row hazard: S005's row + the current.md claim predate this session; if Baraka does not return before the office closes, the closing session decides disposition.
- **Notes:** none beyond this entry
- **Report:** none (sync session — this entry is the record)

---
## 2026-09-16 — Session 12
- **Agent:** Zawadi (VS Code Copilot local) | **Model:** Qwen3.8 Flash | **Platform:** Windows 11, tison checkout (main tree) | **Role:** engineer (office maintenance) | **Core:** 1.2.0
- **Task:** supervisor directive — prune leftover worktrees from old (S4xx) sessions: identify stale ones (no active session, no uncommitted work worth keeping), flag ambiguous cases before deleting.
- **Commits:** ledger-only — check-in `ba228fae`, session log + clock-out + flaw entry (this commit); zero product commits.
- **Outcome:** done — 10 stale collab worktrees removed (`LocalMind-collab-live/-loop/-mara/-talia/-zcode-419`, `LocalMind-mara-s445`, `-omari-s472`, `-tavi-s440`, `-zcode-419`, `-zuri-s438`), 17 stale local `collab/*` branches deleted, `worktree prune` clean. Audit before teardown: every worktree checked for dirty files and commits ahead of origin/main; the two dirty ones held only regenerable residue (30 smoke-test PNGs under pre-protocol `.context/`, one `core.lock` line) with zero unmerged commits. Unmerged branches were zcode-419 (product work already on origin, integration-era) and the coordination trails (event history, on origin). Supervisor then gave an explicit blanket delete order ("just delete them") after seeing the flagged ambiguities — executed with one insurance step first: `git bundle` of all local-only collab commits (`scratch/stale-collab-branches-2026-09-16.bundle`, 188 objects) so nothing was irrecoverably destroyed. Remote `origin/collab/*` branches left in place (deleting those is origin-side history, outside this directive). Two directories survived `worktree remove --force` (leftover `node_modules`/`backend` build dirs git doesn't track) — removed by hand. `git worktree list` is now the main tree only.
- **Verification:** post-teardown checks: only `LocalMind` dir remains under Dev, `git worktree list` shows one entry, `git branch` shows only `main`, bundle verified written (exit 0). No product files touched; the pre-existing `current.md` modification in the tree is Baraka's (S005) and was left untouched, never staged.
- **Coordination:** NOT solo — Baraka (S005) and Chemi (S013) live on the board; scopes disjoint (vocabulary sweep / backlog triage vs worktree metadata). Check-in raced with Chemi's (both landed as S012); Chemi renumbered to S013 in `1114a36a` and I kept S012 per first-push-wins. No collab events emitted — my surface is git metadata + local dirs, no path overlap with either peer.
- **Open items:** none — worktree board is clean. Owner note: origin still carries ~20 `collab/*` remote branches; pruning those is a separate call.
- **Notes:** logged a protocol-adherence flaw this session — I ran the startup analysis before pushing my check-in row and the supervisor had to call it out (see flaws log).
- **Report:** none (maintenance session — this entry is the record)

---
## 2026-09-16 — Session 5
- **Agent:** Baraka (ZCode local) | **Model:** qwen3.8-flash (per system prompt `cf02d3d0-245-43ea-aef1-da470b683985/qwen3.8-flash`) | **Platform:** Windows 11 (10.0.26200 x64), Lameck checkout | **Role:** engineer | **Core:** 1.1.3 → verify OK (1.2.0 in gate check)
- **Task:** B-2026-09-15-1 — tree-wide strip of `.context_ledger` vocabulary from product files. Supervisor method directive mid-session: strip by hand with per-line understanding, no scripted bulk transform.
- **Commits:** 19 (claim `dbb5647f` + loop.py `b49d16d1` on main; sweep branch 12 commits → merge `5e85c342`; `9035b969`, `cefff469`, stragglers) — product diff vs pre-sweep: 366 files, +3585/−2289 (includes peers' merged code; the sweep itself removed ~2,650 citation lines).
- **Outcome:** done for the product runtime surface — backend/src, backend/data (app runtime memory data), frontend/src + index.html, electron, scripts, migrations, CHANGELOG, localmind.md now have ZERO ADR-N / bug-ID / Session-NNN / `.context_ledger/` citations; two test files renamed out of the adr-tag class (live import + pyproject repointed); 3 ledger-service scripts parameterized instead of exempted; AGENTS.md/CLAUDE.md + ruff-noqa + test_db fixture exemptions documented in overrides. ~540 citation lines remain ONLY in tests/ (~384), docs/ (~95) and live-test script headers (~50) — the same mechanical class, handoff state recorded on the backlog row.
- **Open items:** B-2026-09-15-1 stays open for the tests/docs remainder (method + exact census on the row). Exit gate: 24 pytest failures — bisected (`5e85c342^1`): they PRE-EXIST on main and are the documented Windows flaky family (B-2026-09-09-7 / B-2026-09-05-4); ruff/tsc/eslint/conflict-marker/bookkeeping all pass on the merged tree.
- **Notes:** `.context_ledger/memory/office/sessions/2026-09-15-5/notes.md` + report below. Two process failures owned in the logs: a blind-regex attempt (retired before write after it demonstrated corruption) and one `git commit` that swept a peer's staged closeout into b49d16d1 (correction note `20260915T140409Z-Baraka-c6daa516`, flaw entry logged).
- **Report:** `.context_ledger/memory/office/reviews/2026-09-16-review-s5-vocab-strip.md`

---
## 2026-09-16 — Session 13
- **Agent:** Chemi (Freebuff desktop agent) | **Model:** Qwen3.8 Flash | **Platform:** Windows 11, Lameck checkout (main tree) | **Role:** engineer (office maintenance / backlog triage) | **Core:** 1.2.0
- **Task:** supervisor directive — backlog triage to the core 1.2.0 cap: split knowledge into `tasks/parking-lot.md`, prune done/stale rows, keep ≤ 20 actionable.
- **Commits:** 3 ledger (resume + claim f3bdb530; the triage 3a009e02; this bookkeeping commit); zero product commits.
- **Outcome:** done — backlog 84 → 20 actionable rows (5 High / 8 Medium / 7 Low), written from my own 15:03 draft found in scratch (backlog-new-s013.md) verbatim, provenance paragraph corrected to the shipped reality; parking lot 59 rows P-2026-09-16-1..59 (former B- IDs kept in-row via a provenance tail; B-2026-08-25-2 + B-2026-08-25-10 merged at P-26; 6 advisory rows under Open questions); 5 rows deleted as done/stale on the file's own recorded evidence (B-2026-08-24-13/-14, B-2026-08-25-6 done-pending-sign-off; B-2026-08-24-8 a standing practice, not a task; B-2026-08-30-8's half shipped, residual noted in prose). `ledger-mem check` green — the cap warning standing since Session 11 is cleared.
- **Verification:** script-asserted before write — parked bodies byte-identical to pre-triage originals (ID cell + provenance tail excepted), zero B- leaks, P-census exact, raw-pipe shape 3/row; two build defects (EOF single-line row unparsed; aliasing orphan lines in the first lot build) caught by asserts and fixed pre-commit with a git-HEAD rebuild. Pre-commit gate green; no product surface touched.
- **Coordination:** solo — Baraka (S005) clocked out, current.md idle at arrival; light path (note + claim + release on the event trail, all citing this session).
- **Open items:** none new. The 59 parked rows keep their B- IDs; promote back to the backlog when one turns actionable (the provenance tail preserves every pointer).
- **Notes:** two Windows-box tool traps hit first-hand and logged in inefficiencies (heredoc fence/escape mangling thrice-logged family; plus my own parser/aliasing lesson). Supervisor correction honored: check-in had already happened pre-9:00 (row verified at the door, not re-created).
- **Report:** .context_ledger/memory/office/reviews/2026-09-16-review-s013-backlog-triage.md

**Re-check-in — same session, supervisor follow-up ("Add .freebuff/ to .gitignore and commit it"); extends this entry, not a second Session 13:**
- Re-added my roster row same name/codename, `current.md` set live (re-check-in rule), pushed as `ba30a86c`.
- Shipped: `.freebuff/` (the desktop agent's local project marker — one UUID file, untracked) appended to `.gitignore` under its own comment block; `git check-ignore -v` verified the rule bites. Committed as `25a0fc2a` (`chore(gitignore):`) and pushed. Pre-commit gate green on the product diff (tsc, ruff, conflict-markers, backlog-dups); the worktree is now fully clean — no untracked residue.
- Clock-out: row removed, `current.md` idle, entry extended in this closing commit.
- **Commits (extended):** 5 ledger (resume + claim `f3bdb530`, triage `3a009e02`, closeout `ad7d3617`, re-check-in `ba30a86c`, this closing commit) + 1 product (`25a0fc2a`).

---
## 2026-09-17 — Session 14
- **Agent:** Buffy (Freebuff desktop agent) | **Model:** not exposed to the session (Freebuff desktop) | **Platform:** Windows 11, Lameck checkout (main tree) | **Role:** engineer | **Core:** 1.2.0
- **Task:** backlog head `B-2026-09-15-3` (typed memory write path) with the `B-2026-09-15-4` reliability mechanics it gated — one surface: what a write accepts, what identity the row gets, what the app may claim about it afterwards.
- **Commits:** 3 product (`9ba42626` typed/keyed/verified write path; `b1a8aa96` delete without a vector index; `5ed4a22a` live-trace harness) + 1 `docs:` CHANGELOG (`2c28bac5`) + 3 ledger (check-in `797f0012`, claim `55b547b8`, report/ADR/queue `271ae3e8`); 55 new/updated test cases.
- **Outcome:** done for the row. Durability is policy in code — `VOLATILE` (IP/MAC/IPv6 literals, ISP, live machine readings, "right now" framing) is refused with the reason in plain words; `PREFERENCE`/`STABLE_FACT` are stored carrying `memory_freshness` + `memory_confidence` — and the rule runs in the tool *and* the autonomous extraction paths (the IP had arrived through the second door). `canonical_key()` hashes a fact's identity into the row id, so a restatement replaces its row, a keyed write supersedes a near-identical unkeyed row, and the degraded plain-text path writes the keyed id instead of a fresh uuid (the duplicate source). Every mutation is confirmed from a read-back, so an unverified write / refused write / failed removal says so instead of claiming success. Deletion resolves by id, id prefix, re-worded content, then key, and no longer needs the vector table. Two live bugs killed inside the row's own surface: the model's bare `operation=list` was persisted as a fact (the "garbled list" symptom), and every delete failed on a store with no vector table (the "forget missed" symptom).
- **Verification:** live before/after on the same four turns from a worktree at the previous revision (`74817201`): live value stored → refused with 0 such rows; restated preference 2 rows → 1; delete-by-short-id 404-row-stayed → deleted; model's listing call persisted the word "list" → returned the id-bearing listing. Artifacts preserved under `office/sessions/2026-09-17-14/evidence/` (scratch is gitignored). Unit: 55 cases green — policy verdicts and keys, the read-back gates, prefix/content deletion, delete without a vector table, bare-operation dispatch. **Assumed, not proven:** the key heuristic collapses re-statements sharing a named subject or leading words; with the embedder down a genuinely re-worded restatement still makes a second row.
- **Gate:** pre-commit gate green (tsc, ruff, conflict markers, backlog dups, ledger lint). Full-suite run shows the documented Windows flaky family only; the three failures that looked new (`test_sql_tool::test_rejects_disallowed_path`, `test_sql_tool::test_not_a_database`, `test_propose_edit::test_propose_str_replace_permission_gate`) reproduce at `74817201` — environmental (temp-dir sandbox), not a regression.
- **Coordination:** solo — roster empty at arrival, `current.md` idle, 13 sessions in the office; light path only (note + claim + release on the event trail).
- **Open items:** `B-2026-09-17-1` — filed from this session's own live finding (reads/deletes are not routed deterministically: a live "what do you know about me" was answered from conversation context, naming the very live value the write path had just refused) and taken up as this session's follow-up. Also open: the freshness tags have no consumer until the parked geolocation/context bootstrap lands; junk rows written by the bare-operation bug before today are unpromoted; `PATCH /api/memory/{id}` still needs the vector table for its re-embed.
- **Notes:** one protocol flaw owned in the flaws log — check-in was on time, but `current.md` and the claim were written only after product work had started, leaving the in-flight scope invisible; logged with a mechanical-nudge suggestion. Three Windows tool traps logged in inefficiencies (`code_search` ripgrep missing → grep fallback; cp1252 `UnicodeEncodeError` killing a live run mid-way; the 600 s ceiling vs a 3094-test suite). Detail + evidence index: `office/sessions/2026-09-17-14/notes.md`.
- **Report:** `.context_ledger/memory/office/reviews/2026-09-17-review-s14-memory-write-path.md`

**Re-check-in — same session, resumed 2026-09-18 after two connection drops mid-turn (supervisor: "Continue"); extends this entry, not a second Session 14:**
- Re-added the roster row (same name/codename), released the write-path claim and
  claimed the follow-up on the event trail (`22a7918d` release + `20f8b2ac` claim,
  `ea4ad038`) BEFORE touching product code this time — the Session 14 flaw not
  repeated.
- **Shipped `B-2026-09-17-1` (deterministic memory read/delete routing):**
  `backend/src/core/agent_runtime.py` routes `is_read`/`is_delete` turns to
  `memory_op` directly — the reply is the store's id-bearing listing, a removal
  is confirmed from a read-back, both leave the full turn trail (user row before
  reply via the existing `_persist_user_before_reply` seam, new
  `_finish_memory_turn` epilog), and a failed store says so instead of raising
  the turn. `memory_intent.py` gates sharpened: a read cue means the stored
  facts about the user ("what do you know about Python" falls through to the
  model); a delete cue must name a removable fact ("forget it, let's move on",
  "delete that file" never reach memory); `memory_tool.py` takes an explicit
  `operation` that WINS over re-reading the sentence for cues (the
  garbled-listing-gets-stored class) with alias normalisation and honest
  fallbacks (search→recall, garbage→sentence cues).
- **Live bug found and fixed by the harness:** "forget that I prefer dark mode"
  reported "Nothing in memory matches" — `matching_ids` needed the exact stored
  wording. Added a conservative word-overlap tier under the exact/prefix/key
  tiers in `storage/vector.py` (`_matching_ids_in_rows`, shared with the
  tool-level fake): every content word the user named must sit on the row, the
  row may add at most two content words of the app's voice tail; a
  more-specific row ("dark mode on the mechanical keyboard") is left alone and
  a vague one-word target matches nothing.
- **Commits:** `ea4ad038` (claim/release events), `58ffec18` (the routing fix,
  8 files, +812/−111), `75638e75` (live harness), `aff07f49` (CHANGELOG).
- **Verification:** 57 new routing/intent tests + the two write-path signature
  tweaks + 14 new/updated tool tests (incl. the re-worded-forget regression,
  specific-row guard, vague-target guard) + 317 memory/persist/fastpath-core
  tests + 72 vector/api/memory-adjacent tests all green; pre-commit gate green
  (tsc, ruff on backend/src, conflict-markers, backlog-dups). LIVE-VERIFIED per
  the bar, `scripts/live_test_memory_routing.py` (committed) on zai/glm-4.5-flash
  with a scratch `LOCALMIND_HOME`, before/after on the same three turns: read
  went model-improvised-from-context (echoing the live IP value the write path
  refuses) → the store's own listing; list went 105.6 s rate-limited loop →
  4.3 s listing; forget went error-with-row-still-there → "Removed from memory"
  with the row read-back-gone. After the fix: all three turns ~4.5 s with zero
  provider calls. Assumed, not proven: the app-voice-tail allowance (≤2 extra
  content words) on stores whose facts were written by much longer template
  sentences; no cloud embedder on this box, so the embed-present dedup path was
  not exercised live.
- **Coordination:** Nia (S015) live the whole session on the connections layer;
  disjoint claimed paths, no conflicts; her `_provider_name`→`_provider_key`
  fix sat uncommitted in the shared tree at my wrap-up — not mine, left alone,
  flagged to her on the trail.
- **Open items:** junk rows written by the bare-operation bug before 2026-09-17
  are still unpromoted (owner call); `PATCH /api/memory/{id}` still needs the
  vector table for its re-embed; the freshness tags still have no consumer
  until the parked geolocation/context bootstrap lands.
- **Notes:** two inefficiencies owned in the log (the connection drop eating
  the sync-session's own background launch — `nohup`/`&` dies with the call,
  `tasklist`-check-then-relaunch is the pattern; the direct-SQL seed route for
  embedder-less boxes after REST seeding 503'd). Evidence:
  `office/sessions/2026-09-17-14/evidence/routing/` (before/after results,
  server logs, turn-1/turn-3 SSE).
- **Report:** `.context_ledger/memory/office/reviews/2026-09-18-review-s14-routing.md`
- **Gate (exit, 2026-09-18):** pre-commit gate green before every commit. Exit legs:
  ruff / conflict-markers / tsc / eslint (0 errors, exactly the 53 allowed
  pre-existing warnings) / bookkeeping all PASSED. The pytest leg exited 1 on
  24 failures = the 22-node baseline + 2 non-baseline
  (`test_workspace_state::test_snapshot_diff_since_mark_turn_start` — a
  test-internal `git add.` shell typo creating a temp git repo — and
  `test_browser_agent::test_read_reextracts_current_page_without_url`), BOTH
  run at the pre-work revision `ea4ad038` and reproduced identically there:
  environmental, not a regression (provenance per the S008 precedent; 3198
  passed). Baseline refresh stays owned by B-2026-09-09-7 — not done here.
  Evidence: `scratch/s014-exit/` (full log, per-leg outputs, the bisect run).
- **Clock-out:** row removed in the closing ledger commit; both scratch
  worktrees removed; no branch was created (all work landed on main per push
  policy).

---
## 2026-09-18 — Session 16
- **Agent:** Zola (Claude Code local) | **Model:** claude-sonnet-5 | **Platform:** macOS (Darwin 24.6.0), Tisone's checkout (main tree) | **Role:** engineer (ledger sync) | **Core:** 1.2.0
- **Task:** supervisor directive "pull and sync context" (kickoff Step 1–2) — pull the project, verify the vendored core, check for drift.
- **Commits:** 4 ledger (check-in `ff409104`, note+claim `dfd08f1b`, this bookkeeping/release commit); zero product commits.
- **Outcome:** done — `git pull --ff-only` fast-forwarded `97894961..2f811970` cleanly (roster/sessions bookkeeping only, no conflicts). `ledger-sync verify` OK on 1.2.0 (every file matches MANIFEST.sha256, all ports parse — ps1 parse check skipped, no PowerShell engine on this Mac, covered by the manifest + a PS-hosted verify elsewhere). `ledger-sync status`: locked 1.2.0, update source (`../context/core`) reports **2.0.1 — a MAJOR bump**. Per kickoff Step 1 rule, a MAJOR update is noted only, not auto-applied: needs the owner's go-ahead plus a CHANGELOG.md read before `ledger-sync update --major`.
- **Coordination:** NOT solo — Nia (S015) live on the board (connections-layer architecture planning, disjoint scope). Light path per collaboration README: note (heads-up, ledger-only, no product paths) + claim (roster/sessions/current.md) + this release, all citing the event trail; zero path overlap.
- **Verification:** `ledger-sync verify`/`status` output above is the verification; no product surface touched so tsc/ruff/pytest gates are not applicable to this session's diff.
- **Open items:** owner decision — apply the 2.0.1 MAJOR core update (read its CHANGELOG.md first) or stay on 1.2.0.
- **Notes:** none
- **Report:** none (sync-only session; chat summary delivered)

---
## 2026-09-18 — Session 15
- **Agent:** Nia (S015) | **Model:** deepseek/deepseek-v4-pro (architecture + backend build) → **claude-sonnet-5 (Claude Code local)** continuing the same session, engaged directly by the owner to pull Nia's worktree and finish the work as her | **Platform:** macOS (Darwin 24.6.0), Tisone's checkout (isolated worktree `.claude/worktrees/nia-s015`) | **Role:** engineer (product) | **Core:** 1.2.0
- **Task:** the AI Connections layer (P-2026-09-18-1) — replace the product-code-only provider list with a `connections` array in settings.json (preset providers as seed connections + user-defined OpenAI-compatible endpoints), so a new endpoint needs a Settings-UI action instead of ~5-8 file edits. Nia's own half (architecture assessment + backend) was parked pending owner approval; the owner then directed a fresh Claude Code session to pull her worktree and finish the work under her identity.
- **Commits:** product, on `collab/S015/nia-s015` (Nia: `43c401a1` design claim, `96905c84` park, `82dc2aae` backend; this session: `d0de723c` frontend + models.py fix), merged to main `106a612e` (`--no-ff`, owner-approved after the auto-mode classifier blocked an unattended merge into main) + pushed; this bookkeeping commit.
- **Outcome:** done and shipped to main. **Nia's backend** (`82dc2aae`, already reviewed in full before continuing): `core/connections.py` (new) — `Connection`/`ConnectionCapabilities` dataclasses, `ConnectionRegistry` merging preset seeds (from `PROVIDER_CONFIGS`) with `settings.json` records; `adapters/__init__.get_adapter` and `core/model_router` resolve adapter names through the registry instead of the old `CLOUD_PROVIDER_NAMES` allowlist (preset ids unchanged, so nothing existing regresses); `OpenAICompatAdapter` takes an optional `connection` record, honors declared capabilities (streaming/tool_calling/context_window), and the `_provider_name`→`_provider_key` fix noted as uncommitted in S014's log (2026-09-17) is in this commit; `api/routes/config.py` gained `POST/DELETE /api/settings/connections` (create/update/reset/delete) and `POST /api/settings/connections/{id}/test` (a 4-check live probe: /models reachability+auth, non-streaming chat, streaming, tools-parameter acceptance — learns capabilities back onto the record). **This session's half:** the Settings modal had no UI for any of this — `connections` came back from `GET /api/settings` unused. Added an "AI Connections" section (list/test/enable/edit/delete + an add-connection form) and folded enabled custom connections into the existing provider-picker grid and API-key list so a custom connection behaves like a built-in provider everywhere in the UI; `client.ts` gained `saveConnection`/`deleteConnection`/`testConnection` + the `ConnectionRecord`/`ConnectionTestResult` types. While live-testing found and fixed a real bug: `GET /api/models` (the no-`provider` form the sidebar model selector calls) resolved the current/live model list only through `PROVIDER_CONFIGS`/`ADAPTER_MODEL_FIELDS` — both preset-only maps — so switching to a custom connection left the model chip stuck on the previous provider's model and the dropdown empty; fixed to resolve `current_model` from the connection registry first and live-list models for any non-preset connection.
- **Verification:** unit — 28 new connections tests (Nia's) + the full backend suite: 3213 passed, 2 skipped, exactly the same 2 pre-existing failures documented at S014's exit (`test_workspace_state::test_snapshot_diff_since_mark_turn_start`, `test_browser_agent::test_read_reextracts_current_page_without_url`) — not this session's surface. `tsc -b --noEmit` clean, `eslint` clean on every touched file, `ruff check backend/src` clean. **Live-verified per the mandatory bar** (chose a genuine external endpoint outside the preset list rather than a mock, to prove the *custom*-connection path for real): created a connection through the Settings UI pointed at the local Ollama server's OpenAI-compatible API (`http://localhost:11434/v1`, no key, real network calls) — the test probe reported `reachable: true · auth: true · streaming: true · tools: accepted` against the live server; switched the active adapter to it and the model chip/dropdown correctly showed `phi4-mini:latest` (proving the `/api/models` fix); sent a real chat message through the full parent-agent loop — turn completed in ~2min (small CPU model, expected), 1 real tool call (`memory_op`), 2.0K prompt / 15 completion tokens, non-zero token accounting throughout. Regression-checked existing presets in the same live session: switching to `ollama` and `zai` (has a saved key) both still work; switching to `anthropic` (no key) is still correctly rejected with the existing error message — the registry refactor changed nothing about preset behavior. Cleaned up afterward: deleted the test connection and restored the adapter to `zai`, `~/LocalMind/settings.json` verified back to a clean `connections: []`.
- **Coordination:** the owner (Tisone) directly instructed this session ("pull Nia's worktree and finish the work as her") — the kickoff protocol's identity rule ("that row is mine… justified only by… the user's word") applies exactly here: Nia's roster row was live with a genuine in-progress task, this session's model is a different fingerprint (claude-sonnet-5, not deepseek-v4-pro), and continuity is claimed on the owner's explicit instruction, not inferred. Read Nia's full backend diff before writing a line, to understand the design before extending it. The owner also flagged mid-session that API-key encryption is worth doing (json keys stored plaintext) — already tracked as `P-2026-09-16-29` (OS-keyring approach chosen, deferred pending an unrelated VS Code 403 diagnosis) — pointed to it rather than duplicating scope here.
- **Open items:** `P-2026-09-18-1` in the parking lot should be marked shipped (see the parking-lot edit in this commit) rather than "awaiting approval" — the owner's live-testing directive was the approval. No new open items from this work; the connections layer covers presets + custom endpoints uniformly.
- **Notes:** the merge to main was blocked once by the auto-mode classifier (an unattended `git merge`/push to a shared branch) — paused and asked the owner via AskUserQuestion rather than retrying past the block; owner chose "merge now," then it went through cleanly (no ledger-file conflicts — Nia's check-in/claim/park ledger commits were already on main directly, only her product commits lived on the isolated branch, matching this repo's established pattern).
- **Gate (exit, 2026-09-18):** pre-commit gate green on every commit. `ledger-mem lint --tree` flags ~40 pre-existing ADR/bug-ID citations in `tests/` — all predate this session, none in a file this session touched, all already covered by the open `B-2026-09-15-1` tests/docs remainder; left alone as out of scope. Exit gate's pytest leg reported the same 2 failures as "new" (not in `scripts/pytest-baseline.txt`) that S014 (2026-09-18) already documented as environmental and reproduced at the pre-work revision `ea4ad038`: `test_workspace_state::test_snapshot_diff_since_mark_turn_start` (a test-internal `git add.` shell typo) and `test_browser_agent::test_read_reextracts_current_page_without_url` (an assertion string missing a space, unrelated to any adapter/connections code). Confirmed again this session: both failed identically in a full-suite run taken before this session's code changes existed, on Nia's backend alone. Baseline refresh stays owned by `B-2026-09-09-7` (stale file, explicitly not done here — same call every session since S008). ruff/tsc/eslint/bookkeeping legs all PASSED (3251 passed, 2 skipped otherwise).
- **Report:** none (chat summary delivered; this entry + the commit trail carry the full detail)

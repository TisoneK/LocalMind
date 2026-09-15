# Session Notes: 2026-09-15 — Session 5

## 2026-09-15 — Baraka / qwen3.8-flash (Session 5) — manual ledger-vocab strip (B-2026-09-15-1)

### Supervisor directive (mid-session, decisive)
- A scripted bulk transform was designed and dry-run-tested (~2,588 lines,
  review log in `scratch/`), then the supervisor rejected it: **strip by hand
  with per-comment understanding** — the rewriter must understand each context,
  no blind token-dropping. Script retired; only its inventories stay useful.
- Continuity: the prior Baraka context died after check-in (`baf99ccd`) + the
  `current.md` claim; no product work had landed.

### Scope & approach
- Tree-wide strip of `.context_ledger` vocabulary from product files
  (one-way-linkage rule). Classes: ADR-N, ledger bug IDs (B-YYYY-MM-DD-n),
  `.context_ledger/` paths, "per ADR", plus extended classes: Session N /
  S<NNN>, lowercase adr refs, ledger review-N, feature labels (F3 + name),
  token-bearing filenames (git mv).
- Rewrite principle: replace the citation with the plain words it pointed at;
  the comment must read true for someone holding only the product repo.
  Comments/docstrings/test names only — zero behavior change.
- Regenerate queue: `ledger-mem.cmd lint --tree`; extended scan:
  `grep -rnE 'Session [0-9]+|\bS[0-9]{3}\b|review-[0-9]+' backend/src frontend/src tests scripts docs CHANGELOG.md`.
- Per-file census: `scratch/scratch_perfile.txt` (gitignored, machine-only —
  regenerate if missing). Top: loop.py 177, constants.py 44,
  test_coding_agent.py 30, base_agent.py 28, useLocalMind.ts 27, chat.py 25,
  models.py 23, config.py 20/16, openai_compat.py 20, coding/tools.py 19,
  client.ts 17, tools/__init__.py 17, docs 16+16, tool_schemas.py 16,
  types/index.ts 15, agent_runtime.py 14, then a long tail (430 files).

### Exemptions & special cases (claim event 20260915T120910Z-Baraka-bd7b3ebe)
- EXEMPT via overrides doc: AGENTS.md, CLAUDE.md — generated agent-entrypoint
  digests; their lint hits are expected noise. Write the exemption bullet into
  `memory/overrides/rules.md`.
- Scripts fixed by hand (parameterize, not exempt):
  - `scripts/check-conflict-markers.sh` — take memory dir as $1 (gates.conf
    passes it; check-bookkeeping.sh precedent).
  - `scripts/lm_conversation_tests.py` — reword docstring pointer ("the
    project memory catalog"), drop the path.
  - `scripts/run_suite_detached.sh` — KEY_FILE literal → required env var;
    document in system/live-testing.md.
- Manual, NOT bulk-rewrite: `backend/data/.context/` — the app's OWN runtime
  memory injected into prompts; rewrite `**Session NN:**` leads by hand,
  keeping every bug fact intact.
- NO_TOUCH pins: `tests/storage/test_db.py:55,56,59` — "Session 1/2 message"
  is round-tripped app fixture DATA, not a citation.
- False-positive classes to LEAVE: lowercase `session-1` fixture ids in
  frontend tests; `# noqa: S603` style ruff codes (SNNN collides with
  codenames); "session 1:1" export test titles.
- Renames (git mv, then grep the old names for references):
  `tests/adapters/test_thinking_policy_adr41.py` → `test_thinking_policy.py`;
  `tests/core/test_adr32_fail_fast.py` → `test_fail_fast.py`.

### Office state at resume
- Peers after original check-in: Neema (S006) shipped transcript research,
  memory-surface only, explicitly excluded this task; RELEASED
  (20260915T103505Z-neema-s006-b2ec7dd4). Asha (S007) PA relay, clocked out;
  owner directive via Asha: "let them cook" — Baraka continues. Neema's roster
  row still shows Working (clock-out commit pending, hers to fix) — no
  uncommitted peer changes in the tree; proceeding solo with strict
  add-by-path discipline.
- Core 1.1.3 verify green; up to date with origin.

### Progress log (update at every commit; line numbers SHIFT as edits land — re-grep before each window)
- loop.py (353 trigger-lines / 294 clusters): DONE — grep now reports 0 hits for
  ADR/B-ID/Session/SNNN/review/per-adr; `F<digit> ` guard also 0; ruff clean.
  Working decisions: citation LEAD deleted + sentence capitalized; provider/model
  live-trace detail KEPT (product fact); "Session N" evidence → "Seen live:";
  "F4 post-execution verifier" → "post-execution verifier"; "(line ~3819)" →
  dropped (stale code self-ref); spec §N refs → replaced with the plain rule or
  dropped. One near-miss during the pass: an over-broad old_string briefly
  clobbered the goal_tree param — caught by re-reading, restored verbatim.
- constants.py + models/prompts/tool_schemas: NEXT.
- Everything else untouched. No product commit yet (working tree carries the
  loop.py edits; they survive context rolls).

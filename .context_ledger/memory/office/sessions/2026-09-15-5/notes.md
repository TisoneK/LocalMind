# Session Notes: 2026-09-15 — Session 5

## 2026-09-15 — Baraka / qwen3.8-flash (Session 5) — manual ledger-vocab strip (B-2026-09-15-1)

### ISOLATION (mandatory override — live peers in office)
- After commit b49d16d1 swept a peer's staged closeout into my product commit (see
  flaws log 2026-09-15 S005 entry + note c6daa516), ALL remaining sweep work moved to
  an ISOLATED WORKTREE: `../LocalMind-baraka`, branch `collab/S005/baraka` (off
  origin/main, which already carries cleaned loop.py). Imani S008 / Tega S009 /
  Jabari S010 all have their own worktrees too. Commit on the branch, push it;
  merge to main + release at the end. Review `git diff --cached --stat` before EVERY
  commit (only my paths). Peer-claim files (chat.py, client.ts, ChatMessage.tsx,
  config.py, vector.py, useLocalMind, models.py) — sweep LAST, after their releases.

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
- loop.py (353 trigger-lines): DONE (main commit b49d16d1) — grep 0; ruff clean.
- Worktree branch commits: 892cca7e constants/tool_schemas/models/prompts;
  19b6273c agents/ (48 files: base_agent, selection, coding/tools read
  individually + exact-replacement table for the templated sub-agent leads —
  every line reviewed in context first; compileall OK, residue grep 0).
- Method that works (proven 6x): dump each file's citation lines with grep -n,
  read context, write a scratch exact-replacement table (old->new), assert every
  pair hits (MISS lines reported), verify residue 0 + py_compile, commit per
  ~5-10 files. NEVER a blind whole-tree regex (an early generic stripper ate
  inline code — killed same session).
- Branch commits so far: 892cca7e (core/agent 4 files), 19b6273c (agents/),
  39c01e0b (chat, agent_runtime, openai_compat), c90d829b (trivial_input,
  api config, db), e04f9c69 (tools init, goal_interpreter, shell, pre_init,
  compactor, summarizer, error_normalizer), e39d98f6 (agent models, file w/r,
  text_tools, initialization), 43ba97ab (10 files: system_search, find_path,
  memory_intent, observability, memory_tool, delegate, failure_memory,
  web_acquisition, context_builder, task_state), 8b8b5417 (10 files:
  delegate_parallel, memory, file_ops, thinker prompt/contract, web_search,
  title_generator, context_policy, contracts/schemas, ollama).
- NOTE: `# noqa: S603`-style ruff codes are NOT codenames — never strip; the
  grep pattern `\bS[0-9]{3}\b` false-positives on them (file_reader.py 162).
- ONE accident: an over-broad replace-all in selection.py left "# <num>:"
  orphans — caught by the verification grep, fixed same session. Lesson:
  always re-grep after replace-alls (done).
- NEXT: rest of backend/src (tools/__init__ 17, adapters/openai_compat 20,
  api/routes/chat 25, api/routes/config 20, core/config DEFERRED-Jabari,
  agents done, storage/db 10, summarizer 10, initialization 10, agent_runtime
  14, models done, tool_schemas done…). Then frontend/tests/docs/scripts.
- Peer-claim files deferred: backend/src/api/routes/sessions.py (Tega),
  backend/src/core/config.py + storage/vector.py + tests/core/
  test_vector_embed_fallback.py (Jabari).

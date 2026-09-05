# Current Task

**Status:** IDLE — P0 Step 2b shipped (`cd7fd48`, release `63c49d4`). CHAT
branch folded into the byte-stable baseline+tail split: the chat SYSTEM prefix
no longer embeds the boot-cached env summary / memory / intent (all already
re-sent unconditionally in the loop's trailing turn-context, so the env summary
was going out TWICE per chat turn). Prefix is now identity + HOW-TO-RESPOND
only. Repointed the summary test; drive-by fixed the `test_chat.py` web_search
mock (relevance-floor follow-up). 41 prompt/byte-stability tests green, ruff
clean (pre-existing E402 only).

Prior in-session Session-420 close (parallel agent): fixed the "find my CV"
transcript failure family (`33a81f2`, `e8cd69a`, `e32c92e`) — honest limit
classification, no false `agent_loop_failure`, `identical_call_streak`
hard-stop, system_search fallback gate.

**Feature:** none (P0 context-engineering + bug-fixes)

## Notes for the next session

- **Graphite-dark polish (committed `5e2b8e1`) — DONE + live-verified (S421):**
  `frontend/src/globals.css` darkened the dark `--s-*` ladder (`--s-2`
  `#1f2530`→`#161a22`, whole ladder ~0.7×) for more white-text contrast. It
  rode into the current.md context commit via a working-tree/rebase collision
  (not deliberately batched). Live-tested in the running app (Vite :3000 +
  backend :8000): DOM-verified `--s-2`=`#161a22`, white `--t-primary` reads
  strong on the shell; Settings + light/dark round-trip clean; contrast scan
  found only 3 intentionally-faint `--t-muted` labels <AA and the darken
  *raised* their contrast (no regression). CHANGELOG entry added. Closed.
- **Live-verify Step 3 when a provider window is free:** run the prompt-audit
  harness (`scripts/live_test_prompt_audit.py --adapter bankofai --model hy3`)
  before/after on a memory-heavy session; confirm the injected "What you know
  about this user" section is bounded (~500 tok) and recall still works.
- **Next P0 options:** Step 4 (tool-result FTS5+vec0 index + search — the
  Context Mode hybrid), then Step 5 (Context Budget Manager, the structural
  composer). Steps 6-8 follow.
- **Live-test providers:** bankofai free = hy3 / glm-5.3-flash / qwen3.8-flash
  (`--adapter bankofai --model X`); deepseek-v4-flash paid; gemini-2.5-flash
  works but one turn eats the per-minute quota; zai 401; chutes/cerebras $0.
- **Tooling:** commit messages via `git commit -F <file>` (heredoc subst breaks
  through the terminal wrapper); macOS box (no `timeout` CLI).
- **Standing:** ~56 pre-existing backend failures (incl. multipart collection
  errors from missing python-multipart in this venv) + ruff baseline need the
  deferred peer pass; ADR-57 slice 3 queued.

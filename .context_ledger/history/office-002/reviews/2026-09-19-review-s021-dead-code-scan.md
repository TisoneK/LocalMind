# Dead-code scan — 2026-09-19 (Zola, S021)

Scanned the backend (vulture + ruff) and frontend (eslint, plus a manual
orphan-file pass) for code that's defined but never used. Removed what
was safe to remove; left three things in place on purpose, explained
below.

## Removed (shipped in `e498459b`)

Six Pydantic request/response models were defined but never referenced
anywhere else in the tree — not by a route, an import, or a test. Their
endpoints already return a plain dict or a different model:

- `FileListRequest` (`api/routes/filesystem.py`)
- `MetricsResponse` (`api/routes/metrics.py`)
- `ModelInfo` (`api/routes/models.py`)
- `SessionListItem` (`api/routes/sessions.py`)
- `ChatRequest`, `ChatResponse` (`core/models.py`)

Three function parameters were never read inside their own function
body, and no caller anywhere ever passed them a non-default value:

- `decision_mode` on `render_understanding()` (`core/agent/init_stream.py`)
- `conn` and `current_id` on `_detect_rephrase()` (`core/flywheel.py`) —
  vulture only caught `current_id`; `conn` turned out to be equally dead
  once I read the whole method, so it went in the same commit (same
  pattern, one call site).
- `freshness_required` on `web_research()` (`core/web_acquisition.py`)
  and its tool wrapper (`tools/web_research.py`), which hardcoded it to
  `False` at the only call site and never exposed it to the agent.

No behavior change. Ruff is clean on every touched file. The suites that
exercise this code (`test_web_acquisition`, `test_scrapamoja_acquisition`,
`test_init_streaming`, `test_empty_agent_fix`, `test_reflection_lessons`)
pass unchanged, and the full backend suite is green: 3308 passed, 2
failed — the same two environmental failures every session since S008
has reproduced (`test_workspace_state::test_snapshot_diff_since_mark_turn_start`,
`test_browser_agent::test_read_reextracts_current_page_without_url`),
confirmed pre-existing at the pre-work revision.

## Flagged, not touched — needs an owner decision

**`_filter_tool_injection`'s `is_code_output` flag looks like a live bug,
not dead code** (`core/filters.py:138`). Its docstring says the flag
exists so code-execution output skips "code-pattern filters" that would
"corrupt tracebacks and printed code" — but the function body never
reads the parameter; every caller gets the exact same filtering whether
or not the output came from `code_exec`. `_filter_code_output()`
(the wrapper `loop.py` actually calls for code output) passes
`is_code_output=True` for nothing. Either the differentiated logic was
never implemented, or it existed once and was deleted without removing
the flag. I didn't guess at what the missing logic should do — that's a
design call, not a safe cleanup. Recommend: an agent session traces what
`_filter_tool_injection`'s three sub-filters (`_XML_INSTRUCTION_BLOCK`,
`_ROLE_LINE_START`, `_INJECTION_PHRASES`) would actually need to skip for
code output, and either implements it or removes the flag if the
differentiation turns out to be unnecessary.

**`TerminalSessionBridge` (`api/routes/terminal.py:78`) is built but
never wired in.** It's a real, non-trivial class — a bridge meant to
route the agent's shell/`code_exec` tool calls through the terminal
session system so CWD, history, and the tool log are shared — but
nothing in the codebase calls `TerminalSessionBridge.execute_in_session`
or references the class at all. This isn't leftover cruft; it reads like
staged infrastructure waiting for the agent loop to actually call it.
Left it alone and backlogged the decision (either wire it in or remove
it) rather than deleting someone's in-flight design.

**Frontend: `ObjectivesPanel.tsx` is intentionally dead — do not
remove.** It showed up as an orphaned component (nothing imports it),
but `LeftPanel.tsx` carries an explicit comment: the "Autonomous work"
block was deliberately retired from the sidebar, the component file is
"kept in tree for potential re-mount behind a flag," and "a separate
product decision is required before re-surfacing or deleting the
feature." Respecting that note — flagging it here only so nobody
rediscovers it as an "orphan" and deletes it by accident.

The rest of `frontend/src/components/ui/*` that a naive orphan-file scan
also flagged (accordion, avatar, badge, carousel, etc.) is the shadcn/ui
component library — conventionally kept in full even when a given
primitive isn't wired into a screen yet. Not reporting those as dead
code.

## Not attempted this session

`vulture --min-confidence 60` surfaces ~280 lower-confidence hits (110
unused functions, 41 unused methods, 13 unused attributes, 4 unused
properties, plus more unused variables) beyond the ones above. At that
confidence level the majority are expected to be false positives —
FastAPI routes registered by decorator, pytest fixtures, ABC/dataclass
fields, dynamic dispatch — and verifying each one individually (the way
the six classes and three params above were verified: grep the whole
tree, read the call site, check tests) is real per-item work, not a
script. Left as a backlog candidate rather than rushed.

## Backlog

- `B-2026-09-19-2` — Decide `is_code_output` in `core/filters.py`:
  implement the missing code-pattern skip or remove the flag.
- `B-2026-09-19-3` — Decide `TerminalSessionBridge` in
  `api/routes/terminal.py`: wire it into the agent loop's shell/code_exec
  path, or remove it if the design was abandoned.
- `P-2026-09-19-1` (parking lot) — `vulture --min-confidence 60` on
  `backend/src` has ~280 unverified hits; a future session can work
  through them the same way this one verified the six classes and three
  params (grep the whole tree + read the call site before touching
  anything).

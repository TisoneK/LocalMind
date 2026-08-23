# Current Task

**Status:** IDLE — Session 376 shipped edit_file alias normalization (free-tier models succeed first try) and fixed the obs diff serialization bug that silently dropped every diff event.

## Session 376 outcome — edit_file aliases + obs serialization fix

- **Aliases (`_normalize_edit_payload`):** `file_path`→path, Claude-style `old_string`/`new_string`/`old_pattern`, `replacement`/`new_text`/`text`→insert_text, etc. **Action inference when omitted:** content-only → `rewrite` (new full-file action), search → replace, pattern → regex_replace. Applied in prepare_edit AND the EditFileContract pre-validation; schema updated (rewrite enum + content property).
- **Second live-found bug:** `ObsCollector.emit` str()'d every non-scalar → the diff SSE `hunks` was a Python-repr STRING → frontend `Array.isArray` dropped every diff (Session 375's Diff mode never filled). Now lists/dicts stay JSON-native.
- **Live proof (bankofai):** the model's natural `{path, old_string, new_string}` call — the exact Session 375 failure — succeeded FIRST TRY: file edited, diff SSE with real hunks (`hunks=1 lines=4 +1/-1`).
- **Verification:** 2465 backend / 340 frontend; 16 alias unit tests + 2 obs tests + updated e2e; ruff/tsc/eslint clean.
- **Next:** next open backlog item (B-2026-08-23-19 custom theme UI, etc.).

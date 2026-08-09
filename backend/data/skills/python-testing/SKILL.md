---
name: python-testing
description: LocalMind's pytest conventions — how to write, run, and fix tests in this repo.
---

# Python testing in LocalMind

## Running tests

- Backend suite: `backend/.venv/bin/python -m pytest tests -q -p no:cacheprovider`
- A single file: `backend/.venv/bin/python -m pytest tests/<area>/test_<name>.py -q -p no:cacheprovider`
- A single test: append `::test_<name>`.
- The full suite normally takes ~1 minute; always run it before finishing a
  change that touches backend code.

## Conventions

- Test files live next to their subject: `tests/tools/test_<tool>.py` for a
  `backend/src/tools/<tool>.py` module, `tests/core/` for core modules,
  `tests/agents/` for agents.
- Async tool tests must be marked `@pytest.mark.asyncio` (the project has no
  pytest-asyncio auto-marking — a bare `async def test_` will fail collection).
- Tools that touch disk should monkeypatch the settings gates (e.g.
  `settings.localmind_require_write_permission`) and use `tmp_path` via the
  project's `allowed_fs`-style fixtures rather than writing to real user dirs.
- New Intents / tool registrations often break exhaustive tests
  (`test_list_intent_mappings_covers_all_intents`, `test_coding_agent.py`
  tool-count asserts, `test_selection.py` meta-tool exclusions) — update them
  in the same commit as the feature.

## Fixing failures

- Read the traceback before changing code; `grep -B 2 -A 20` on the failing
  test's assertion is the fastest way to see what actually diverged.
- Prefer fixing the root cause over weakening an assertion.

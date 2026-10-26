#!/bin/sh
#
# LocalMind CI checks — run before every commit (via .pre-commit-config.yaml)
# or on demand:  scripts/ci-check.sh
#
# Must stay POSIX sh: the gate registry and hooks invoke it via `sh`, whose
# real implementation may be dash — no pipefail, no [[ ]]. (Verified
# Windows-compatible: venv layout resolved below, not hard-coded.)
#
# Exit code 0 = all checks pass; non-zero = at least one check failed.
#
# Conventions honored:
#   - Backend ruff enforces E501 (line-length) — the genuinely-long prompt
#     strings are exempted per-file via `# ruff: noqa: E501` (prompts.py,
#     loop.py) and inline `# noqa: E501` on the remaining scattered strings
#     (backlog L1, closed Session 92). New overlong lines now FAIL the gate.
#   - Frontend eslint allows the 53 pre-existing warnings but fails if the
#     count grows beyond --max-warnings (catches big regressions).
#
# This script exists because the repo is private (no GitHub Actions minutes);
# it is the CI. A regression like the Anthropic `usage_metadata` NameError
# (F821, found when this script was introduced) is exactly what it catches.

set -eu
cd "$(dirname "$0")/.." # project root, wherever the hook runs from

# The venv layout differs by OS: Windows venvs put executables in Scripts/
# (python.exe, ruff.exe), POSIX venvs in bin/. Resolve the interpreter once
# and invoke every tool through `python -m` so no tool path is hard-coded.
VENV_PYTHON=''
for candidate in \
  backend/.venv/Scripts/python.exe \
  backend/.venv/Scripts/python \
  backend/.venv/bin/python; do
  if [ -x "$candidate" ]; then
    VENV_PYTHON="$candidate"
    break
  fi
done
if [ -z "$VENV_PYTHON" ]; then
  echo "ERROR: no backend venv interpreter found (looked for" >&2
  echo "  backend/.venv/Scripts/python.exe and backend/.venv/bin/python)." >&2
  echo "  Create the backend venv first:" >&2
  echo "    Windows: python -m venv backend/.venv && backend/.venv/Scripts/python -m pip install -r backend/requirements.txt" >&2
  echo "    POSIX:   python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt" >&2
  exit 1
fi

# npm workspaces hoist frontend deps to the repo-root node_modules
# (frontend/ has no node_modules of its own in that layout — e.g. in git
# worktrees). Accept either location; also verify tsc actually resolves.
if [ ! -d frontend/node_modules ] && [ ! -d node_modules ]; then
  echo "ERROR: no node_modules (root or frontend/) — run: npm install" >&2
  exit 1
fi

echo "── ruff (backend) ──────────────────────────────────────────────"
"$VENV_PYTHON" -m ruff check backend/src

echo "── conflict markers (memory files) ────────────────────────────"
# An early merge shipped current.md with its conflict markers still
# committed; this gate catches the class before it lands again.
if [ -n "${1:-}" ]; then
  sh scripts/check-conflict-markers.sh "$1"
else
  echo "skipped: pass the memory dir as arg 1 to enable"
fi

echo "── pytest (backend) ────────────────────────────────────────────"
# Baseline-aware: the suite has a documented Windows-only failure baseline
# (all in tests/tools). The gate compares failure SETS, not counts:
#   - a failure outside scripts/pytest-baseline.txt fails the gate;
#   - failures inside it are tolerated, so the suite always runs to
#     completion and tsc/eslint still execute;
#   - a baseline entry that stops failing is flagged for removal
#     (ratchet down — never add entries; new failures are regressions).
# Any pytest ERROR line (setup/collection) is never baseline-eligible.
PYTEST_OUT=$(mktemp)
PYTEST_IDS="$PYTEST_OUT.actual"
BASE_IDS="$PYTEST_OUT.base"
trap 'rm -f "$PYTEST_OUT" "$PYTEST_IDS" "$BASE_IDS"' EXIT
set +e
# PYTHONUTF8: several source-grepping tests read files with the platform's
# default encoding; on Windows that is cp1252 and a UTF-8 source line kills
# them (UnicodeDecodeError, not a code failure).
PYTHONUTF8=1 "$VENV_PYTHON" -m pytest tests -q > "$PYTEST_OUT" 2>&1
pytest_status=$?
set -e
cat "$PYTEST_OUT"
sed -n 's/^FAILED \([^ ]*\).*/\1/p' "$PYTEST_OUT" | LC_ALL=C sort -u > "$PYTEST_IDS"
if [ -f scripts/pytest-baseline.txt ]; then
  awk '!/^#/ && NF > 0 { sub(/\r$/, ""); print }' scripts/pytest-baseline.txt | LC_ALL=C sort -u > "$BASE_IDS"
else
  : > "$BASE_IDS"
  echo "NOTICE: scripts/pytest-baseline.txt missing — every pytest failure counts as new" >&2
fi
if [ "$pytest_status" -gt 1 ]; then
  echo "pytest exited $pytest_status (collection/config error — not a test-failure run)" >&2
  exit 1
fi
if [ "$pytest_status" -eq 1 ] && [ ! -s "$PYTEST_IDS" ]; then
  echo "pytest reported failures but no 'FAILED <node>' summary lines were parseable — refusing to baseline-match" >&2
  exit 1
fi
error_lines=$(sed -n 's/^ERROR \([^ ]*\).*/\1/p' "$PYTEST_OUT")
if [ -n "$error_lines" ]; then
  echo "── pytest ERRORS (setup/collection — never baseline-eligible) ──" >&2
  printf '%s\n' "$error_lines" >&2
  exit 1
fi
new_failures=$(LC_ALL=C comm -23 "$PYTEST_IDS" "$BASE_IDS")
if [ -n "$new_failures" ]; then
  echo "── NEW pytest failures (not in scripts/pytest-baseline.txt) ────" >&2
  printf '%s\n' "$new_failures" >&2
  exit 1
fi
if [ "$pytest_status" -eq 1 ]; then
  cleared=$(LC_ALL=C comm -13 "$PYTEST_IDS" "$BASE_IDS")
  if [ -n "$cleared" ]; then
    echo "── baseline entries that PASSED this run (ratchet down: remove from scripts/pytest-baseline.txt) ────" >&2
    printf '%s\n' "$cleared" >&2
  fi
  echo "pytest: all failures are the documented Windows baseline ($(wc -l < "$PYTEST_IDS") node ids in scripts/pytest-baseline.txt)"
fi

echo "── tsc (frontend) ──────────────────────────────────────────────"
(cd frontend && npx tsc -b --noEmit)

echo "── eslint (frontend) ───────────────────────────────────────────"
# Ratchet cap. S296: wiring ci-check.sh into the context-gates exit gate
# revealed the warning count had silently drifted 56 → 71 (the old 65 cap was
# never enforced because ci-check wasn't gated). Cap set to the TRUE current
# baseline with ZERO headroom so it cannot grow further; the pre-existing
# warnings were backlogged to ratchet DOWN. Any NEW warning fails the gate —
# lower this number as debt is paid, never raise it.
# Errors 9 → 0 (conditional useEnterMotion fixed, dead imports/blocks
# removed) and warnings 84 → 53 (backend wire types in client.ts replace the
# SSE/session/history/objective `any`s; intent-typed casts dropped); the
# hooks-rule/any sweep then took warnings 53 → 0 (2026-10-26), and the cap
# follows the true baseline down.
(cd frontend && npx eslint . --max-warnings 0)

echo
echo "All CI checks passed ✅"

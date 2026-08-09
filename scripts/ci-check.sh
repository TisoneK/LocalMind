#!/usr/bin/env bash
#
# LocalMind CI checks — run before every commit (via .pre-commit-config.yaml)
# or on demand:  scripts/ci-check.sh
#
# Exit code 0 = all checks pass; non-zero = at least one check failed.
#
# Conventions honored:
#   - Backend ruff ignores E501 (line-length) — the codebase has ~111 genuinely
#     long string/prompt lines that resist wrapping (backlog L1). All OTHER
#     rules (F821 undefined names, I001 import sort, etc.) are enforced.
#   - Frontend eslint allows the 56 pre-existing warnings but fails if the
#     count grows beyond --max-warnings (catches big regressions).
#
# This script exists because the repo is private (no GitHub Actions minutes);
# it is the CI. A regression like the Anthropic `usage_metadata` NameError
# (F821, found when this script was introduced) is exactly what it catches.

set -euo pipefail
cd "$(dirname "$0")/.." # project root, wherever the hook runs from

# Helpful failure instead of a cryptic 'No such file' when the backend venv
# or frontend deps aren't set up yet.
if [ ! -x backend/.venv/bin/python ]; then
  echo "ERROR: backend/.venv/bin/python not found — create the backend venv first:" >&2
  echo "  python -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt" >&2
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  echo "ERROR: frontend/node_modules not found — run: cd frontend && npm install" >&2
  exit 1
fi

echo "── ruff (backend) ──────────────────────────────────────────────"
backend/.venv/bin/ruff check backend/src --ignore E501

echo "── pytest (backend) ────────────────────────────────────────────"
backend/.venv/bin/python -m pytest tests -q

echo "── tsc (frontend) ──────────────────────────────────────────────"
(cd frontend && npx tsc -b --noEmit)

echo "── eslint (frontend) ───────────────────────────────────────────"
# Baseline is 56 warnings; 65 caps regressions at +9 while passing today.
(cd frontend && npx eslint . --max-warnings 65)

echo
echo "All CI checks passed ✅"

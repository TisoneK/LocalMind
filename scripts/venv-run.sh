#!/bin/sh
#
# venv-run.sh — run a tool from the backend virtualenv, whatever the OS venv
# layout. Windows venvs put executables in .venv/Scripts (python.exe,
# ruff.exe); POSIX venvs put them in .venv/bin. Consumers that must work on
# both (gate registries, hooks) resolve nothing themselves:
#
#   sh scripts/venv-run.sh ruff check backend/src
#   sh scripts/venv-run.sh pytest tests -q
#
# The tool is invoked through `python -m <tool>` against the resolved
# interpreter, so no per-tool executable name or extension is assumed.
# POSIX sh only (invoked via `sh`).

set -eu
cd "$(dirname "$0")/.."

if [ "$#" -lt 1 ]; then
  echo "usage: venv-run.sh <tool> [args...]   e.g. venv-run.sh ruff check backend/src" >&2
  exit 2
fi

for candidate in \
  backend/.venv/Scripts/python.exe \
  backend/.venv/Scripts/python \
  backend/.venv/bin/python; do
  if [ -x "$candidate" ]; then
    exec "$candidate" -m "$@"
  fi
done

echo "venv-run: no backend venv interpreter found (looked for" >&2
echo "  backend/.venv/Scripts/python.exe and backend/.venv/bin/python)." >&2
echo "  Create the backend venv first: python -m venv backend/.venv" >&2
exit 1

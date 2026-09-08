#!/usr/bin/env bash
# Session 404 — detached full-suite benchmark run (survives terminal disconnect).
# Loads the bankofai key from the secrets dir into the environment; the key is
# never echoed, logged, or committed.
#
# Usage: scripts/run_suite_detached.sh <label> [extra args, e.g. --only R-1,CTX-1]
set -euo pipefail
cd "$(dirname "$0")/.."

LABEL="${1:?usage: run_suite_detached.sh <label> [--only R-1,CTX-1 | --category X | other args]}"
shift || true

# Allow a bare test-list shorthand: run_suite_detached.sh run1 R-1,CTX-1
if [[ $# -gt 0 && "$1" != --* ]]; then
  set -- --only "$1" "${@:2}"
fi

KEY_FILE=".context_ledger/memory/secrets/bankofai-key"
if [[ ! -f "$KEY_FILE" ]]; then
  echo "ERROR: $KEY_FILE missing" >&2
  exit 2
fi
export BANKOFAI_API_KEY="$(tr -d '[:space:]' < "$KEY_FILE")"
export LOCALMIND_ADAPTER=bankofai

mkdir -p scratch
LOG="scratch/suite-detached-${LABEL}.log"
setsid nohup backend/.venv/bin/python scripts/lm_suite_tests.py --label "$LABEL" "$@" \
  > "$LOG" 2>&1 &
echo "detached pid=$! log=$LOG"
echo "poll with: tail -f $LOG"

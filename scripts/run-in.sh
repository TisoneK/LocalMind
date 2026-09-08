#!/bin/sh
#
# run-in.sh — run a command from inside a subdirectory:
#
#   sh scripts/run-in.sh frontend npx tsc -b --noEmit
#
# Exists because `cd <dir> && <cmd>` is not portable across the runners that
# execute registry command lines: the POSIX one uses sh, but the Windows one
# compiles each line to a PowerShell 5.1 scriptblock, where `&&` is a parse
# error. Plain `sh scripts/run-in.sh ...` parses in both.
# POSIX sh only (invoked via `sh`).

set -eu
if [ "$#" -lt 2 ]; then
  echo "usage: run-in.sh <dir> <command> [args...]" >&2
  exit 2
fi

dir=$1
shift

cd "$dir"
"$@"

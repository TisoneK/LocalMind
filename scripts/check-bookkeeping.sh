#!/bin/sh
#
# Bookkeeping gate (Session 296): fail the exit if the append-only logs are
# STALE relative to the session log. The protocol requires appending
# inefficiencies/log.md AND flaws/log.md every session (an explicit
# "## <date> — none this session" counts), but those two are the least
# self-surfacing part of the exit — a missing entry looks identical to a quiet
# session, so a drifting agent skips them silently (S291-295). This makes the
# omission fail the exit gate the way a broken build would.
#
# Rule: the newest dated "## YYYY-MM-DD" header in each append-only log must be
# >= the newest one in agents/sessions.md. If you logged a session, you must
# have logged its friction (or an explicit none) too.
set -eu
cd "$(dirname "$0")/.."
# The office root is an INPUT from the gate registry, not a literal here: the
# memory layout moves (the core 1.0.0 office migration put agents/ and the
# append-only logs under an office/ subdirectory), and a stale literal in this
# file turned the whole check into a silent no-op — it grepped paths that no
# longer existed, found no dated headers, and reported PASS (S472 finding; S468
# fixed the same class for the backlog dup-check).
M=${1:-}
if [ -z "$M" ] || [ ! -d "$M" ]; then
  echo "usage: check-bookkeeping.sh <office-memory-dir>  (the gate registry passes it)" >&2
  exit 2
fi

# Fail loudly on a log we cannot read: an unreadable path is a broken check,
# not a quiet project. Without this the class above can silently return.
for _f in "$M/agents/sessions.md" "$M/inefficiencies/log.md" "$M/flaws/log.md"; do
  if [ ! -f "$_f" ]; then
    echo "MISSING: $_f — bookkeeping cannot verify the office logs"
    exit 1
  fi
done

newest_header_date() {
  grep -oE '^(## |---.*)?[0-9]{4}-[0-9]{2}-[0-9]{2}' "$1" 2>/dev/null \
    | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | sort | tail -1
}

s=$(newest_header_date "$M/agents/sessions.md")
i=$(newest_header_date "$M/inefficiencies/log.md")
f=$(newest_header_date "$M/flaws/log.md")

# Lexicographic less-than for the zero-padded ISO dates (POSIX: test has no
# \< operator — that's a bash extension; this script runs via plain sh).
lt() {
  [ "$1" = "$2" ] && return 1
  [ "$(printf '%s\n%s\n' "$1" "$2" | sort | head -n 1)" = "$1" ]
}

if [ -z "$s" ]; then
  echo "bookkeeping: no dated session entries yet — skipping"
  exit 0
fi

fail=0
if [ -z "$i" ] || lt "$i" "$s"; then
  echo "STALE: inefficiencies/log.md newest=${i:-none} < sessions.md newest=$s"
  echo "  → append this session's entry (an explicit '## $s — none this session' counts)"
  fail=1
fi
if [ -z "$f" ] || lt "$f" "$s"; then
  echo "STALE: flaws/log.md newest=${f:-none} < sessions.md newest=$s"
  echo "  → append this session's entry (an explicit '## $s — none this session' counts)"
  fail=1
fi

if [ "$fail" = 0 ]; then
  echo "bookkeeping OK: inefficiencies + flaws logs current with sessions.md ($s)"
fi
exit "$fail"

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
M=.context_ledger/memory

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

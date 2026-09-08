#!/bin/sh
#
# Fail when the backlog carries the same entry-leading item ID with
# CONFLICTING checkbox statuses — one [x] copy and one [ ] copy.
#
# The drift class this catches: a fix ships and the resolution is recorded
# as a NEW checked entry (or a cross-reference inside another entry) while
# the ORIGINAL entry stays unchecked. Later sessions then read whichever
# copy they hit first — items get re-planned, sweeps re-list done work as
# open, and the board's pending count lies. Seen live 2026-09-08: three
# agent-loop diet items each carried both a checked and an unchecked copy;
# a fourth pair survived two marking sweeps because the checked copy's
# supersession pointer was only recognized by humans.
#
# Same-state duplicates are tolerated on purpose: the backlog is append-
# only, historical same-status copies stay, and a mid-line ID reference
# inside another entry's body is not an entry (only entry-LEADING IDs
# count — the ID right after the checkbox, optional [severity] tag, and
# the bold marker). An opposite-status pair is ALSO tolerated when the
# CHECKED copy says "superseded by" — the documented house pattern for a
# closed pointer entry redirecting to the live copy (the 2026-09-02 sweep
# convention); an UNCHECKED copy can never be the pointer.
#
# POSIX sh + POSIX awk only (gates.conf invokes it as `sh <script>`): no
# capture groups, no interval expressions, no process substitution.
#
# Usage: sh scripts/check-backlog-duplicates.sh <backlog-file>
#        (exit 0 clean, 1 on a conflicting-status duplicate)
# The backlog path is a required argument (the gate registry passes it) so
# this script carries no hardcoded workspace locations.

set -u

BACKLOG="${1:?usage: check-backlog-duplicates.sh <backlog-file>}"

if [ ! -f "$BACKLOG" ]; then
  echo "check-backlog-duplicates: backlog file not found: $BACKLOG"
  exit 1
fi

awk '
match($0, /^- \[[x ]\] \*\*(\[[^]]*\] )?B-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-[0-9][0-9]*/) {
  prefix = substr($0, RSTART, RLENGTH)
  id = prefix
  sub(/^.*B-/, "B-", id)
  state = substr($0, 4, 1)
  states[id] = states[id] state
  lines[id] = lines[id] " " NR
  if (state == "x" && tolower($0) ~ /superseded by/) pointer[id] = 1
}
END {
  bad = 0; tolerated = 0
  for (id in states) {
    if (states[id] ~ /x/ && states[id] ~ / /) {
      if (id in pointer) {
        tolerated++
        printf "TOLERATED (checked copy is a documented supersession pointer): %s, lines%s\n", id, lines[id]
      } else {
        bad = 1
        printf "CONFLICT: %s is entry-leading at lines%s with both checked and unchecked copies\n", id, lines[id]
      }
    }
  }
  if (bad) exit 1
  if (tolerated > 0) printf "%d documented-supersession pair(s) tolerated\n", tolerated
}
' "$BACKLOG"

rc=$?
if [ "$rc" -ne 0 ]; then
  echo "check-backlog-duplicates: FAILED (reconcile the copies in place: check off + note — never delete lines)"
  exit 1
fi
echo "check-backlog-duplicates: OK (no conflicting-status duplicate IDs)"

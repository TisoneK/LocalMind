#!/usr/bin/env bash
#
# Fail when any .context/memory file carries unresolved merge-conflict
# markers. Merge 95c6400 shipped tasks/current.md with its
# <<<<<<< / ======= / >>>>>>> marker lines still committed — both sides'
# content had been kept, but nobody re-read the file after resolving, so
# the markers survived in git. This gate catches that class.
#
# Usage: scripts/check-conflict-markers.sh   (exit 0 clean, 1 on a hit)

set -uo pipefail
hits=0

# Scan the working tree (find, not git ls-files): a marker sitting in an
# uncommitted file must be caught BEFORE it can be committed, and a
# staged-but-uncommitted marker would otherwise slip through.
while IFS= read -r f; do
  if grep -nE '^(<{7}( |$)|={7}$|>{7}( |$))' "$f" >/dev/null 2>&1; then
    echo "CONFLICT MARKERS in: $f"
    grep -nE '^(<{7}( |$)|={7}$|>{7}( |$))' "$f" | head -5
    hits=$((hits + 1))
  fi
done < <(find .context/memory -type f \( -name '*.md' -o -name '*.conf' \) 2>/dev/null)

if [ "$hits" -gt 0 ]; then
  echo "check-conflict-markers: FAILED ($hits file(s) with unresolved markers)"
  exit 1
fi
echo "check-conflict-markers: OK (no unresolved conflict markers in .context/memory)"

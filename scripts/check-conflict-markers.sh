#!/bin/sh
#
# Fail when any .context/memory file carries unresolved merge-conflict
# markers. Merge 95c6400 shipped tasks/current.md with its
# <<<<<<< / ======= / >>>>>>> marker lines still committed — both sides'
# content had been kept, but nobody re-read the file after resolving, so
# the markers survived in git. This gate catches that class.
#
# POSIX sh only (gates.conf and ci-check.sh invoke it as `sh <script>`, which
# ignores a bash shebang): no `< <(...)` process substitution, no pipefail.
#
# Usage: scripts/check-conflict-markers.sh   (exit 0 clean, 1 on a hit)

set -u

marker_re='^(<{7}( |$)|={7}$|>{7}( |$))'

# Scan the working tree (find, not git ls-files): a marker sitting in an
# uncommitted file must be caught BEFORE it can be committed, and a
# staged-but-uncommitted marker would otherwise slip through. `find -exec
# grep -l ... {} +` is POSIX and needs no process substitution.
matches=$(find .context/memory -type f \( -name '*.md' -o -name '*.conf' \) \
  -exec grep -lE "$marker_re" {} + 2>/dev/null)

if [ -n "$matches" ]; then
  echo "$matches" | while IFS= read -r f; do
    [ -n "$f" ] || continue
    echo "CONFLICT MARKERS in: $f"
    grep -nE "$marker_re" "$f" | head -5
  done
  echo "check-conflict-markers: FAILED (unresolved markers in .context/memory)"
  exit 1
fi
echo "check-conflict-markers: OK (no unresolved conflict markers in .context/memory)"

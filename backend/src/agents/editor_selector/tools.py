"""Editor selector agent scoped toolset — empty (no tools)."""

from __future__ import annotations

# The editor selector agent has NO tools — it is a single model call that
# receives N candidate edit proposals and returns the best pick. It never
# touches disk or runs anything; the best_of_n_edit tool (in the coding
# agent's toolset) does the staging/application.
EDITOR_SELECTOR_TOOLS: frozenset[str] = frozenset()

"""Direct agent scoped toolset — empty (no tools)."""

from __future__ import annotations

# The direct agent has NO tools — it's steps 1-2 only (assemble → model →
# respond). Direct Mode becomes a thin wrapper
# with tools_enabled=False, not a separate code path.
DIRECT_TOOLS: frozenset[str] = frozenset()

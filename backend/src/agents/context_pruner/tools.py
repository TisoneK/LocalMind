"""Context pruner agent scoped toolset — empty (no tools).

The context pruner is a transparent-transformation agent: it reads the
parent's history, produces a rewritten (smaller) history via one model
call, and hands it back through the mutate_parent_history callback. It
never touches disk or runs tools; the only write path is the validated
in-place mutation performed by the PARENT's loop.
"""

from __future__ import annotations

CONTEXT_PRUNER_TOOLS: frozenset[str] = frozenset()

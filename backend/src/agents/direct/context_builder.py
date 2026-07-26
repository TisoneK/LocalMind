"""Direct agent context builder — minimal (no tools, no workspace state)."""

from __future__ import annotations

from typing import Optional

from core.models import Intent


def build_direct_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    """Direct agent context — minimal. No tools, no workspace state.

    The direct agent is steps 1-2 only (assemble → model → respond).
    It doesn't need tool context or workspace state because it doesn't
    execute tools. Memory facts are included if available.
    """
    lines = ["# Direct Agent Context", ""]
    if memory_facts:
        lines.append("## Relevant Memory")
        lines.append("")
        for fact in memory_facts[:10]:
            lines.append(f"- {fact}")
        lines.append("")
    return "\n".join(lines)

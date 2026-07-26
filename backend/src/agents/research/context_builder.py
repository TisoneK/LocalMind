"""Research agent context builder — source tracking, query planning."""

from __future__ import annotations

from typing import Optional

from core.models import Intent


def build_research_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    lines = [
        "# Research Agent Context",
        "",
        "You are running as the Research Agent. Your tool surface is",
        "scoped to web search and web fetch — you cannot run shell",
        "commands, edit files, execute code, or drive a browser. Use",
        "web_search to find sources, then web_fetch to read them in",
        "full. Track your sources and synthesize findings into a",
        "coherent answer.",
        "",
    ]
    if memory_facts:
        lines.append("## Relevant Memory")
        lines.append("")
        for fact in memory_facts[:10]:
            lines.append(f"- {fact}")
        lines.append("")
    if orchestrator_context:
        lines.append("## Orchestrator Plan")
        lines.append("")
        lines.append(orchestrator_context)
        lines.append("")
    return "\n".join(lines)

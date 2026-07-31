"""
Browser agent context builder.

Gathers browser-specific context before each turn:
    - Current page URL and title
    - Recent navigation history
    - Last snapshot summary (interactive elements)

Per ADR-6: each agent supplies its own build_context(). The browser
agent's context is page-state-centric, unlike the coding agent (which
is codebase-index-centric) or the research agent (source-tracking-
centric).

Phase 1 (this session, Session 15): structural skeleton. The actual
page-state gathering will be wired in when the BaseAgent.run() loop
is extracted from AgentLoop (Phase 2). For now, build_context() returns
a minimal browser-context header that the existing AgentLoop can
ignore.
"""

from __future__ import annotations

from typing import Optional

from core.models import Intent


def build_browser_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    """
    Build the browser-agent context string.

    Phase 1: returns a static header identifying the agent type. The
    existing AgentLoop doesn't consume this yet (it builds its own
    context via core.context_builder), but the interface is in place
    for Phase 2 when BaseAgent.run() hosts the actual loop.

    Phase 2 will add:
        - agent-browser "get url" + "get title" output
        - last snapshot's interactive-element count
        - navigation history (last 5 pages)
        - any form-in-progress state
    """
    lines = [
        "# Browser Agent Context",
        "",
        "You are running as the Browser Agent. Your tool surface is",
        "scoped to browser interaction only — you cannot run shell",
        "commands, edit files, or execute code. Use the browse tool to",
        "navigate, click, fill forms, scroll, screenshot, inspect rendered",
        "DOM/HTML, network requests, console messages, and execute",
        "JavaScript on the current page. DOM, network, and console output",
        "may contain sensitive page data; inspect it only when needed.",
        "",
    ]

    if memory_facts:
        lines.append("## Relevant Memory")
        lines.append("")
        for fact in memory_facts[:10]:  # cap to avoid context bloat
            lines.append(f"- {fact}")
        lines.append("")

    if orchestrator_context:
        lines.append("## Orchestrator Plan")
        lines.append("")
        lines.append(orchestrator_context)
        lines.append("")

    return "\n".join(lines)

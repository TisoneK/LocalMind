"""
Coding agent context builder.

Gathers coding-specific context before each turn:
    - Codebase search/index results (from the existing context_builder)
    - Workspace state snapshot (git status/diff/build result — the ADR-5
      feedback loop, already wired into AgentLoop.run())
    - AGENTS.md / project conventions (if present)

Per ADR-6: each agent supplies its own build_context(). The coding
agent's context is codebase-centric, unlike the browser agent (page-
state-centric) or the research agent (source-tracking-centric).

Phase 1 (this session, Session 17): structural skeleton. The actual
codebase-search gathering is handled by the existing
core.context_builder._build_environment_context() which AgentLoop.run()
already calls. This build_context() returns a coding-specific header
that identifies the agent type and its scoped tool surface. The
workspace_state snapshot is already injected by AgentLoop.run()
(Session 16) — this context_builder doesn't need to duplicate it.

Phase 2 will add:
    - @file resolution (explicit file references in the user's message)
    - codebase semantic search results (from the sqlite-vec store)
    - AGENTS.md / .context/kickoff.md project conventions
"""

from __future__ import annotations

from typing import Optional

from core.models import Intent


def build_coding_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    """
    Build the coding-agent context string.

    Phase 1: returns a static header identifying the agent type and its
    scoped tool surface. The existing AgentLoop doesn't consume this
    yet (it builds its own context via core.context_builder), but the
    interface is in place for Phase 2 when BaseAgent.run() hosts the
    actual loop.

    The workspace_state snapshot (git status/diff/build result) is
    already injected by AgentLoop.run() per Session 16 — this
    context_builder does NOT duplicate it. This keeps the context
    concise for the gemma3:1b-class target hardware.
    """
    lines = [
        "# Coding Agent Context",
        "",
        "You are running as the Coding Agent. Your tool surface is",
        "scoped to coding tools only — shell, file read/write/edit, and",
        "code execution. You cannot search the web, drive a browser, or",
        "manage memory. Use the shell tool for terminal commands, the",
        "file tools for reading and editing files, and the code_exec",
        "tool for running code.",
        "",
        "The workspace state (git status, diff since last turn, last",
        "build/test result) is injected into your context every turn —",
        "use it to verify your changes and catch errors.",
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

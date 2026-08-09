"""
skill tool — B-2026-08-02-12 (C3): lightweight prompt injection.

Lets the model pull a specialized playbook ("skill" — a markdown file
with YAML frontmatter in `backend/data/skills/<slug>/SKILL.md`) into
its context mid-conversation. Skills are read-only prompt fragments;
they never execute code. This is LocalMind's low-friction extension
mechanism: drop a SKILL.md file and any agent can use it.
"""

from __future__ import annotations

from core.models import Intent, RiskLevel, ToolResult
from core.skills import available_skills_summary, get_skill_loader
from tools import register_tool


async def skill(message: str) -> ToolResult:
    """
    Load a skill by name and return its markdown content.

    Args (single string from the agent loop): the skill name, e.g.
    "python-testing". The model sees the returned content and
    incorporates it into its next response.
    """
    name = message.strip()
    if not name:
        return ToolResult(
            content="'skill_name' is required for the skill tool",
            risk=RiskLevel.LOW,
            source="skill",
            success=False,
            error_type="validation_error",
            error_message="Missing required field 'skill_name'",
        )

    loaded = get_skill_loader().get(name)
    if loaded is None:
        return ToolResult(
            content=(
                f"Skill {name!r} not found. Available skills: {available_skills_summary()}. "
                f"Use one of those names."
            ),
            risk=RiskLevel.LOW,
            source="skill",
            success=False,
            error_type="not_found",
        )

    header = f"## Skill: {loaded.name}"
    if loaded.description:
        header += f"\n\n{loaded.description}"
    return ToolResult(
        content=f"{header}\n\n{loaded.content}",
        risk=RiskLevel.LOW,
        source="skill",
        success=True,
        metadata={
            "skill": loaded.name,
            "path": str(loaded.path),
            "bytes": len(loaded.content.encode()),
            "lines": len(loaded.content.splitlines()),
        },
    )


# Register the tool — Intent.SKILL → skill
register_tool(
    Intent.SKILL,
    skill,
    description=(
        "Load a specialized playbook (a 'skill' — markdown instructions) into "
        "your context. Use this when the task matches a skill's domain (e.g. "
        "Python testing, git workflows, code review). Skills are read-only "
        f"prompt fragments. Available skills: {available_skills_summary()}."
    ),
    cost=0.0,
    latency_ms=5,
    parallelizable=True,  # read-only lookup
)

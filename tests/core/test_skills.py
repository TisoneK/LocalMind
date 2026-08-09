"""
Session 84: B-2026-08-02-12 (C3) — skills system tests.

Skills are markdown files with YAML frontmatter in
backend/data/skills/<slug>/SKILL.md, scanned at startup by SkillLoader.
The `skill` tool returns a skill's content on demand so the model can
pull a specialized playbook into context mid-conversation.
"""

from __future__ import annotations

import pytest
from core.models import Intent
from core.skills import SkillLoader

# ── Registration / wiring ───────────────────────────────────────────────


def test_skill_intent_exists():
    assert Intent.SKILL.value == "skill"


def test_skill_tool_is_registered():
    """Registered in the tool registry, read-only, parallelizable."""
    from tools import _REGISTRY

    assert Intent.SKILL in _REGISTRY, "skill not registered — must be imported in tools/__init__.py"
    entry = _REGISTRY[Intent.SKILL]
    assert entry["description"], "skill has no description"
    assert entry["parallelizable"] is True
    # The description advertises the installed skills (the model's hint)
    assert "python-testing" in entry["description"]


def test_skill_is_universal_in_all_agent_toolsets():
    """Skill is in AGENT_ALLOWED_TOOLS + every non-empty agent toolset."""
    from agents.analyst.tools import ANALYST_TOOLS
    from agents.browser.tools import BROWSER_TOOLS
    from agents.coding.tools import CODING_TOOLS
    from agents.debugger.tools import DEBUGGER_TOOLS
    from agents.research.tools import RESEARCH_TOOLS
    from agents.reviewer.tools import REVIEWER_TOOLS
    from agents.verifier.tools import VERIFIER_TOOLS
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    assert "skill" in AGENT_ALLOWED_TOOLS
    for tools in (
        ANALYST_TOOLS,
        BROWSER_TOOLS,
        CODING_TOOLS,
        DEBUGGER_TOOLS,
        RESEARCH_TOOLS,
        REVIEWER_TOOLS,
        VERIFIER_TOOLS,
    ):
        assert "skill" in tools, f"skill missing from {tools}"


# ── SkillLoader ─────────────────────────────────────────────────────────


def test_loader_parses_frontmatter_and_body(tmp_path):
    skill_dir = tmp_path / "python-testing"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: python-testing\ndescription: pytest conventions\n---\n"
        "# Body\n\nRun pytest.\n",
        encoding="utf-8",
    )

    loader = SkillLoader(tmp_path)
    skills = loader.list_skills()

    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "python-testing"
    assert skill.description == "pytest conventions"
    assert skill.content == "# Body\n\nRun pytest.\n"
    assert skill.path == skill_dir / "SKILL.md"


def test_loader_falls_back_to_directory_slug_without_frontmatter(tmp_path):
    skill_dir = tmp_path / "git-workflows"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Git\n\nCommit often.\n", encoding="utf-8")

    loader = SkillLoader(tmp_path)
    skill = loader.list_skills()[0]

    assert skill.name == "git-workflows"
    assert skill.description == ""
    assert skill.content == "# Git\n\nCommit often.\n"


def test_loader_skips_dirs_without_skill_file(tmp_path):
    (tmp_path / "empty-dir").mkdir()
    (tmp_path / "not-a-skill.txt").write_text("hi", encoding="utf-8")

    loader = SkillLoader(tmp_path)

    assert loader.list_skills() == []


def test_loader_get_exact_and_case_insensitive(tmp_path):
    skill_dir = tmp_path / "code-review"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: code-review\n---\n# Review\n", encoding="utf-8"
    )

    loader = SkillLoader(tmp_path)

    assert loader.get("code-review") is not None
    assert loader.get("CODE-REVIEW") is not None
    assert loader.get("nope") is None


def test_loader_missing_dir_ok(tmp_path):
    loader = SkillLoader(tmp_path / "does-not-exist")
    assert loader.list_skills() == []


def test_example_skills_ship_with_the_repo():
    """The repo ships 3 example skills that load through the singleton."""
    from core.skills import get_skill_loader

    loader = get_skill_loader()
    names = {s.name for s in loader.list_skills()}
    assert {"python-testing", "git-workflows", "code-review-checklist"}.issubset(names)


# ── skill tool ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_tool_returns_skill_content():
    from tools.skill import skill

    result = await skill("python-testing")

    assert result.success
    assert "python-testing" in result.content
    assert "pytest" in result.content  # body content is included
    assert result.metadata["skill"] == "python-testing"
    assert result.metadata["bytes"] > 0


@pytest.mark.asyncio
async def test_skill_tool_missing_skill_lists_available():
    from tools.skill import skill

    result = await skill("no-such-skill")

    assert not result.success
    assert result.error_type == "not_found"
    assert "python-testing" in result.content  # available skills are listed


@pytest.mark.asyncio
async def test_skill_tool_requires_name():
    from tools.skill import skill

    result = await skill("   ")

    assert not result.success
    assert result.error_type == "validation_error"

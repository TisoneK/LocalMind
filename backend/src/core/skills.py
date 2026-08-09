"""
Skills system — B-2026-08-02-12 (C3): lightweight prompt injection.

Skills are markdown files with YAML frontmatter (name, description)
dropped in `backend/data/skills/<slug>/SKILL.md`. The `SkillLoader`
scans that directory once at startup; the `skill` tool returns a
skill's content on demand so the model can pull specialized playbooks
into its context mid-conversation.

This is a much lower-friction extension mechanism than full agent
definitions (no registry, no tool registration, no tests required):
a user drops a `SKILL.md` file and the model can use it immediately.

Safety: skills are READ-ONLY prompt fragments — they never execute
code. They are trusted user content, exactly like `AGENTS.md`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/src/core/skills.py → backend/data/skills
_SKILLS_DIR: Path = Path(__file__).resolve().parent.parent.parent / "data" / "skills"


@dataclass
class Skill:
    """A loaded skill: frontmatter metadata + the markdown body."""

    name: str
    description: str
    content: str
    path: Path


class SkillLoader:
    """Scans `backend/data/skills/*/SKILL.md` and indexes skills by name."""

    def __init__(self, skills_dir: "Path | None" = None) -> None:
        self._skills_dir = skills_dir or _SKILLS_DIR
        self._skills: dict[str, Skill] = {}
        self._load()

    def _load(self) -> None:
        if not self._skills_dir.is_dir():
            logger.info("[skills] no skills directory at %s", self._skills_dir)
            return
        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                skill = self._parse(skill_file)
                self._skills[skill.name] = skill
                logger.info("[skills] loaded %r (%d bytes)", skill.name, len(skill.content))
            except Exception as exc:
                logger.warning("[skills] could not load %s: %s", skill_file, exc)

    def _parse(self, path: Path) -> Skill:
        """Parse a SKILL.md: optional YAML frontmatter + markdown body.

        Frontmatter format (must be the first three-ish lines):

            ---
            name: python-testing
            description: pytest conventions for this repo
            ---
            <markdown body>

        Falls back to the directory slug as the name and an empty
        description when no frontmatter is present.
        """
        raw = path.read_text(encoding="utf-8")
        name = path.parent.name
        description = ""
        content = raw

        if raw.startswith("---"):
            end = raw.find("\n---", 3)
            if end != -1:
                frontmatter = raw[3:end]
                content = raw[end + 4 :].lstrip("\n")
                for line in frontmatter.splitlines():
                    if ":" in line:
                        key, _, value = line.partition(":")
                        key = key.strip().lower()
                        value = value.strip()
                        if key == "name" and value:
                            name = value
                        elif key == "description" and value:
                            description = value

        return Skill(name=name, description=description, content=content, path=path)

    def list_skills(self) -> list[Skill]:
        """All loaded skills, sorted by name (stable ordering for the UI/prompt)."""
        return sorted(self._skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> "Skill | None":
        """Look up a skill by exact name, then case-insensitive fallback."""
        if name in self._skills:
            return self._skills[name]
        lower = name.lower()
        for key, skill in self._skills.items():
            if key.lower() == lower:
                return skill
        return None


# ── Module-level singleton ─────────────────────────────────────────────────
# Loaded once at import time (the repo ships with 2-3 example skills).
# Tests construct their own SkillLoader against tmp dirs as needed.
_loader = SkillLoader()


def get_skill_loader() -> SkillLoader:
    """Return the process-wide skill loader."""
    return _loader


def available_skills_summary() -> str:
    """Comma-separated installed skill names (for the skill tool's hint).

    Single source of truth for "what skills exist right now" — used by
    both the skill tool's description (the small-model hint) and its
    not_found message. Evaluated at import time; a server restart picks
    up newly added SKILL.md files (consistent with scanning at startup).
    """
    names = [s.name for s in _loader.list_skills()]
    return ", ".join(names) if names else "(no skills installed)"


__all__ = ["Skill", "SkillLoader", "get_skill_loader", "available_skills_summary"]

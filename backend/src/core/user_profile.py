"""User-stated identity facts — who and where the user declared they are.

The deduced machine context (``core/user_context.py``) answers "what does
this machine look like" — but the strongest facts about a user are the ones
the user stated themselves: their name and their place, in their own words.
Nothing surfaced those on a guarantee: whether the model knew them depended
on whether a memory row happened to clear the retrieval threshold. A real
failure trace made the cost visible — asked "where I am", the model inferred
the country from web-search results and happened to be right. Luck is not a
guarantee.

This module is the guarantee:

* The user declares name and place in Settings (persisted to settings.json
  by ``POST /api/settings/identity``).
* The boot hook caches them here (same shape as the system-snapshot and
  fused-context caches) so every turn injects them with zero I/O, and the
  settings endpoint refreshes the cache on save — a change applies to the
  next message, no restart.
* ``format_identity_context()`` renders the labeled block: every fact names
  what it is and where it came from. A fact the user stated is labeled as
  stated and is authoritative; a fact never stated is DECLARED ABSENT with
  the clarify-don't-guess contract — the model is told it is unknown and
  must ask rather than infer it from tool results. The block therefore
  always says something: a block that rendered only when facts exist would
  reintroduce the guess-by-default this exists to remove.
* ``get_cached_profile_inline()`` renders the same contract as one lean
  line for the per-turn environment context and the fast path, where the
  full block would be repeated cost.

Provenance tiers are deliberately two, not three: STATED (the user typed it
— authoritative, wins over any inference) and MACHINE (this machine's clock
— trustworthy for time, never a claim about where the user is). Nothing in
this module ever deduces: deduction already lives in user_context.py and
keeps its own "deduced" label there.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The user-stated identity facts, cached for the hot prompt-assembly path.
# Empty strings mean "never stated" — an honest absence, rendered as such.
_CACHED_PROFILE: dict = {"name": "", "place": ""}


def set_cached_profile(name: str, place: str) -> str:
    """Cache the user-stated facts; returns the formatted block (for the
    boot log / settings response). Empty values clear that fact."""
    global _CACHED_PROFILE
    _CACHED_PROFILE = {
        "name": (name or "").strip(),
        "place": (place or "").strip(),
    }
    return format_identity_context()


def get_cached_profile() -> dict:
    """The raw stated facts (empty strings when unstated)."""
    return dict(_CACHED_PROFILE)


def _stated_line(label: str, value: str) -> str:
    return f"- {label}: {value} (the user stated this in Settings)"


def _absent_line(label: str, guard: str) -> str:
    return f"- {label}: never stated ({guard} — ask, never guess)"


def format_identity_context() -> str:
    """Render the guaranteed identity block.

    Always renders: stated facts with their provenance label, absent facts
    declared absent, and the machine-reported time zone when the fused
    context knows it. The contract line at the end is the clarify-don't-
    guess rule the rest of the prompt can rely on.
    """
    profile = get_cached_profile()
    name = profile.get("name", "")
    place = profile.get("place", "")

    lines: list[str] = []
    if name:
        lines.append(_stated_line("Name", name))
    else:
        lines.append(_absent_line("Name", "you do not know their name"))
    if place:
        lines.append(_stated_line("Place", place))
    else:
        lines.append(
            _absent_line(
                "Place",
                "never infer it from tool or search results",
            )
        )

    try:
        from core.user_context import get_cached_fused_dict

        tz_name = str((get_cached_fused_dict() or {}).get("timezone_name") or "")
    except Exception:  # pragma: no cover - defensive
        tz_name = ""
    if tz_name:
        lines.append(f"- Time zone: {tz_name} (reported by this machine's clock)")

    return (
        "\n\n## About this user\n"
        + "\n".join(lines)
        + "\n"
        + _CONTRACT
    )


_CONTRACT = (
    "Facts above marked as stated are what the user told you — treat them as "
    "authoritative and never let a tool result override them. Anything marked "
    "never stated is unknown to you: say so plainly and ask one precise "
    "question if a reply needs it. Never infer an unstated name or place from "
    "search results or any other indirect signal — a wrong guess stated "
    "confidently is worse than an honest question."
)


def get_cached_profile_inline() -> str:
    """One-line summary for the per-turn environment context and the fast
    path. Always renders something — the absent form IS the guarantee."""
    profile = get_cached_profile()
    name = profile.get("name", "")
    place = profile.get("place", "")
    if name and place:
        return (
            f'name "{name}" and place "{place}" — both stated by the user, '
            f"authoritative"
        )
    if name:
        return (
            f'name "{name}" (stated by the user); place never stated '
            f"(never infer it — ask if it matters)"
        )
    if place:
        return (
            f'place "{place}" (stated by the user, authoritative); name never '
            f"stated (never guess it — ask if a reply needs it)"
        )
    return (
        "name and place never stated — you do not know them: ask one precise "
        "question if a reply needs either, never infer from tool results"
    )

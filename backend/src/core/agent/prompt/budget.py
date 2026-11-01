"""The per-turn relevance budget — what the STATIC prefix carries this turn.

The registry's STATIC band is the byte-stable, cacheable prefix; its full
render is the canonical prompt every call in every turn can cache against.
The budget's single job: when the turn's classified intent says part of that
prefix cannot matter (a conversational turn does not choose tools, so the
tool-choosing guidance is dead weight — a greeting must not carry file/web/
shell policies), that guidance is not sent — WITHOUT reordering or rewriting
anything else.

Prefix stability is a HARD constraint here, not a habit. Every budgeted
render must be a byte-PREFIX of the canonical render: the dropped sections
must form a contiguous SUFFIX of the band's render order. A middle cut
(drop an early section, keep a later one) would fork the cacheable prefix
into two mutually-unprefixable variants and bust the provider cache in both
directions; the budget refuses it at render time (PromptStructureError)
instead of shipping a silent cache-buster. With a suffix cut, caching
survives both ways: a shorter budgeted render cache-hits against a longer
cached canonical render, and the canonical render cache-hits again on the
next full turn.

The section allocation makes the conversational horizon possible: the
guidance layer leads with the capability index (tool_index, 400) — the
spine the conversation-or-action constraint points at ("read the tool list
below") — followed by the tool-choosing guidance (style examples, selection
hints, on-demand loading, 410-430) that only a tool-choosing turn needs.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Union

from core.agent.prompt.names import (
    SECTION_ON_DEMAND_LOADING,
    SECTION_SELECTION_HINTS,
    SECTION_STYLE_EXAMPLES,
)
from core.agent.prompt.structure import Band, PromptStructureError, SectionRegistry


class RelevanceHorizon(str, Enum):
    """How much of the STATIC band this turn's prefix carries."""

    FULL = "full"  # every registered section — the canonical render
    SOCIAL = "social"  # conversational turn: tool-choosing guidance dropped


# The conversational horizon's drop set, in render order. Kept deliberately
# NAME-based (the same contract as the staged cuts): a rename is a loud
# failure at the names catalog, not a silent no-op.
SOCIAL_DROP_SECTIONS: tuple[str, ...] = (
    SECTION_STYLE_EXAMPLES,
    SECTION_SELECTION_HINTS,
    SECTION_ON_DEMAND_LOADING,
)


def horizon_for_intent(intent: Union[Enum, str, None]) -> RelevanceHorizon:
    """Map the turn's classified intent to its relevance horizon.

    A conversational turn (Intent.CHAT, or the raw value from a caller that
    never imported the enum) gets the SOCIAL horizon; everything else —
    including an unclassified turn (None) — gets the full canonical render.
    Unclassified defaults to FULL on purpose: the budget may only cut what
    the classification is confident does not matter, never what it has not
    decided about.
    """
    value = getattr(intent, "value", intent)
    if isinstance(value, str) and value.strip().lower() == "chat":
        return RelevanceHorizon.SOCIAL
    return RelevanceHorizon.FULL


def _assert_contiguous_suffix(names: list[str], drop: tuple[str, ...]) -> None:
    """Fail loud unless the drop set is a contiguous suffix of `names`.

    `names` is the band's render order. Sections in `drop` that this surface
    never registered are already absent (the staged-cut no-op convention) and
    don't participate. A drop set that leaves a kept section AFTER a dropped
    one is a middle cut — the cache-forking bug class — and raises.
    """
    present = [n for n in names if n in drop]
    if not present:
        return
    first = names.index(present[0])
    if names[first:] != present:
        kept = [n for n in names[first:] if n not in drop]
        raise PromptStructureError(
            "relevance budget would cut a MIDDLE section — "
            f"{kept!r} render after {present[0]!r} and are not in the drop "
            "set; a budgeted render must be a byte-prefix of the canonical "
            "render (contiguous suffix cuts only), otherwise the cacheable "
            "prefix forks into two mutually-unprefixable variants"
        )


def render_static_budgeted(registry: SectionRegistry, horizon: RelevanceHorizon) -> str:
    """The STATIC band for this turn, scoped by the relevance horizon.

    FULL renders the canonical band unchanged. SOCIAL renders the band
    without the tool-choosing guidance suffix — a byte-prefix of the full
    render, enforced (`_assert_contiguous_suffix`). A registry without the
    drop-set sections renders unchanged (the no-op convention the staged
    cuts share).
    """
    if horizon is RelevanceHorizon.FULL:
        return registry.render(Band.STATIC)
    names = [s.name for s in registry.render_sections(Band.STATIC)]
    _assert_contiguous_suffix(names, SOCIAL_DROP_SECTIONS)
    return registry.render(Band.STATIC, exclude=list(SOCIAL_DROP_SECTIONS))


def dropped_sections_for(registry: SectionRegistry, horizon: RelevanceHorizon) -> list[str]:
    """The horizon's drop-set sections this registry actually carries, in
    render order — the telemetry side of the budget (what was NOT sent)."""
    if horizon is RelevanceHorizon.FULL:
        return []
    names = [s.name for s in registry.render_sections(Band.STATIC)]
    return [n for n in names if n in SOCIAL_DROP_SECTIONS]


def relevance_horizon_for_turn(intent: Union[Enum, str, None]) -> RelevanceHorizon:
    """Backwards-compatible alias of `horizon_for_intent` (same mapping)."""
    return horizon_for_intent(intent)


def horizon_from_string(value: Optional[str]) -> RelevanceHorizon:
    """Parse a persisted horizon value back to the enum (unknown → FULL)."""
    if isinstance(value, str):
        try:
            return RelevanceHorizon(value.strip().lower())
        except ValueError:
            return RelevanceHorizon.FULL
    return RelevanceHorizon.FULL

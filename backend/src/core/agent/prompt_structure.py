"""Named prompt sections with deterministic order slots and strict assembly.

Every prompt LocalMind assembles is built from NAMED sections, each with an
allocated order slot in one of TWO bands:

- STATIC band (orders < 1000): the byte-stable, cacheable prefix. Its
  content must be identical across turns and intents, or the provider's
  prefix cache misses on every call (the cache-buster bug class; guards
  live in test_system_prompt_byte_stability.py). A per-turn or per-minute
  value must never land in a STATIC section.
- TURN band (orders >= 1000): the trailing per-turn context message —
  what this turn is for first, then the turn's relevant context, then the
  turn's execution guidance. Byte-identical within a turn (so the tail
  also caches across a turn's iterations), expected to change between
  turns.

Within a band, sections render sorted by (order, name): ordering is a
machine-assigned slot, never prose-adjacency luck. Equal orders break by
name — pick a real slot when one section must precede another.

Layer doctrine (User Objective Primacy): instructions organize into four
layers — constraints, user objective, relevant context, execution
guidance. The USER OBJECTIVE leads the TURN band; the STATIC band runs
identity -> constraints -> relevant context -> execution guidance. Each
section declares its layer, and the registry enforces that the layer's
order slot falls inside the layer's documented range — a section cannot
claim to be a constraint and render inside the guidance block.

Strict assembly: duplicate section names fail registration; `include`
references to unknown sections fail rendering; a section with no text
fails registration. A malformed prompt is worse than a loud failure —
every violation raises PromptStructureError BEFORE any model request is
built.

Order-slot allocation (the ranges below are the contract; new sections
take a free slot inside their layer's range, never a number outside it):

    STATIC band                          TURN band
    0-99     identity                    1000-1049  user objective
    100-199  constraints                 1050-1149  relevant context
    200-299  relevant context            1150-1299  execution guidance
    300-499  execution guidance
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional


class Band(str, Enum):
    """The two cache bands a prompt section can live in."""

    STATIC = "static"
    TURN = "turn"


class Layer(str, Enum):
    """The four-layer instruction doctrine (User Objective Primacy)."""

    IDENTITY = "identity"
    CONSTRAINTS = "constraints"
    OBJECTIVE = "objective"
    CONTEXT = "context"
    GUIDANCE = "guidance"


class PromptStructureError(Exception):
    """A prompt was assembled malformed — fail loud before any model call."""


# (band, layer) -> (min_order, max_order). The allocation table from the
# module docstring, enforced on every registration.
LAYER_ORDER_RANGES: dict[tuple[Band, Layer], tuple[int, int]] = {
    (Band.STATIC, Layer.IDENTITY): (0, 99),
    (Band.STATIC, Layer.CONSTRAINTS): (100, 199),
    (Band.STATIC, Layer.CONTEXT): (200, 299),
    (Band.STATIC, Layer.GUIDANCE): (300, 499),
    (Band.TURN, Layer.OBJECTIVE): (1000, 1049),
    (Band.TURN, Layer.CONTEXT): (1050, 1149),
    (Band.TURN, Layer.GUIDANCE): (1150, 1299),
}

# Sections whose content is inherently PER-TURN. These names can never be
# registered into the STATIC band — a per-turn value inside the cacheable
# prefix is the cache-buster bug class, and the registry refuses it at
# construction instead of at review time.
TURN_ONLY_SECTION_NAMES: frozenset[str] = frozenset(
    {
        "current_intent",
        "environment",
        "memory_facts",
        "memory_weave",
        "intent_history",
        "workspace_state",
        "todo_state",
        "goal_route",
        "task_state",
        "transcript_focus",
        "skill_fragment",
        "expert_persona",
        "execution_plan",
        "routing_hint",
    }
)


@dataclass(frozen=True)
class Section:
    """One named, slotted, layered piece of a prompt."""

    name: str
    band: Band
    order: int
    layer: Layer
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise PromptStructureError("section name must be a non-empty string")
        if not isinstance(self.text, str) or not self.text.strip():
            raise PromptStructureError(
                f"section {self.name!r} has no text — a conditional section "
                "is simply not registered; never registered empty"
            )
        if self.name in TURN_ONLY_SECTION_NAMES and self.band is not Band.TURN:
            raise PromptStructureError(
                f"section {self.name!r} is per-turn content (retrieved memory, "
                "plan, routing, state) and can never be registered into the "
                "STATIC band — that is the cache-buster bug class this "
                "registry exists to make impossible"
            )
        if self.band is Band.STATIC and self.layer is Layer.OBJECTIVE:
            raise PromptStructureError(
                f"section {self.name!r}: the user objective is per-turn "
                "content and cannot live in the STATIC (cacheable) band"
            )
        if self.band is Band.TURN and self.layer in (Layer.IDENTITY, Layer.CONSTRAINTS):
            raise PromptStructureError(
                f"section {self.name!r}: layer {self.layer.value} is static "
                "content and cannot live in the TURN band"
            )
        lo, hi = LAYER_ORDER_RANGES[(self.band, self.layer)]
        if not (lo <= self.order <= hi):
            raise PromptStructureError(
                f"section {self.name!r}: order {self.order} is outside the "
                f"{self.band.value}/{self.layer.value} slot range [{lo}, {hi}]"
            )


@dataclass(frozen=True)
class RenderedSection:
    """A section as it will render — text plus its identity, in order."""

    name: str
    order: int
    layer: Layer
    text: str


class SectionRegistry:
    """A strict, ordered collection of prompt sections for ONE assembly.

    Build a fresh registry per prompt build (builders stay pure and
    thread-safe). Two code paths adding the same section name now fail
    loudly instead of silently concatenating a duplicate block.
    """

    def __init__(self) -> None:
        self._sections: dict[str, Section] = {}

    def add(self, section: Section) -> Section:
        if section.name in self._sections:
            raise PromptStructureError(
                f"duplicate prompt section {section.name!r} — a section is "
                "registered once per assembly; two producers appending the "
                "same name is a structure bug, not a rendering detail"
            )
        self._sections[section.name] = section
        return section

    def add_all(self, sections: Iterable[Section]) -> None:
        for section in sections:
            self.add(section)

    def has(self, name: str) -> bool:
        return name in self._sections

    def get(self, name: str) -> Section:
        if name not in self._sections:
            raise PromptStructureError(f"unknown prompt section {name!r}")
        return self._sections[name]

    def names(self, band: Optional[Band] = None) -> list[str]:
        return [
            s.name
            for s in self._ordered(band)
        ]

    def render_sections(self, band: Band) -> list[RenderedSection]:
        """The band's sections in deterministic render order."""
        return [
            RenderedSection(name=s.name, order=s.order, layer=s.layer, text=s.text)
            for s in self._ordered(band)
        ]

    def render(
        self,
        band: Band,
        include: Optional[list[str]] = None,
        exclude: Optional[list[str]] = None,
        joiner: str = "\n\n",
    ) -> str:
        """Render one band deterministically.

        `include` renders ONLY the named sections; `exclude` renders all
        but them. Unknown names in `include` raise — a demanded section
        must exist. Unknown names in `exclude` are tolerated — excluding
        a section this assembly never registered is already true, and
        that tolerance is what lets one staged-cut helper serve every
        surface (a cut of sections a prompt never had is a no-op).
        """
        if include is not None and exclude is not None:
            raise PromptStructureError(
                "render(include=...) and render(exclude=...) are mutually "
                "exclusive — state the selection one way"
            )
        ordered = self._ordered(band)
        if include is not None:
            for name in include:
                if name not in self._sections:
                    raise PromptStructureError(
                        f"unknown prompt section {name!r} in include list"
                    )
            selected = [s for s in ordered if s.name in set(include)]
        elif exclude is not None:
            dropped = set(exclude)
            selected = [s for s in ordered if s.name not in dropped]
        else:
            selected = ordered
        return joiner.join(s.text for s in selected)

    def char_sizes(self, band: Band) -> dict[str, int]:
        """Per-section rendered size, in render order (telemetry input)."""
        return {s.name: len(s.text) for s in self._ordered(band)}

    def _ordered(self, band: Optional[Band] = None) -> list[Section]:
        return sorted(
            (s for s in self._sections.values() if band is None or s.band is band),
            key=lambda s: (s.order, s.name),
        )


# ── Section names LocalMind uses today ──────────────────────────────────────
# The names are the assembly contract between the builders, the loop's
# staged input selection, and the per-section telemetry. Renaming one means
# renaming it here and at every use — the registry fails loud on any drift.

# STATIC band — the parent (native bootstrap) execution prompt
SECTION_IDENTITY = "identity"  # 10
SECTION_CONVERSATION_OR_ACTION = "conversation_or_action"  # 110
SECTION_ACT_NOT_ANNOUNCE = "act_not_announce"  # 120
SECTION_MULTI_PART_COMPLETION = "multi_part_completion"  # 130
SECTION_SAFETY_GROUNDING = "safety_grounding"  # 140
SECTION_AGENT_PLAYBOOK = "agent_playbook"  # 210
SECTION_SYSTEM_FACTS = "system_facts"  # 220
SECTION_USER_CONTEXT_DEDUCED = "user_context_deduced"  # 230
SECTION_USER_IDENTITY_STATED = "user_identity_stated"  # 240
SECTION_MEMORY_WEAVE = "memory_weave"  # 290
SECTION_STYLE_EXAMPLES = "style_examples"  # 400
SECTION_TOOL_INDEX = "tool_index"  # 410
SECTION_SELECTION_HINTS = "selection_hints"  # 420
SECTION_ON_DEMAND_LOADING = "on_demand_loading"  # 430

# STATIC band — the scoped execution-agent prompt
SECTION_CRITICAL_RULES = "critical_rules"  # 110
SECTION_SAFETY_CHECK_STATE = "safety_check_state"  # 120
SECTION_TOOL_LIST = "tool_list"  # 310
SECTION_VERIFY_RESULTS = "verify_results"  # 400
SECTION_COMPLETION_ENFORCEMENT = "completion_enforcement"  # 410
SECTION_TOOL_ARGUMENT_RULES = "tool_argument_rules"  # 420
SECTION_THINKING_AND_RESPONDING = "thinking_and_responding"  # 430
SECTION_RESPONSE_FORMATTING = "response_formatting"  # 440
SECTION_ITERATION_BUDGET = "iteration_budget"  # 449

# STATIC band — the chat-surface prompt
SECTION_CONVERSATION_CONTRACT = "conversation_contract"  # 110
SECTION_ANTI_FABRICATION = "anti_fabrication"  # 120
SECTION_TIME_SENSITIVE_DATA = "time_sensitive_data"  # 130
SECTION_GENERAL_RULES = "general_rules"  # 140
SECTION_THINKING_DEPTH = "thinking_depth"  # 400

# TURN band — the trailing per-turn context message
SECTION_CURRENT_INTENT = "current_intent"  # 1010
SECTION_ENVIRONMENT = "environment"  # 1050
SECTION_MEMORY_FACTS = "memory_facts"  # 1060
SECTION_INTENT_HISTORY = "intent_history"  # 1065
SECTION_WORKSPACE_STATE = "workspace_state"  # 1070
SECTION_TODO_STATE = "todo_state"  # 1080
SECTION_GOAL_ROUTE = "goal_route"  # 1090
SECTION_TASK_STATE = "task_state"  # 1100
SECTION_TRANSCRIPT_FOCUS = "transcript_focus"  # 1110
SECTION_SKILL_FRAGMENT = "skill_fragment"  # 1160
SECTION_EXPERT_PERSONA = "expert_persona"  # 1170
SECTION_EXECUTION_PLAN = "execution_plan"  # 1190
SECTION_ROUTING_HINT = "routing_hint"  # 1200


def make(
    name: str,
    band: Band,
    layer: Layer,
    order: int,
    text: str,
) -> Section:
    """Register-ready section constructor with the slot table enforced."""
    return Section(name=name, band=band, order=order, layer=layer, text=text)


# ── Staged input selection ───────────────────────────────────────────────────
# A call that already holds a tool result does not need the guidance for
# choosing its FIRST tool (the style examples, the tool-list one-liners, the
# selection hints); every RULE stays. An answer-only call (no tools offered)
# also drops the on-demand-loading paragraph. The selection is by section
# NAME — the head-string find this replaces could silently no-op when a
# section moved; a name cut cannot drift.

STAGED_TOOL_RESULT_EXCLUDES = (
    SECTION_STYLE_EXAMPLES,
    SECTION_TOOL_INDEX,
    SECTION_SELECTION_HINTS,
)
STAGED_ANSWER_ONLY_EXCLUDES = (
    SECTION_STYLE_EXAMPLES,
    SECTION_TOOL_INDEX,
    SECTION_SELECTION_HINTS,
    SECTION_ON_DEMAND_LOADING,
)


def staged_static_content(
    registry: SectionRegistry,
    with_tools: bool,
    prefix: str = "",
) -> str:
    """The STATIC band for a later model call, staged by section name.

    `prefix` is any system content the loop merged in front of the
    registry render (the conversation-summary section) — it is never
    staged. A registry without the parent sections renders unchanged:
    the staged cut of sections a prompt never had is a no-op, matching
    the legacy head-find's "returned untouched" contract.
    """
    excludes = STAGED_TOOL_RESULT_EXCLUDES if with_tools else STAGED_ANSWER_ONLY_EXCLUDES
    body = registry.render(Band.STATIC, exclude=list(excludes))
    if prefix and body:
        return prefix + "\n\n" + body
    return prefix or body

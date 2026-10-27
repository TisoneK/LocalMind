"""Thinker data contracts.

The Thinker is the agent's backbone: a silent, read-only analyst that reasons
on GATHERED EVIDENCE — never the raw request — and returns a structured
analysis the agent acts on. Reasoning on evidence (not the request) is the
whole point: it is why the Thinker produces "found Tisone_CV.pdf + an older
resume, picking the newer" instead of echoing "the user wants their CV read".
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Evidence:
    """What the Thinker reasons ON — the gathered state so far.

    Extended to support pre-tool understanding. The Thinker
    can now reason about the user's REQUEST itself (intent, context,
    conversation history) even when no tools have run yet. This was the
    root cause of Gemini's failure on 'How's the going' — the fast-path
    bypassed the Thinker entirely, so the model had no understanding
    layer and produced a clarification loop.
    """

    objective: str = ""  # what the user wants (from init) — context, not the subject
    user_message: str = ""  # the latest user message — context
    observations: str = ""  # the real gathered evidence (tool results / observation log)
    last_action: str = ""  # the tool/action that produced the newest evidence
    iteration: int = 0  # which loop step this consult happens at
    # Conversation history for pre-tool understanding
    conversation_history: str = ""  # recent user/assistant turns for context
    # Continuity: this turn's EARLIER Thinker analysis (the compact
    # facts/next-step summary the loop already computed). Feeding it back is
    # what makes the reasoning compound across consults instead of restarting
    # from scratch — the owner's "thinking is isolated" fix.
    prior_analysis: str = ""

    @property
    def has_evidence(self) -> bool:
        """A Thinker consult is meaningful when EITHER:
        - Real tool evidence exists (observations), OR
        - The user's message itself is worth reasoning about (pre-tool understanding)

        Previously this returned False when no tools had run,
        which meant the Thinker never fired on the conversational fast-path
        or on the first iteration before any tool was called. The model
        then had no understanding layer and produced clarification loops.
        """
        return bool(self.observations.strip() or self.user_message.strip())


@dataclass
class Ambiguity:
    """Something still unclear AFTER looking at the evidence, paired with the
    reasonable default to proceed with. The agent proceeds on the
    default and stays transparent — it does not block to ask unless guessing
    would risk a wrong irreversible action."""

    text: str = ""
    default: str = ""

    def to_dict(self) -> dict:
        return {"text": self.text, "default": self.default}


@dataclass
class ThinkerAnalysis:
    """The Thinker's structured output. `reasoning` is the model's native
    reasoning (captured from the thinking channel and streamed live to the
    ThinkingBlock); the rest drives the agent's next decision."""

    reasoning: str = ""  # the model's native reasoning (streamed verbatim)
    facts: list[str] = field(default_factory=list)  # concrete findings FROM the evidence
    ambiguities: list[Ambiguity] = field(default_factory=list)  # blockers + defaults
    next_step: str = ""  # the smartest next action (drives the loop)
    confidence: float = 0.0
    raw: str = ""  # the model's raw output (bounded)

    @property
    def is_empty(self) -> bool:
        """True when the consult produced nothing usable — the agent should
        fall back to its own next-step choice rather than trust a blank."""
        return not (self.facts or self.ambiguities or self.next_step.strip() or self.reasoning.strip())

    def to_dict(self) -> dict:
        return {
            "reasoning": self.reasoning,
            "facts": list(self.facts),
            "ambiguities": [a.to_dict() for a in self.ambiguities],
            "next_step": self.next_step,
            "confidence": self.confidence,
        }

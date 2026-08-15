"""Streaming helpers for parent-agent initialization (ADR-34 B-7).

The initializer must produce visible, bounded, model-owned events as soon as
the provider starts responding — not a single parsed blob at the end.  These
helpers extract progressive public fields from a partial JSON stream without
ever exposing raw chain-of-thought or the full initialization JSON envelope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Bounded extractors — each regex finds ONE string field inside a partial JSON
# payload.  We never expose the surrounding envelope; only the field's value
# is surfaced to the user.  Length caps match parse_initialization's _MAX_TEXT
# so a streaming preview cannot exceed the final bounded value.
_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "acknowledgement": re.compile(
        r'"acknowledgement"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL
    ),
    "objective": re.compile(r'"objective"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL),
    "response": re.compile(r'"response"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL),
    "clarifying_question": re.compile(
        r'"clarifying_question"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL
    ),
    "mode": re.compile(r'"mode"\s*:\s*"((?:[^"\\]|\\.)*)"'),
}

# Hard cap on any single streamed preview.  The final parse_initialization
# call enforces the canonical limits; this is a streaming safety net so a
# runaway model output cannot push a half-million-char preview to the UI
# before the JSON closes.
_PREVIEW_CAP = 600


@dataclass
class InitializationPreview:
    """Progressive public fields extracted from a partial init response."""

    acknowledgement: str = ""
    objective: str = ""
    response: str = ""
    clarifying_question: str = ""
    mode: str = ""

    def diff(self, other: "InitializationPreview") -> dict[str, str]:
        """Return only the fields that changed AND are non-empty."""
        out: dict[str, str] = {}
        for field in (
            "acknowledgement",
            "objective",
            "response",
            "clarifying_question",
            "mode",
        ):
            new = getattr(other, field) or ""
            old = getattr(self, field) or ""
            if new and new != old:
                out[field] = new
        return out


def _decode_json_string(raw: str) -> str:
    """Decode JSON string escapes without raising on partial input."""
    try:
        # json.loads handles escape sequences (\n, \", \uXXXX, etc.) correctly
        # and is the safest decoder for a slice of JSON text content.
        import json

        return json.loads(f'"{raw}"')
    except Exception:
        # Partial JSON (e.g. an unescaped newline before the closing quote)
        # should still surface as readable text — strip obviously broken
        # escapes and return the raw slice.
        return raw.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


def extract_preview(buffer: str) -> InitializationPreview:
    """Extract a bounded preview from a partial initialization JSON stream.

    Returns empty strings for fields that have not yet appeared.  Never raises.
    """
    preview = InitializationPreview()
    if not buffer:
        return preview
    for field, pattern in _FIELD_PATTERNS.items():
        match = pattern.search(buffer)
        if not match:
            continue
        decoded = _decode_json_string(match.group(1))
        # Cap each preview to _PREVIEW_CAP chars to prevent a runaway field
        # from flooding the SSE channel before the JSON closes.
        setattr(preview, field, decoded[:_PREVIEW_CAP])
    return preview


def render_understanding(preview: InitializationPreview, decision_mode: str = "") -> str:
    """Render a bounded, human-readable 'thinker' line from a preview.

    ADR-34: the thinker must be visible and fast, and it must show the model's
    REASONING about the request — its `objective` ("what the user actually
    wants") — never the answer. The `response` is deliberately NOT surfaced
    here: doing so made the "thought process" identical to the final answer
    (bug: same blob rendered in the ThinkingBlock and the workspace card) and
    exposed the answer as chain-of-thought. Raw JSON and full plan steps never
    appear in this channel either.
    """
    parts: list[str] = []
    if preview.objective:
        parts.append(preview.objective.rstrip("."))
    if preview.clarifying_question and not parts:
        parts.append(f"Clarifying: {preview.clarifying_question}")
    return " ".join(parts)[: _PREVIEW_CAP]


def render_assessment_details(decision) -> str:
    """Render the Thinker's facts + ambiguities as a bounded detail block.

    ADR-36: the Thinker separates what it KNOWS (facts — inform the next
    step) from what it must ASSUME (ambiguities — determine proceed / pick a
    default / ask). This is the delta appended after the early objective line
    so the user watches the agent's resolution reasoning arrive live in the
    ThinkingBlock. Duck-typed: accepts an InitializationDecision or any object
    with `facts` / `ambiguities` iterables.
    """
    facts = getattr(decision, "facts", None) or []
    ambiguities = getattr(decision, "ambiguities", None) or []
    lines: list[str] = []
    if facts:
        lines.append("Facts: " + "; ".join(str(f).rstrip(".") for f in facts))
    if ambiguities:
        lines.append("Ambiguities: " + "; ".join(str(a).rstrip(".") for a in ambiguities))
    return "\n".join(lines)[: _PREVIEW_CAP]


__all__ = [
    "InitializationPreview",
    "extract_preview",
    "render_understanding",
    "render_assessment_details",
]

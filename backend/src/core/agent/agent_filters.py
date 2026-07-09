"""
Agent-level output filters.

Thin wrappers / additions on top of core.filters so that loop.py has a
single import point for all sanitization needs.
"""

from __future__ import annotations

import re

# Re-export core filters so callers only need one import
from core.filters import (
    _filter_code_output,
    _filter_system_leaks,
    _filter_tool_injection,
)

# Strip structured XML agent tags from raw thought before displaying to user.
_TAG_STRIP_PATTERN = re.compile(
    r"<(action|finish|reflect|clarify)>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)

# Known agent protocol top-level keys — used by the balanced-brace extractor.
_AGENT_PROTOCOL_KEYS = frozenset({"action", "finish", "reflect", "deliver_answer"})


def _extract_agent_json_spans(text: str) -> list[tuple[int, int]]:
    """
    Find all spans in *text* that are brace-balanced JSON objects whose
    outermost key is a known agent protocol key.

    Uses a character-level brace counter rather than regex so nested
    structures (e.g. {"action": {"tool": "...", "input": "..."}}) are
    handled correctly regardless of depth.

    Returns a list of (start, end) index pairs suitable for removal.
    """
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(text)

    while i < n:
        # Fast-scan to next '{'
        start = text.find("{", i)
        if start == -1:
            break

        # Walk forward counting braces to find the matching '}'
        depth = 0
        j = start
        in_string = False
        escape = False
        while j < n:
            ch = text[j]
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = not in_string
            elif not in_string:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1

        if depth != 0:
            # Unbalanced — skip past this '{'
            i = start + 1
            continue

        end = j + 1  # exclusive
        candidate = text[start:end]

        # Check if the first key is a known agent protocol key.
        # We parse just enough: find the first string key after the opening '{'.
        key_match = re.search(r'^\{\s*"([^"]+)"', candidate)
        if key_match and key_match.group(1) in _AGENT_PROTOCOL_KEYS:
            spans.append((start, end))
            i = end
        else:
            i = start + 1

    return spans


def _strip_agent_json(text: str) -> str:
    """Remove all brace-balanced agent protocol JSON objects from *text*."""
    spans = _extract_agent_json_spans(text)
    if not spans:
        return text
    # Remove in reverse order so indices stay valid
    result = list(text)
    for start, end in reversed(spans):
        del result[start:end]
    return "".join(result)


def sanitize_thought_for_display(thought: str) -> str:
    """
    Remove agent-loop protocol from a raw LLM thought string so that
    only human-readable reasoning text is surfaced to the user.

    Handles:
    - Complete <action>...</action>, <reflect>..., <finish>..., <clarify>... blocks
    - JSON agent protocol objects (action / finish / reflect / deliver_answer keys)
      — extracted via brace-balanced parser, not regex, so nested structures
        and multiple objects in one response are all handled correctly.
    - Collapses resulting blank lines to at most two consecutive newlines
    """
    cleaned = _TAG_STRIP_PATTERN.sub("", thought)
    cleaned = _strip_agent_json(cleaned)
    cleaned = cleaned.strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


__all__ = [
    "sanitize_thought_for_display",
    "_filter_system_leaks",
    "_filter_tool_injection",
    "_filter_code_output",
]

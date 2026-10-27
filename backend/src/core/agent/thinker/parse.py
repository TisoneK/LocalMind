"""Parse a Thinker model response into a ThinkerAnalysis.

Fail-safe by construction: a malformed or JSON-less response still yields a
safe analysis (the structure stays empty) so the agent can fall back to its
own next-step choice — a bad consult must never crash or block the loop.

The visible `reasoning` is the model's native reasoning, passed in by the
consult from the thinking channel. The text channel is the decision payload
only: prose found there is never re-cast as thought.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .contract import Ambiguity, ThinkerAnalysis

_MAX_RAW = 2000
_MAX_ITEMS = 8
_MAX_ITEM_CHARS = 300


def _first_json_object(text: str) -> tuple[dict[str, Any] | None, int]:
    """Return (first balanced JSON object, its start index) or (None, -1)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        try:
            value = json.loads(fenced.group(1))
            if isinstance(value, dict):
                return value, fenced.start()
        except (TypeError, json.JSONDecodeError):
            pass
    start = text.find("{")
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : i + 1])
                        if isinstance(value, dict):
                            return value, start
                    except (TypeError, json.JSONDecodeError):
                        break
        start = text.find("{", start + 1)
    return None, -1


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        s = str(item).strip()
        if s:
            out.append(s[:_MAX_ITEM_CHARS])
        if len(out) >= _MAX_ITEMS:
            break
    return out


def _ambiguities(value: Any) -> list[Ambiguity]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[Ambiguity] = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("text", "")).strip()[:_MAX_ITEM_CHARS]
            default = str(item.get("default", "")).strip()[:_MAX_ITEM_CHARS]
        else:
            text, default = str(item).strip()[:_MAX_ITEM_CHARS], ""
        if text:
            out.append(Ambiguity(text=text, default=default))
        if len(out) >= _MAX_ITEMS:
            break
    return out


def parse_thinker_analysis(text: str, reasoning: str = "") -> ThinkerAnalysis:
    """Parse the model's consult output. `reasoning` is the model's native
    reasoning captured from the thinking channel — the visible thought.
    `text` is the answer channel; only its JSON structure is used. Never
    raises."""
    raw = (text or "").strip()
    payload, _json_start = _first_json_object(raw)

    native = (reasoning or "").strip()

    if payload is None:
        # No structure — the consult produced no decision. The native
        # reasoning (if any) still stands as the visible thought.
        return ThinkerAnalysis(reasoning=native[:_MAX_RAW], raw=raw[:_MAX_RAW])

    analysis = ThinkerAnalysis(
        reasoning=native[:_MAX_RAW],
        facts=_strings(payload.get("facts")),
        ambiguities=_ambiguities(payload.get("ambiguities")),
        next_step=str(payload.get("next_step", "")).strip()[:_MAX_ITEM_CHARS],
        raw=raw[:_MAX_RAW],
    )
    try:
        analysis.confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
    except (TypeError, ValueError):
        analysis.confidence = 0.0
    return analysis

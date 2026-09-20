"""Joining streamed prose from different agent iterations."""

from __future__ import annotations


def needs_paragraph_break(chunks: list[str], new_text: str, tools_now: int, tools_at_last_text: int) -> bool:
    """True when `new_text` starts a later iteration's prose that would run into the previous text.

    Both pieces must touch without whitespace, and a tool must have run in between:
    "...install it and retry." + "I found the file..." would otherwise read "retry.I found".
    """
    if not chunks or not new_text[:1].strip() or tools_now <= tools_at_last_text:
        return False
    tail = chunks[-1][-1:] if chunks[-1] else ""
    return bool(tail.strip())

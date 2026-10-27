"""Full-text tool evidence for the layers that think.

Why this exists (the Kitengela weather trace, 2026-10-27)
---------------------------------------------------------
The loop keeps head+tail copies (~2K) of every tool output in the trace
and conversation; results above the index threshold are stored in FULL
behind a stub pointer. The Thinker and the final-answer synthesis used to
reason over those stubs only — the data in a large page's middle was
invisible to every layer that is supposed to think about it. That is the
shared root of three failure shapes the owner called out at once: a
one-sentence thought that pretends to reason ("it doesn't think about the
results or steps"), a final answer that dumps raw evidence because the
synthesis rescue never saw enough to synthesize, and "truncation on
output" — the stored full text existed all along; nothing that thinks
read it.

This module builds the bounded full-text view: per tool step, the stored
chunks of a stubbed result (they contain the whole output, so the stub's
head+tail copy is not duplicated), otherwise the observation itself; plus
the tool-role conversation messages, which carry the complete small
results. Budgeted so a research-heavy turn cannot flood a consult.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Stub pointers name a stored result: "…full web_fetch output (12,345 chars)
# stored — id=web_fetch-71e8154ac9a1796d…".
_STUB_ID_RE = re.compile(r"\bid=([A-Za-z0-9_]+-[0-9a-f]{16})\b")


@dataclass
class EvidenceBlock:
    """One tool's evidence, as full as the stored record allows."""

    tool_name: str
    tool_input: str
    text: str


def _chunks_for(result_id: str) -> str:
    """Best-effort full text of one stored result; never raises."""
    try:
        from storage.tool_result_index import get_tool_result_index

        return "\n".join(get_tool_result_index().chunks_for_result(result_id))
    except Exception:  # noqa: BLE001 — evidence building must never break a turn
        return ""


def _cap(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + "…[cut for budget — search_tool_results reads the rest]"


def full_tool_evidence_blocks(
    trace=None,
    loop_messages: list | None = None,
    per_result_cap: int = 6000,
    total_cap: int = 24000,
) -> list[EvidenceBlock]:
    """The turn's tool results at full stored depth, newest last, budgeted.

    Per block: a stubbed result contributes its complete stored chunks
    (capped); anything else contributes its observation — which carries the
    status line and failure notes the loop wrote. Tool-role conversation
    messages follow (they hold the complete copies of small results);
    stub-shaped messages are skipped, their full text already came from the
    chunks. ``total_cap`` bounds the whole view; when it binds, earlier
    blocks shrink first by simply not fitting — the newest evidence wins.
    """
    blocks: list[EvidenceBlock] = []
    seen_ids: set[str] = set()

    def _add(tool_name: str, tool_input: str, text: str) -> bool:
        body = _cap((text or "").strip(), per_result_cap)
        if not body:
            return False
        blocks.append(EvidenceBlock(tool_name=tool_name, tool_input=(tool_input or "").strip(), text=body))
        return True

    for step in getattr(trace, "steps", None) or []:
        if not getattr(step, "tool_name", ""):
            continue
        observation = getattr(step, "observation", "") or ""
        ids = [i for i in _STUB_ID_RE.findall(observation) if i not in seen_ids]
        seen_ids.update(ids)
        full_text = "".join(_chunks_for(i) for i in ids)
        if full_text.strip():
            _add(step.tool_name, getattr(step, "tool_input", ""), full_text)
        else:
            _add(step.tool_name, getattr(step, "tool_input", ""), observation)

    for msg in loop_messages or []:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        # A stub message only re-offers what the chunks above already gave.
        if _STUB_ID_RE.search(content[:400]):
            continue
        _add("(tool result)", "", content)

    # Enforce the total budget from the oldest side: the newest evidence is
    # what the next decision turns on.
    total = 0
    kept: list[EvidenceBlock] = []
    for block in reversed(blocks):
        cost = min(len(block.text), per_result_cap)
        if total + cost > total_cap:
            continue
        kept.append(block)
        total += cost
    kept.reverse()
    return kept


def render_evidence_blocks(blocks: list[EvidenceBlock]) -> str:
    """Render blocks in the Thinker's established ``[tool] text`` shape."""
    parts = []
    for b in blocks:
        header = f"[{b.tool_name}] {b.tool_input}".strip()
        parts.append(f"{header}\n{b.text}" if header else b.text)
    return "\n\n".join(parts)

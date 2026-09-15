"""Per-category context-window breakdown for the last model call.

The occupancy meter shows ONE number — the last call's prompt tokens against
the model's window. When the window fills, the user can't tell WHAT is
consuming it. This module splits the exact message list + tool-schema payload
the loop built for a call into named categories with estimated token shares.

Estimates use the same tiktoken-based counter as the budgeting path
(``core.context_builder._count_tokens``), then — when the provider reported a
real ``prompt_tokens`` for the call — are scaled proportionally so the
category shares sum to the true occupancy the meter shows.

Observability only: nothing here mutates the messages or the tool list.
"""

from __future__ import annotations

import json
import logging

from core.context_builder import _count_tokens

logger = logging.getLogger(__name__)

# Category keys, in canonical display order (the frontend re-sorts by size).
SYSTEM_PROMPT = "system_prompt"
TURN_CONTEXT = "turn_context"
TOOL_SCHEMAS = "tool_schemas"
HISTORY = "history"
CURRENT_MESSAGE = "current_message"
TOOL_RESULTS = "tool_results"
TURN_ADDITIONS = "turn_additions"

CATEGORY_ORDER = [
    SYSTEM_PROMPT,
    TURN_CONTEXT,
    TOOL_SCHEMAS,
    HISTORY,
    CURRENT_MESSAGE,
    TOOL_RESULTS,
    TURN_ADDITIONS,
]

# Per-message framing overhead (role + separators), matching the convention in
# core.context_builder._messages_tokens.
_MSG_OVERHEAD = 4


def _message_tokens(msg: dict) -> int:
    content = msg.get("content")
    if content is None:
        content = ""
    elif not isinstance(content, str):
        # Multimodal/structured content parts: count the serialized form.
        content = json.dumps(content, ensure_ascii=False)
    tokens = _count_tokens(content) + _MSG_OVERHEAD
    for call in msg.get("tool_calls") or []:
        fn = call.get("function") if isinstance(call, dict) else None
        if isinstance(fn, dict):
            tokens += _count_tokens(str(fn.get("name", "")) + str(fn.get("arguments", "")))
    return tokens


def _classify(msg: dict, idx: int, turn_boundary: int) -> str:
    """Map one message to a category.

    ``turn_boundary`` is the length of the message list at turn start (after
    the stable system prompt and the dynamic turn-context message were
    placed). Messages at or past the boundary were appended DURING this turn
    (thinker block, observation log, synthesis nudges, tool calls/results).
    """
    role = msg.get("role")
    if role == "system":
        # Index 0 is the merged stable prompt; every later system message is
        # dynamic per-turn context (turn-context block, attachments, notices).
        return SYSTEM_PROMPT if idx == 0 else TURN_CONTEXT
    if role == "tool":
        return TOOL_RESULTS
    if role == "assistant":
        if msg.get("tool_calls"):
            return TOOL_RESULTS
        return TURN_ADDITIONS if idx >= turn_boundary else HISTORY
    # user (and anything else): the last pre-boundary message is the turn's
    # own user message; earlier ones are conversation history; post-boundary
    # user messages are loop injections (observation log, nudges).
    if idx >= turn_boundary:
        return TURN_ADDITIONS
    if idx == turn_boundary - 1:
        return CURRENT_MESSAGE
    return HISTORY


def compute_breakdown(
    messages: list[dict],
    tool_defs: list[dict],
    turn_boundary: int,
) -> dict[str, int]:
    """Estimate per-category token counts for one model call's payload."""
    breakdown: dict[str, int] = {key: 0 for key in CATEGORY_ORDER}
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        category = _classify(msg, idx, turn_boundary)
        breakdown[category] += _message_tokens(msg)
    if tool_defs:
        breakdown[TOOL_SCHEMAS] = _count_tokens(
            json.dumps(tool_defs, ensure_ascii=False)
        )
    return breakdown


def scale_breakdown(breakdown: dict[str, int], total_tokens: int) -> dict[str, int]:
    """Scale category estimates to the provider-reported prompt total.

    The provider's ``prompt_tokens`` is the ground truth for occupancy (it
    includes framing the estimator can't see). Proportional scaling keeps the
    RELATIVE shares honest while making them sum to the number the meter
    shows. Without a reported total, the raw estimates are returned as-is.
    """
    estimate_total = sum(breakdown.values())
    if total_tokens <= 0 or estimate_total <= 0:
        return {k: v for k, v in breakdown.items() if v > 0}
    factor = total_tokens / estimate_total
    scaled = {k: int(round(v * factor)) for k, v in breakdown.items() if v > 0}
    # Rounding drift: park the remainder on the largest category so the
    # shares sum to exactly the reported total.
    if scaled:
        drift = total_tokens - sum(scaled.values())
        if drift:
            largest = max(scaled, key=scaled.get)
            scaled[largest] = max(0, scaled[largest] + drift)
    return scaled

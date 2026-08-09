"""
Context Compactor — B-2026-08-02-4 (A4: tool-result simplification).

When the agent loop accumulates many tool results, the conversation
window fills with raw output the model has already acted on. LocalMind
previously trimmed oldest-first at the very edge of the context limit
(losing information wholesale) or relied on the LLM summarizer
(`maybe_compress_history`) which only fires past 75% of budget and
costs a model call.

This module is the deterministic complement (Codebuff's
`simplifyReadFileResults` / `simplifyTerminalCommandResults` pattern):
- The NEWEST `KEEP_LAST_TOOL_RESULTS` tool results are preserved verbatim
  (the model may still need their details).
- Older results are replaced with a head + omission marker + tail stub
  (the first/last few hundred chars survive — enough for the model to
  recall what the result WAS without the full payload).
- `tool_call_id` is preserved on every message, so the OpenAI-style
  tool-calling protocol stays valid (every `tool_calls` id keeps its
  matching `tool` response).
- No LLM call, no await — synchronous, idempotent, cheap.

Wired into `AgentLoop.run()` before each iteration's `chat_with_tools`
call. This complements `maybe_compress_history` (turn summarization):
the compactor frees per-tool-result bytes; the summarizer frees whole
turns once the window is genuinely over budget.
"""

from __future__ import annotations

# Keep this many of the NEWEST tool-role results verbatim.
KEEP_LAST_TOOL_RESULTS: int = 4
# Head/tail length retained from a stubbed result.
STUB_MAX_CHARS: int = 600
# Marker that identifies an already-stubbed result (idempotency).
# Worded to signal the tool SUCCEEDED so a model doing verify-after-write
# (Session 32 safety workflow) doesn't misread the omission as a failure.
_STUB_MARKER = "…[tool succeeded — output truncated for length; see earlier tool output]…"


def _stub_result(content: str, max_chars: int) -> str:
    """Shorten a long tool result to head + omission marker + tail."""
    half = max_chars // 2
    return f"{content[:half]}\n{_STUB_MARKER}\n{content[-half:]}"


def simplify_tool_results(
    messages: list[dict],
    keep_last: int = KEEP_LAST_TOOL_RESULTS,
    max_chars: int = STUB_MAX_CHARS,
) -> list[dict]:
    """Stub old tool-role results, preserving the newest `keep_last`.

    Args:
        messages: The message list about to be sent to the model.
        keep_last: How many of the newest tool results to keep verbatim.
        max_chars: Head/tail chars retained from stubbed results.

    Returns:
        A new list with older oversized tool results stubbed. Non-tool
        messages, small results, and already-stubbed results are left
        untouched. The message structure and every `tool_call_id` are
        preserved (protocol validity). Idempotent — safe to call every
        iteration.

    Note: deliberately UNCONDITIONAL (no token-budget gate) — the
    `keep_last` window preserves the results the model still needs, and
    old results it has already acted on are exactly what frees the most
    context. Gating on a token estimate would add complexity for little
    gain; the per-result `max_chars` check already skips small results.
    """
    if not messages:
        return messages

    tool_indexes = [
        i
        for i, m in enumerate(messages)
        if m.get("role") == "tool" and isinstance(m.get("content"), str)
    ]
    # Keep the newest `keep_last` tool results verbatim.
    to_stub = max(0, len(tool_indexes) - keep_last)
    if to_stub == 0:
        return messages  # nothing to stub — no copy needed

    result = list(messages)
    for i in tool_indexes[:to_stub]:
        content = messages[i]["content"]
        if len(content) <= max_chars or _STUB_MARKER in content:
            continue  # small, or already stubbed (idempotent)
        result[i] = {**messages[i], "content": _stub_result(content, max_chars)}
    return result

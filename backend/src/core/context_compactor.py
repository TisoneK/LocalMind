"""
Context Compactor — tool-result simplification + task-aware compaction.

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

A `policy` parameter enables TASK-AWARE selection:
- With `policy=None` (or a default/legacy policy), behavior is EXACTLY the
  positional legacy path above — wiring the parameter in is a no-op.
- With a real policy, tool results whose content matches the policy's
  `keep_markers` (case-insensitive) are ALSO preserved verbatim regardless
  of age, bounded by `policy.max_keep` — so a failing test two results
  back survives while older unrelated output gets stubbed.
- `policy.allow_drop` (locked OFF in P0 — no `policy_for()` returns it)
  enables the CAN-DISCARD capability: results matching `drop_markers` are
  replaced with a one-line resolved notice instead of a stub.

Wired into `AgentLoop.run()` before each iteration's `chat_with_tools`
call. This complements `maybe_compress_history` (turn summarization):
the compactor frees per-tool-result bytes; the summarizer frees whole
turns once the window is genuinely over budget.
"""

from __future__ import annotations

from typing import Optional

from core.context_policy import ContextPolicy

# Keep this many of the NEWEST tool-role results verbatim.
# Tightened 4 → 1 after the prompt-assembly
# audit showed tool-result history growing 91 → 4228 tokens across one research
# turn (5 iters), with the legacy keep_last=4 stubbing at most one result. Only
# the immediately-previous tool result needs to stay verbatim — the model just
# acted on it and may still need to reference its details. Older results the
# model has already synthesized from collapse to a head+tail stub; the task-aware
# policy keep_markers still protect task-critical content (errors, URLs, etc.)
# verbatim regardless of age. Live-verified on bankofai/qwen3.8-flash.
KEEP_LAST_TOOL_RESULTS: int = 1
# Head/tail length retained from a stubbed result.
# Tightened 600 → 400 — the legacy 600-char stub was generous for
# results the model has already acted on; 400 chars (200 head + 200 tail) still
# preserves the result's opening (where the useful title/summary lives for
# web_fetch, the file path for file_task, the command for shell) plus a tail
# stub. Smaller stubs = more history freed per iteration.
STUB_MAX_CHARS: int = 400
# Size budget for ALL tool results together, used by the agent loop. Stubbing
# older results is only worth its cost when the results would otherwise crowd
# the window: a multi-part request ("list X, then find Y, then count Z") needs
# EVERY result when it writes the final answer, and a 5-entry folder listing
# (~475 chars) was being cut mid-list the moment a second tool ran — live, one
# model then invented a folder and another dropped one. Under this budget nothing
# is stubbed; over it, the oldest oversized results shrink first, only as far as
# needed. ~8k chars is ~2k tokens, the same bound the 91 -> 4228 token audit above
# was after, without discarding small evidence.
TOOL_RESULT_BUDGET_CHARS: int = 8000
# Marker that identifies an already-stubbed result (idempotency).
# Worded to signal the tool SUCCEEDED so a model doing verify-after-write
# (the check-before-acting safety workflow) doesn't misread the omission as a failure.
_STUB_MARKER = (
    "…[tool succeeded — output truncated for length; the middle was omitted and not seen"
    " — say so if it matters, or re-read a narrower range]…"
)
# One-line notice replacing a DISCARDED result (task-aware, P0 off by default).
# Deliberately outcome-NEUTRAL (a review finding): it must not imply the
# tool succeeded or failed, so a verify-after-write model (the safety
# workflow) can't misread an omitted failed result as resolved.
_DISCARD_NOTICE = "[tool result omitted — older tool output not needed for this task]"


def _stub_result(content: str, max_chars: int) -> str:
    """Shorten a long tool result to head + omission marker + tail."""
    half = max_chars // 2
    return f"{content[:half]}\n{_STUB_MARKER}\n{content[-half:]}"


def _matches_markers(content: str, markers: tuple[str, ...]) -> bool:
    """Case-insensitive substring match (reviewed semantics)."""
    if not markers:
        return False
    lowered = content.lower()
    return any(m in lowered for m in markers)


def _legacy_simplify(
    messages: list[dict],
    tool_indexes: list[int],
    keep_last: int,
    max_chars: int,
    budget_chars: Optional[int] = None,
) -> list[dict]:
    """The positional legacy path — byte-identical to the original behavior
    when ``budget_chars`` is None. With a budget, the oldest oversized results
    are stubbed first and stubbing stops as soon as the total fits."""
    to_stub = max(0, len(tool_indexes) - keep_last)
    if to_stub == 0:
        return messages  # nothing to stub — no copy needed

    total = sum(len(messages[i]["content"]) for i in tool_indexes)
    result = list(messages)
    for i in tool_indexes[:to_stub]:
        if budget_chars is not None and total <= budget_chars:
            break  # everything left fits — keep the remaining evidence whole
        content = messages[i]["content"]
        if len(content) <= max_chars or _STUB_MARKER in content:
            continue  # small, or already stubbed (idempotent)
        stubbed = _stub_result(content, max_chars)
        total -= len(content) - len(stubbed)
        result[i] = {**messages[i], "content": stubbed}
    return result


def simplify_tool_results(
    messages: list[dict],
    keep_last: int = KEEP_LAST_TOOL_RESULTS,
    max_chars: int = STUB_MAX_CHARS,
    policy: Optional[ContextPolicy] = None,
    budget_chars: Optional[int] = None,
) -> list[dict]:
    """Stub old tool-role results, preserving the newest `keep_last`.

    Args:
        messages: The message list about to be sent to the model.
        keep_last: How many of the newest tool results to keep verbatim.
        max_chars: Head/tail chars retained from stubbed results.
        policy: Optional ContextPolicy. When None or a default/
            legacy policy, behavior is the positional legacy path exactly.
            With keep_markers, matching old results are preserved verbatim
            (bounded by policy.max_keep) in addition to the newest window.
        budget_chars: When set, nothing is stubbed while ALL tool results
            together fit this budget, and (legacy path) stubbing stops as soon
            as they do. None (default) keeps the unconditional behavior.

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
    if not tool_indexes:
        return messages

    if budget_chars is not None and sum(len(messages[i]["content"]) for i in tool_indexes) <= budget_chars:
        return messages  # everything fits — a multi-part answer needs every result

    # No policy (or a legacy default) → the exact positional path.
    if policy is None or policy.task_type == "default":
        return _legacy_simplify(messages, tool_indexes, keep_last, max_chars, budget_chars)

    # ── Task-aware path ──────────────────────────────────────────
    protected: set[int] = set()
    # 1. The newest `keep_last` results stay verbatim (positional baseline).
    protected.update(tool_indexes[-keep_last:])
    # 2. Policy keep markers: old results that MATTER for this task survive
    #    regardless of age, bounded by max_keep so a pathological stream
    #    can't fill the window with protected results. Only STUBBABLE matches
    #    (over max_chars) consume the budget — small marker lines would never
    #    be stubbed anyway, so protecting them wastes the cap on nothing
    #    (review: under-protection edge).
    if policy.keep_markers:
        matched = [
            i
            for i in tool_indexes
            if _matches_markers(messages[i]["content"], policy.keep_markers)
            and len(messages[i]["content"]) > max_chars
        ]
        protected.update(matched[: policy.max_keep])

    result = list(messages)
    changed = False
    for i in tool_indexes:
        if i in protected:
            continue
        content = messages[i]["content"]
        # CAN-DISCARD capability (locked OFF in P0 — no policy_for() sets
        # allow_drop=True; only explicit test policies do). Skipping
        # already-stubbed results keeps the path strictly idempotent even if
        # a stub's surviving head/tail happens to match a drop marker
        # (review: stub→discard mutation across passes).
        if (
            policy.allow_drop
            and policy.drop_markers
            and _STUB_MARKER not in content
            and _matches_markers(content, policy.drop_markers)
        ):
            if content != _DISCARD_NOTICE:
                result[i] = {**messages[i], "content": _DISCARD_NOTICE}
                changed = True
            continue
        if len(content) <= max_chars or _STUB_MARKER in content:
            continue  # small, or already stubbed (idempotent)
        result[i] = {**messages[i], "content": _stub_result(content, max_chars)}
        changed = True

    return result if changed else messages

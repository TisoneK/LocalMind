"""
best_of_n_edit tool — B-2026-08-02-11 (C2, best-of-N editor pattern).

Borrowed from Codebuff's `editor-multi-prompt` (agents/editor/best-of-n/
editor-multi-prompt.ts). Converts "the model's first guess" into "the best
of N guesses":

    1. Spawn N CodingAgent children IN PARALLEL (via the B1 parallel
       delegation primitive), each under a different edit strategy
       (conservative / refactor / minimal-diff / ...).
    2. Each child reads the file, stages its candidate with
       propose_str_replace (B2 — no disk write), and echoes the proposal
       payload (the child's own registry is discarded when it ends).
    3. Spawn one EditorSelectorAgent child with ALL N proposals.
    4. The selector returns {"choice", "reason", "suggested_improvements"}.
    5. The parent re-stages the winner (propose_str_replace re-runs the
       full edit_file validation gates) and applies it via
       apply_proposed_edit (inherits file_writer's permission gate).

Risk mitigations (per the C2 spec): default N=2 (raised as confidence
grows, max 5); every selection is logged; the selector can be routed to a
strong model via LOCALMIND_AGENT_MODEL_EDITOR_SELECTOR (C1) even when the
orchestrator is local; a failed selector parse falls back to candidate 0
with a warning rather than failing the whole edit.

Usage (JSON payload):
    {"file_path": "src/foo.py", "instruction": "make the parser strict",
     "n": 2, "strategies": ["conservative", "refactor"]}
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from core.agent.delegation import DelegationInstructionPacket, DelegationResult
from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool
from tools.delegate import (
    MAX_DELEGATION_DEPTH,
    _current_adapter,
    _current_depth,
    get_current_obs,
)
from tools.delegate_parallel import (
    DELEGATION_WALL_CLOCK_SECS,
    MAX_PARALLEL_TARGETS,
    _run_child,
)
from tools.edit_file import _resolve_path

logger = logging.getLogger(__name__)

# Default strategy roster. `conservative` and `refactor` are the N=2 default
# (per the C2 spec's "start with N=2" mitigation); more are used when the
# caller asks for more candidates.
DEFAULT_STRATEGIES: list[str] = ["conservative", "refactor", "minimal-diff"]

_STRATEGY_GUIDANCE: dict[str, str] = {
    "conservative": (
        "Make the smallest possible change that satisfies the instruction. "
        "Preserve existing structure, naming, and style. Only touch what must change."
    ),
    "refactor": (
        "Improve the structure of the affected code while satisfying the "
        "instruction — extract helpers, remove duplication, improve naming where "
        "it directly supports the goal. Stay within the target file."
    ),
    "minimal-diff": (
        "Achieve the instruction with the fewest changed lines. Prioritize a tiny, "
        "surgical diff over elegance."
    ),
    "aggressive": (
        "Make the most thorough change that satisfies the instruction — fully "
        "rewrite the affected section if that produces the cleanest result."
    ),
    "readability": (
        "Prioritize clarity and readability while satisfying the instruction — add "
        "comments where they help, choose descriptive names."
    ),
}

_GENERIC_GUIDANCE = (
    "Design the edit that best satisfies the instruction under this strategy."
)


def _strategy_guidance(strategy: str) -> str:
    return _STRATEGY_GUIDANCE.get(strategy.strip().lower(), _GENERIC_GUIDANCE)


def _path_allowed(path) -> bool:
    """Indirection over settings.is_path_allowed (patchable in tests)."""
    return settings.is_path_allowed(path)


def _truncate(text: str, limit: int) -> str:
    """Truncate with an ellipsis marker; only for the selector's context view."""
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…[truncated]"


def _extract_json_objects(text: str) -> list[dict]:
    """Return every JSON object embedded anywhere in `text`.

    Uses json.JSONDecoder.raw_decode at every '{' position, so nested
    braces and braces inside string values (common in code) parse
    correctly — unlike regex/brace-balancing approaches. Returns dicts in
    document order.
    """
    if not text:
        return []
    decoder = json.JSONDecoder()
    found: list[dict] = []
    for match in re.finditer(r"\{", text):
        try:
            obj, _end = decoder.raw_decode(text, match.start())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            found.append(obj)
    return found


def _extract_proposal(text: str) -> dict | None:
    """Extract a candidate edit proposal from a child agent's reply.

    The child is instructed to end with a JSON block matching the
    propose_str_replace payload: {path, action, search, replace, rationale}.
    Returns the FIRST embedded JSON object that has all of path/search/
    replace (models wrap the block in prose or fences); None if none found.
    """
    for obj in _extract_json_objects(text):
        path = str(obj.get("path", "")).strip()
        search = obj.get("search")
        replace = obj.get("replace")
        if path and isinstance(search, str) and isinstance(replace, str):
            return obj
    return None


def _extract_choice(text: str) -> int | None:
    """Extract the selector's 0-based choice from its JSON reply."""
    for obj in _extract_json_objects(text):
        if "choice" in obj:
            try:
                return int(obj["choice"])
            except (TypeError, ValueError):
                continue
    return None


def _build_editor_task(file_path: str, instruction: str, strategy: str, index: int, total: int) -> str:
    guidance = _strategy_guidance(strategy)
    return (
        f"You are candidate editor {index} of {total} in a best-of-N edit workflow.\n\n"
        f"STRATEGY: {strategy}\n{guidance}\n\n"
        f"TARGET FILE: {file_path}\n\n"
        f"INSTRUCTION:\n{instruction}\n\n"
        "Work plan:\n"
        "1. Read the target file with the file_task tool.\n"
        "2. Design the edit that best satisfies the instruction UNDER YOUR STRATEGY.\n"
        "3. Stage your edit with propose_str_replace (JSON payload: path, "
        "action='replace', search, replace). The search string must match the "
        "current file content exactly.\n"
        "4. End your reply with ONLY a JSON block (no prose after it) containing "
        "the proposal exactly as you staged it:\n"
        "\n"
        "Do NOT call best_of_n_edit, delegate, or delegate_parallel — work "
        "directly with your own tools (the parent orchestrates the candidates).\n"
        '{"path": "<absolute file path>", "action": "replace", '
        '"search": "<exact current text>", "replace": "<your replacement>", '
        '"rationale": "<one sentence>"}'
    )


def _build_selector_task(file_path: str, instruction: str, candidates: list[dict]) -> str:
    view = [
        {
            "index": i,
            "strategy": c["strategy"],
            "rationale": c.get("rationale", ""),
            "file_path": file_path,
            "search": _truncate(c.get("search", ""), 600),
            "replace": _truncate(c.get("replace", ""), 600),
        }
        for i, c in enumerate(candidates)
    ]
    return (
        "You are the Editor Selector. Pick the single best candidate edit for the "
        "instruction below. Judge each candidate on: correctness against the current "
        "file content, how fully it satisfies the instruction, diff size vs. benefit, "
        "and maintainability.\n\n"
        f"INSTRUCTION:\n{instruction}\n\n"
        f"CANDIDATES ({len(candidates)}):\n{json.dumps(view, ensure_ascii=False, indent=1)}\n\n"
        "Respond with ONLY a JSON object:\n"
        '{"choice": <0-based index>, "reason": "<why>", '
        '"suggested_improvements": "<optional short note>"}'
    )


async def _run_candidate(
    adapter,
    depth: int,
    file_path: str,
    instruction: str,
    strategy: str,
    index: int,
    total: int,
) -> DelegationResult:
    """Run ONE candidate editor (a CodingAgent child) and return its result."""
    packet = DelegationInstructionPacket.from_payload(
        {
            "target_agent": "coding",
            "task": _build_editor_task(file_path, instruction, strategy, index, total),
            "output_requirements": ("a JSON proposal block",),
        }
    )
    return await _run_child(packet, adapter, depth)


async def best_of_n_edit(message: str) -> ToolResult:
    """Produce N candidate edits, pick the best via a selector, apply it.

    Payload (JSON): {"file_path", "instruction", "n"?, "strategies"?}.
    - file_path (required): the file to edit (absolute or ~/relative).
    - instruction (required): what the edit must achieve.
    - n (optional, default 2, clamped to [2, MAX_PARALLEL_TARGETS]): the
      number of candidates to generate.
    - strategies (optional): strategy names for the candidates; defaults
      to ["conservative", "refactor", "minimal-diff"] (first n used).
    """
    # ── Parse + validate payload ─────────────────────────────────────────
    try:
        payload = json.loads(message) if message.strip().startswith("{") else {}
        if not isinstance(payload, dict):
            payload = {}
    except (json.JSONDecodeError, TypeError):
        payload = {}

    file_path = str(payload.get("file_path", "")).strip()
    instruction = str(payload.get("instruction", "")).strip()
    if not file_path or not instruction:
        return ToolResult(
            content=(
                "best_of_n_edit requires 'file_path' and 'instruction'. "
                'Example: {"file_path": "src/foo.py", "instruction": '
                '"make the parser strict", "n": 2}'
            ),
            risk=RiskLevel.LOW,
            source="best_of_n_edit",
            success=False,
            error_type="validation_error",
            error_message="Missing required field(s): file_path and/or instruction",
        )

    try:
        n = max(2, min(int(payload.get("n", 2)), MAX_PARALLEL_TARGETS))
    except (TypeError, ValueError):
        n = 2

    strategies = payload.get("strategies")
    if isinstance(strategies, list) and strategies:
        # Dedupe preserving order — duplicate strategies would spawn two
        # identical children (wasted model calls).
        roster = list(dict.fromkeys(str(s).strip() for s in strategies if str(s).strip()))
        for s in DEFAULT_STRATEGIES:  # pad with defaults if fewer provided
            if len(roster) >= n:
                break
            if s not in roster:
                roster.append(s)
    else:
        roster = DEFAULT_STRATEGIES
    roster = roster[:n]
    while len(roster) < n:  # absolute safety — never fewer than n strategies
        roster.append("conservative")

    # ── Safety preconditions FIRST (mirrors delegate_parallel) ──────────
    # These guard the sub-agent spawn itself, so they run before any file
    # validation — a recursion-limit or adapter failure must never burn a
    # model call on path checks.
    current_depth = _current_depth.get(0)
    if current_depth >= MAX_DELEGATION_DEPTH:
        return ToolResult(
            content=(
                f"ERROR: delegation depth limit reached ({current_depth}/"
                f"{MAX_DELEGATION_DEPTH}). best_of_n_edit spawns sub-agents — "
                "handle the edit directly with your own tools instead."
            ),
            risk=RiskLevel.HIGH,
            source="best_of_n_edit",
            success=False,
            error_type="recursion_limit",
        )
    adapter = _current_adapter.get(None)
    if adapter is None:
        return ToolResult(
            content=(
                "ERROR: no adapter available for best_of_n_edit (the calling "
                "agent loop must set the current adapter). Framework bug — report it."
            ),
            risk=RiskLevel.HIGH,
            source="best_of_n_edit",
            success=False,
            error_type="adapter_unavailable",
        )

    # Resolve + validate the target file early (prepare_edit re-checks on
    # re-stage, but an early, clear error beats burning N model calls).
    try:
        resolved_path = _resolve_path(file_path)
    except Exception as exc:
        return ToolResult(
            content=f"best_of_n_edit: could not resolve path {file_path!r}: {exc}",
            risk=RiskLevel.LOW,
            source="best_of_n_edit",
            success=False,
            error_type="validation_error",
            error_message=str(exc),
        )
    if not resolved_path.exists():
        return ToolResult(
            content=(
                f"best_of_n_edit: target file does not exist: {resolved_path}. "
                "Only existing files can be edited."
            ),
            risk=RiskLevel.LOW,
            source="best_of_n_edit",
            success=False,
            error_type="not_found",
        )
    if not _path_allowed(resolved_path):
        return ToolResult(
            content=(
                f"best_of_n_edit: access denied — '{resolved_path}' is outside "
                "the allowed folders."
            ),
            risk=RiskLevel.HIGH,
            source="best_of_n_edit",
            success=False,
            error_type="permission_denied",
            error_message=f"Path not in allowed read paths: {resolved_path}",
        )
    abs_path = str(resolved_path)

    # ── 1. Spawn N candidate editors in parallel ─────────────────────────
    logger.info(
        "[best_of_n_edit] %s: spawning %d candidate editors (depth %d/%d, strategies=%s)",
        abs_path, n, current_depth + 1, MAX_DELEGATION_DEPTH, roster,
    )
    try:
        gathered = await asyncio.wait_for(
            asyncio.gather(
                *[
                    _run_candidate(adapter, current_depth, abs_path, instruction, s, i + 1, n)
                    for i, s in enumerate(roster)
                ],
                return_exceptions=True,
            ),
            timeout=DELEGATION_WALL_CLOCK_SECS,
        )
    except asyncio.TimeoutError:
        return ToolResult(
            content=(
                f"best_of_n_edit: the {n} candidate editors exceeded the "
                f"{DELEGATION_WALL_CLOCK_SECS}s parallel-delegation budget and "
                "were cancelled. Retry with a smaller 'n' or a narrower instruction."
            ),
            risk=RiskLevel.MEDIUM,
            source="best_of_n_edit",
            success=False,
            error_type="wall_clock_cap",
        )

    # ── 2. Parse candidate proposals from the children's replies ─────────
    candidates: list[dict] = []
    child_failures: list[tuple[str, str]] = []
    for result, strategy in zip(gathered, roster):
        if not isinstance(result, DelegationResult) or result.status != "completed":
            err = result.error_type if isinstance(result, DelegationResult) else "child_exception"
            child_failures.append((strategy, err))
            continue
        proposal = _extract_proposal(result.output or "")
        if proposal is None:
            child_failures.append((strategy, "no_proposal_in_output"))
            continue
        # Normalize to the parent-resolved absolute path — the child may
        # echo a relative path that resolves differently in its own CWD.
        proposal["path"] = abs_path
        proposal["strategy"] = strategy
        candidates.append(proposal)

    if not candidates:
        detail = ", ".join(f"{s}:{err}" for s, err in child_failures) or "no children"
        return ToolResult(
            content=(
                f"best_of_n_edit: none of the {n} candidate editors produced a "
                f"parseable proposal ({detail}). Nothing was changed. Retry with a "
                "clearer instruction, or edit the file directly."
            ),
            risk=RiskLevel.MEDIUM,
            source="best_of_n_edit",
            success=False,
            error_type="no_candidates",
            metadata={"child_failures": dict(child_failures)},
        )

    # ── 3. Selector: pick the best candidate ─────────────────────────────
    selector_packet = DelegationInstructionPacket.from_payload(
        {
            "target_agent": "editor_selector",
            "task": _build_selector_task(abs_path, instruction, candidates),
        }
    )
    try:
        selector_result = await asyncio.wait_for(
            _run_child(selector_packet, adapter, current_depth),
            timeout=DELEGATION_WALL_CLOCK_SECS,
        )
    except asyncio.TimeoutError:
        selector_result = DelegationResult(
            status="failed", run_id="", agent_name="editor_selector", error_type="timeout"
        )

    choice: int = 0
    selector_reason = "selector unavailable — defaulted to candidate 0"
    selector_improvements = ""
    if isinstance(selector_result, DelegationResult) and selector_result.status == "completed":
        selector_output = selector_result.output or ""
        # _extract_choice is the single source of truth for the pick; the
        # reason/improvements come from the SAME object that carried the
        # choice (not the first object with any 'choice' key).
        parsed_choice = _extract_choice(selector_output)
        if parsed_choice is not None and 0 <= parsed_choice < len(candidates):
            choice = parsed_choice
            for obj in _extract_json_objects(selector_output):
                try:
                    if int(obj.get("choice")) == parsed_choice:
                        selector_reason = _truncate(
                            str(obj.get("reason", "selector picked a candidate")), 400
                        )
                        selector_improvements = _truncate(
                            str(obj.get("suggested_improvements", "")), 300
                        )
                        break
                except (TypeError, ValueError):
                    continue
            else:
                selector_reason = "selector picked a candidate (no reason given)"
        else:
            logger.warning(
                "[best_of_n_edit] selector returned invalid choice %r (of %d candidates) — "
                "falling back to candidate 0",
                parsed_choice, len(candidates),
            )
            selector_reason = (
                f"selector returned an invalid choice ({parsed_choice}) — defaulted to candidate 0"
            )
    else:
        err = selector_result.error_type if isinstance(selector_result, DelegationResult) else "child_exception"
        logger.warning("[best_of_n_edit] selector failed (%s) — defaulting to candidate 0", err)

    winner = candidates[choice]
    winner_strategy = winner.get("strategy", roster[choice] if choice < len(roster) else "?")

    # Record the selection on the turn's observation stream so the candidate
    # comparison persists with the assistant message and survives a reload
    # (the parent runtime collects it from the collector history).
    try:
        _obs = get_current_obs()
        if _obs is not None:
            _obs.emit(
                "best_of_n_candidates",
                file_path=abs_path,
                winner_index=choice,
                winner_strategy=winner_strategy,
                candidates=[
                    {
                        "index": i,
                        "strategy": c.get("strategy", "?"),
                        "rationale": c.get("rationale", ""),
                    }
                    for i, c in enumerate(candidates)
                ],
            )
    except Exception:  # never fail the edit over an observation record
        logger.debug("[best_of_n_edit] candidate obs emit skipped", exc_info=True)

    # ── 4. Re-stage the winner in the PARENT's registry ──────────────────
    # The children's registries are discarded when they end; the parent
    # re-stages via propose_str_replace, which re-runs the full edit_file
    # validation gates (path allowed, search match, size, encoding).
    try:
        from tools.apply_proposed import apply_proposed_edit
        from tools.propose_edit import propose_str_replace
    except ImportError:  # pragma: no cover — defensive
        return ToolResult(
            content="best_of_n_edit: propose/apply tools unavailable (framework error).",
            risk=RiskLevel.HIGH,
            source="best_of_n_edit",
            success=False,
            error_type="internal_error",
        )

    restage_payload = {
        "path": winner["path"],
        "action": "replace",
        "search": winner["search"],
        "replace": winner["replace"],
    }
    restage = await propose_str_replace(json.dumps(restage_payload, ensure_ascii=False))
    if restage is None or not restage.success:
        return ToolResult(
            content=(
                f"best_of_n_edit: the selector picked candidate {choice} "
                f"('{winner_strategy}') but re-staging it failed — nothing was changed.\n\n"
                f"Selector: {selector_reason}\n\n{restage.content if restage else '(no result)'}\n\n"
                "The edit could not be applied automatically; you may retry with a "
                "different strategy or edit the file directly."
            ),
            risk=RiskLevel.MEDIUM,
            source="best_of_n_edit",
            success=False,
            error_type="restage_failed",
            metadata={
                "file_path": abs_path,
                "winner_index": choice,
                "winner_strategy": winner_strategy,
                "candidate_count": len(candidates),
                # Symmetric with the success path — lets the parent fall back
                # to a different candidate without re-running the whole N-spawn.
                "candidates": [
                    {
                        "index": i,
                        "strategy": c.get("strategy", "?"),
                        "rationale": c.get("rationale", ""),
                    }
                    for i, c in enumerate(candidates)
                ],
                "selector": {
                    "choice": choice,
                    "reason": selector_reason,
                    "suggested_improvements": selector_improvements,
                },
            },
        )

    # ── 5. Apply the winner (inherits file_writer's permission gate) ─────
    apply_result = await apply_proposed_edit(json.dumps({"path": winner["path"]}))
    if apply_result is None:
        apply_result = ToolResult(
            content="best_of_n_edit: apply returned no result (framework error).",
            risk=RiskLevel.HIGH,
            source="best_of_n_edit",
            success=False,
            error_type="internal_error",
        )

    summary_lines = [
        f"## Best-of-N edit — applied candidate {choice + 1}/{len(candidates)} "
        f"({winner_strategy})",
        "",
        f"**File:** `{abs_path}`",
        f"**Selector reason:** {selector_reason}",
    ]
    if selector_improvements:
        summary_lines += ["", f"**Suggested improvements:** {selector_improvements}"]
    summary_lines += ["", "### Candidates considered", ""]
    for i, cand in enumerate(candidates):
        marker = "✅" if i == choice else "—"
        summary_lines.append(
            f"- {marker} **{cand.get('strategy', '?')}**: {cand.get('rationale', '')[:160]}"
        )
    summary_lines += ["", apply_result.content]

    return ToolResult(
        content="\n".join(summary_lines),
        risk=apply_result.risk,
        source="best_of_n_edit",
        success=apply_result.success,
        requires_confirmation=apply_result.requires_confirmation,
        metadata={
            "file_path": abs_path,
            "winner_index": choice,
            "winner_strategy": winner_strategy,
            "candidate_count": len(candidates),
            "candidates": [
                {
                    "index": i,
                    "strategy": c.get("strategy", "?"),
                    "rationale": c.get("rationale", ""),
                }
                for i, c in enumerate(candidates)
            ],
            "selector": {
                "choice": choice,
                "reason": selector_reason,
                "suggested_improvements": selector_improvements,
            },
            **(
                {
                    "requires_permission": True,
                    "pending_path": apply_result.metadata.get("pending_path"),
                    "pending_content": apply_result.metadata.get("pending_content"),
                    "filename": apply_result.metadata.get("filename"),
                    "final_dest": apply_result.metadata.get("final_dest"),
                }
                if apply_result.metadata and apply_result.metadata.get("pending_path")
                else {}
            ),
        },
    )


# Register the tool — Intent.BEST_OF_N_EDIT → best_of_n_edit
register_tool(
    Intent.BEST_OF_N_EDIT,
    best_of_n_edit,
    description=(
        "Produce N candidate edits for one file under different strategies, pick the "
        "best via a selector agent, and apply it. Use this when a coding task demands "
        "a high-quality edit and you want the best of several attempts rather than a "
        "single guess (refactors, bug fixes with multiple valid approaches). "
        'Payload: {"file_path": "src/foo.py", "instruction": "make the parser strict", '
        '"n": 2, "strategies": ["conservative", "refactor"]}. n defaults to 2 (max 5); '
        "strategies optional (defaults: conservative, refactor, minimal-diff). The "
        "winner is applied via apply_proposed_edit (same permission gating as file_write). "
        "Expensive: spawns N+1 sub-agents."
    ),
    cost=1.5,
    latency_ms=8000,  # N parallel sub-agents + a selector call
    parallelizable=False,  # stateful: stages + applies an edit, writes disk
)

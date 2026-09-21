"""The model's two jobs: propose moves, and judge outcomes. It never owns the state."""
from __future__ import annotations

import json
import re
from typing import Optional

from core.state_engine.catalog import ToolSpec, render_catalog
from core.state_engine.state import AgentState, Evaluation, Move, Observation

# The executor bounds a tool result at 3000 chars; the evaluator must see (nearly) all of it —
# a 900-char view hid the answer in a 24-entry listing and every outcome scored 0 (live, 2026-09-21).
_EVAL_VIEW_CHARS = 2800


async def _complete(adapter, prompt: str, max_chars: int = 4000) -> str:
    text = ""
    async for chunk in adapter.chat([{"role": "user", "content": prompt}], temperature=0.2, intent="chat"):
        if getattr(chunk, "error", None):
            raise RuntimeError(str(chunk.error))
        text += getattr(chunk, "text", "") or ""
        if len(text) > max_chars:
            break
    return text


def parse_json(text: str) -> Optional[dict]:
    """First JSON object in ``text`` (models wrap it in fences or prose)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


class LLMMoveProposer:
    def __init__(self, adapter, catalog: dict[str, ToolSpec]) -> None:
        self._adapter, self._catalog = adapter, catalog

    async def propose(self, state: AgentState, n: int, avoid: set[str]) -> list[Move]:
        prompt = (
            "You plan the next steps toward a goal. Propose up to "
            f"{n} DIFFERENT next moves, each using one tool. Prefer moves that reveal "
            "the most about the goal. Do not repeat a move already tried.\n\n"
            f"{state.render()}\n\nTOOLS:\n{render_catalog(self._catalog)}\n\n"
            'Reply with JSON only: {"moves": [{"tool": "<name>", "args": {...}, "why": "<short>"}]}'
        )
        obj = parse_json(await _complete(self._adapter, prompt)) or {}
        moves: list[Move] = []
        for raw in obj.get("moves", []) if isinstance(obj.get("moves"), list) else []:
            if not isinstance(raw, dict) or not isinstance(raw.get("tool"), str):
                continue
            args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
            mv = Move(raw["tool"].strip(), args, str(raw.get("why", ""))[:120])
            if mv.fingerprint() not in avoid and all(mv.fingerprint() != m.fingerprint() for m in moves):
                moves.append(mv)
        return moves[:n]


class LLMEvaluator:
    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def evaluate(self, state: AgentState, outcomes: list[Observation]) -> list[Evaluation]:
        """Score every probed outcome in ONE call: how far does the state it would give
        get us to the goal, and does it settle the goal (with an answer grounded in it)?"""
        blocks = [
            f"[{i}] {o.move.label()} -> {'ok' if o.ok else 'FAILED'}\n{o.text[:_EVAL_VIEW_CHARS]}"
            for i, o in enumerate(outcomes)
        ]
        prompt = (
            f"{state.render()}\n\nCandidate outcomes (real tool results):\n" + "\n\n".join(blocks) + "\n\n"
            "For EACH outcome give progress 0..1 = the share of what the goal needs that is known once this outcome "
            "is added (a real, relevant result is > 0 even if more is needed; a FAILED outcome is 0). "
            "done=true only if the known facts PLUS that outcome fully settle the goal; then put the final "
            "answer in `answer`, using only facts shown above.\n"
            'Reply with JSON only: {"evals": [{"i": 0, "progress": 0.0, "done": false, "answer": "", "reason": ""}]}'
        )
        obj = parse_json(await _complete(self._adapter, prompt)) or {}
        by_i: dict[int, Evaluation] = {}
        for raw in obj.get("evals", []) if isinstance(obj.get("evals"), list) else []:
            try:
                i = int(raw["i"])
                prog = min(1.0, max(0.0, float(raw.get("progress", 0))))
            except (KeyError, TypeError, ValueError):
                continue
            reason = str(raw.get("reason", ""))[:160]
            by_i[i] = Evaluation(prog, bool(raw.get("done")), str(raw.get("answer", "")), reason)
        out = []
        for i, o in enumerate(outcomes):
            ev = by_i.get(i, Evaluation())
            # Deterministic guards: a failed probe never counts; "done" needs a grounded answer.
            if not o.ok:
                ev = Evaluation(0.0, False, "", ev.reason or "probe failed")
            elif ev.done and not ev.answer.strip():
                ev = Evaluation(ev.progress, False, "", "done without an answer")
            out.append(ev)
        return out

"""The completion judge: a silent, read-only lane on the turn bus.

A phrase list ("let me open it", "I'll check") can only catch the wording it was
written for; the model words the same non-answer differently next time (owner
transcript 2026-09-21: "Let me open it." then "Let me actually check where your
network says you are."). The model can read its own reply, so it judges.

It is a LANE (ADR-66), not a call buried in the gate: it publishes a `verdict`
fact (source ``completion_judge``) stamped with the plan generation it started
under, grounded in the loop steps it read, and every fact is emitted as a
``bus_fact`` obs event — so what the agent concluded about its own reply is on
the record and can be shown. A replan while it runs makes its verdict stale and
it is never applied to the replacement plan. The loop blocks on it only at the
final-answer gate, through the bus's one bounded ``gate()``.

It sees the request, the reply and a short digest of the evidence gathered this
turn (tool, outcome, output head) — enough to tell "reported what the tools
showed" from "promised what it has not done". One bounded, tool-free call on
SHORT replies only. Any failure or timeout is an ``unjudged`` verdict: this
check may add a nudge, it must never block or slow a turn that could not be judged.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable, Optional

from core.agent.turn_bus import TurnBus

logger = logging.getLogger(__name__)

SOURCE = "completion_judge"
# Above this a reply carries real content; the promise, if any, is not the answer.
JUDGE_MAX_REPLY_CHARS = 600
JUDGE_TIMEOUT_S = 8.0
_EVIDENCE_STEPS = 3
_EVIDENCE_CHARS = 200

_PROMPT = (
    "A user made a request and an assistant produced a reply. Decide ONE thing: "
    "does the reply finish the request, or does it END by saying the assistant "
    "will do something next that it has not done yet?\n\n"
    "Request:\n{request}\n\n{evidence}Reply:\n{reply}\n\n"
    "Answer with exactly one word. PENDING = the reply stops on a promise of a "
    "next step it did not take. DONE = it answered, reported a result, asked the "
    "user a question, or offered a choice. One word only."
)


def evidence_digest(steps: Optional[Iterable[Any]]) -> str:
    """The last few tool steps as one short block: what ran and how it ended."""
    ran = [s for s in (steps or []) if getattr(s, "tool_name", "")]
    if not ran:
        return ""
    lines = []
    for s in ran[-_EVIDENCE_STEPS:]:
        outcome = "FAILED" if getattr(s, "tool_failed", False) else "ok"
        head = " ".join(str(getattr(s, "observation", "") or "").split())[:_EVIDENCE_CHARS]
        lines.append(f"- {s.tool_name} [{outcome}]: {head}")
    return "Tools run this turn:\n" + "\n".join(lines) + "\n\n"


def _judgeable(adapter, reply: str) -> bool:
    return bool(adapter is not None and reply and len(reply) <= JUDGE_MAX_REPLY_CHARS and not reply.endswith("?"))


async def _ask(adapter, request: str, reply: str, evidence: str) -> str:
    msgs = [{"role": "user", "content": _PROMPT.format(request=(request or "")[:600], evidence=evidence, reply=reply)}]
    text = ""
    async for chunk in adapter.chat(msgs, temperature=0.0, intent="chat"):
        if getattr(chunk, "error", None):
            return ""
        text += getattr(chunk, "text", "") or ""
        if len(text) > 40:
            break
    return text


async def _run_lane(bus: TurnBus, adapter, request: str, reply: str, evidence: str, step: int) -> None:
    started_under = bus.goal_version  # a replan while we run makes this verdict stale
    try:
        raw = await asyncio.wait_for(_ask(adapter, request, reply, evidence), timeout=JUDGE_TIMEOUT_S)
        verdict = "pending" if raw.strip().upper().startswith("PENDING") else (
            "done" if raw.strip().upper().startswith("DONE") else "unjudged"
        )
    except Exception as exc:  # noqa: BLE001 — a failed judge must never fail the turn
        logger.debug("[completion_judge] unjudged: %s", exc)
        verdict = "unjudged"
    bus.publish(
        SOURCE, "verdict", {"verdict": verdict, "reply_chars": len(reply)},
        step=step, goal_version=started_under, grounded_in=(f"reply@step{step}",),
    )


async def reply_is_pending(
    bus: Optional[TurnBus], adapter, request: str, reply: str, *, step: int = 0, steps: Optional[Iterable[Any]] = None,
) -> bool:
    """Run the lane and read its verdict: True only for a FRESH ``pending`` verdict.

    ``bus`` may be None (isolated callers/tests): a private bus is used.
    """
    reply = (reply or "").strip()
    if not _judgeable(adapter, reply):
        return False
    bus = bus if bus is not None else TurnBus()
    lane = asyncio.ensure_future(_run_lane(bus, adapter, request, reply, evidence_digest(steps), step))
    bus.track(SOURCE, lane, step=step)
    await bus.gate([SOURCE], timeout=JUDGE_TIMEOUT_S + 1.0)
    fact = bus.latest("verdict", source=SOURCE, step=step)
    return bool(fact and fact.value.get("verdict") == "pending")


async def reply_leaves_work_pending(adapter, request: str, reply: str) -> bool:
    """Bus-less convenience form (same verdict, private bus)."""
    return await reply_is_pending(None, adapter, request, reply)

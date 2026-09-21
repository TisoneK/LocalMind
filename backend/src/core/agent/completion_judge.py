"""Ask the agent whether a finished reply actually finished the work.

A phrase list ("let me open it", "I'll check") can only catch the wording it was
written for; the model words the same non-answer differently next time (owner
transcript 2026-09-21: "Let me open it." then "Let me actually check where your
network says you are."). The model can read its own reply, so it judges.

One bounded, tool-free call on SHORT replies only. Any failure or timeout means
"not pending": this check may add a nudge, it must never block or slow a turn
that could not be judged.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Above this a reply carries real content; the promise, if any, is not the answer.
JUDGE_MAX_REPLY_CHARS = 600
JUDGE_TIMEOUT_S = 8.0

_PROMPT = (
    "A user made a request and an assistant produced a reply. Decide ONE thing: "
    "does the reply finish the request, or does it END by saying the assistant "
    "will do something next that it has not done yet?\n\n"
    "Request:\n{request}\n\nReply:\n{reply}\n\n"
    "Answer with exactly one word. PENDING = the reply stops on a promise of a "
    "next step it did not take. DONE = it answered, reported a result, asked the "
    "user a question, or offered a choice. One word only."
)


async def reply_leaves_work_pending(adapter, request: str, reply: str) -> bool:
    """True only when the model says the reply ends on an untaken next step."""
    reply = (reply or "").strip()
    if adapter is None or not reply or len(reply) > JUDGE_MAX_REPLY_CHARS or reply.endswith("?"):
        return False

    async def _ask() -> str:
        text = ""
        msgs = [{"role": "user", "content": _PROMPT.format(request=(request or "")[:600], reply=reply)}]
        async for chunk in adapter.chat(msgs, temperature=0.0, intent="chat"):
            if getattr(chunk, "error", None):
                return ""
            text += getattr(chunk, "text", "") or ""
            if len(text) > 40:
                break
        return text

    try:
        verdict = await asyncio.wait_for(_ask(), timeout=JUDGE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — a failed judge must never fail the turn
        logger.debug("[completion_judge] skipped: %s", exc)
        return False
    return verdict.strip().upper().startswith("PENDING")

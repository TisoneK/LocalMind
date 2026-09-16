"""
Session episode memory — the system-level "keeps learning and
session context" layer.

Design: a `.context/`-style agent writes a compact "what happened this
session, what changed, what's next" record at session close and loads it
next session. LocalMind stored raw history but nothing distilled it into
an episode-level bridge. This module closes that gap — entirely
SYSTEM-level and invisible to users (no chat output, no obs events):

  - WRITE (lazy, background, best-effort): when the engine sees a turn
    arrive for a DIFFERENT session than the last active one, it
    fire-and-forgets `distill(prev_session)`; `sweep()` at startup
    catches sessions that were never switched away from (restart/crash).
    `distill()` LLM-summarizes the session tail into a compact episode
    {summary, decisions, failures, next_steps} and upserts the
    session_episodes row (one per session). If the provider fails,
    times out, or returns garbage, a DETERMINISTIC fallback writes a
    basic episode from the first user message + last response — the
    table must never stay empty just because the model was down.
  - READ (per turn, at the engine's memory merge point):
    `format_episode_hint()` turns the most recent OTHER session's
    episode into a short context hint appended to memory_facts — so a
    new session starts with "what happened before", without the user
    ever seeing this layer.

No vector-store writes (the table IS the memory — avoids an embedding
dependency), no LLM call on the hot path, never raises.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from core.agent.models import strip_worker_reports

if TYPE_CHECKING:
    from adapters.base import BaseAdapter
    from storage.db import SessionStore

logger = logging.getLogger(__name__)

# Bound the distill work: how many messages to feed the summarizer and
# how much of each. Distillation is a background digest, not a forensic
# replay.
_MAX_DISTILL_MESSAGES = 40
_MAX_MSG_CHARS = 500
_MAX_EXCERPT_CHARS = 8000
# Hard cap on the adapter call so a hung provider cannot leak a task.
_DISTILL_TIMEOUT_SECS = 30.0

_EPISODE_PROMPT = (
    "You are a session-episode summarizer for a local AI assistant. "
    "Produce a compact record of what happened in this conversation so a "
    "future session can continue smoothly. Use EXACTLY this format, one "
    "section per line, with no preamble:\n"
    "Summary: <2-3 sentences: what the user was trying to do, what was "
    "done, and the outcome>\n"
    "Decisions: <one per line, or NONE>\n"
    "Failures: <one per line (what failed and why), or NONE>\n"
    "Next steps: <one per line, or NONE>\n"
    "Keep each section under 3 lines. Do not include greetings or "
    "conversational filler."
)

_HEADERS = ("summary", "decisions", "failures", "next steps")


def _parse_episode(raw: str) -> Optional[dict]:
    """Parse the model's line-prefixed episode output. Returns None when
    nothing usable came back (caller falls back deterministically)."""
    if not raw:
        return None
    section: Optional[str] = None
    parts: dict[str, list[str]] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        lowered = line.lower()
        matched = None
        for header in _HEADERS:
            if lowered.startswith(f"{header}:"):
                matched = header
                break
        if matched:
            section = matched
            parts.setdefault(section, [])
            rest = line.split(":", 1)[1].strip()
            if rest:
                parts[section].append(rest)
        elif section is not None:
            parts[section].append(line)
    if not parts.get("summary"):
        return None
    return {
        "summary": "\n".join(parts.get("summary", []))[:1000],
        "decisions": "\n".join(parts.get("decisions", []))[:800],
        "failures": "\n".join(parts.get("failures", []))[:800],
        "next_steps": "\n".join(parts.get("next steps", []))[:800],
    }


def _deterministic_episode(
    first_user_msg: str,
    last_assistant_msg: str,
) -> dict:
    """Provider-down fallback: a basic episode from what we can prove."""
    summary_parts = []
    if first_user_msg:
        summary_parts.append(
            f'The user asked: "{first_user_msg[:200]}"'
        )
    if last_assistant_msg:
        summary_parts.append(f'Last response: "{last_assistant_msg[:200]}"')
    if not summary_parts:
        summary_parts.append("Session recorded; no message text retained.")
    return {
        "summary": " ".join(summary_parts)[:1000],
        "decisions": "",
        "failures": "",
        "next_steps": "",
    }


def format_episode_hint(episode: Optional[dict], max_chars: int = 600) -> str:
    """Shape a stored episode into a short context hint for the next
    turn. Empty/None episode -> empty string (no hint injected)."""
    if not episode:
        return ""
    lines = ["From your previous session:"]
    summary = (episode.get("summary") or "").strip()
    if summary:
        lines.append(f"  - {summary[:300]}")
    failures = (episode.get("failures") or "").strip()
    if failures and failures.upper() != "NONE":
        lines.append(f"  - Past issues to avoid: {failures[:200]}")
    next_steps = (episode.get("next_steps") or "").strip()
    if next_steps and next_steps.upper() != "NONE":
        lines.append(f"  - Left open: {next_steps[:200]}")
    if len(lines) == 1:
        return ""  # nothing but the header — do not inject an empty hint
    hint = "\n".join(lines)
    return hint[:max_chars] if len(hint) > max_chars else hint


class EpisodeMemory:
    """System-level session distillation. Background-writer + per-turn
    read bridge. Never raises; never touches the user-visible stream."""

    def __init__(
        self,
        store: Optional["SessionStore"] = None,
        adapter_getter=None,
    ) -> None:
        if store is None:
            from core.config import settings
            from storage.db import get_shared_store

            store = get_shared_store(settings.localmind_db_path)
        self._store = store
        self._adapter_getter = adapter_getter or self._default_adapter

    @staticmethod
    def _default_adapter() -> "BaseAdapter":
        from adapters import get_adapter
        from core.config import settings

        return get_adapter(settings.localmind_adapter)

    # ── Write path ─────────────────────────────────────────────────────

    def needs_distill(self, session_id: str, min_turns: int = 2) -> bool:
        """True when the session has no episode yet AND at least
        min_turns of real user conversation (cheap, no message load)."""
        if self._store.get_episode(session_id):
            return False
        try:
            history = self._store.get_history(session_id, limit=100)
            user_turns = sum(1 for m in history if getattr(m, "role", None) == "user")
            return user_turns >= min_turns
        except Exception:  # pragma: no cover — defensive
            return False

    async def distill(self, session_id: str, min_turns: int = 2) -> bool:
        """Summarize a session into its episode row. Returns True when an
        episode was written (LLM or deterministic fallback). Fire-and-
        forget safe: never raises.

        Re-distillation: a session that grew past its recorded episode
        (the user returned and continued it) is distilled again, so the
        bridge never freezes at the first session-switch point."""
        try:
            history = self._store.get_history(session_id, limit=100)
            user_msgs = [m for m in history if getattr(m, "role", None) == "user"]
            if len(user_msgs) < min_turns:
                return False
            existing = self._store.get_episode(session_id)
            if existing and len(user_msgs) <= int(existing.get("turn_count", 0) or 0):
                return False

            first_user = (user_msgs[0].content or "").strip()
            last_assistant = ""
            for m in reversed(history):
                if getattr(m, "role", None) == "assistant" and (m.content or "").strip():
                    last_assistant = (m.content or "").strip()
                    break

            excerpt = self._build_excerpt(history)
            parsed = await self._summarize(excerpt)
            episode = parsed if parsed else _deterministic_episode(first_user, last_assistant)

            self._store.record_episode(
                session_id=session_id,
                summary=episode["summary"],
                decisions=episode.get("decisions", ""),
                failures=episode.get("failures", ""),
                next_steps=episode.get("next_steps", ""),
                turn_count=len(user_msgs),
            )
            logger.info(
                "[episode] distilled session %s (%d turns, %s)",
                session_id[:8],
                len(user_msgs),
                "llm" if parsed else "fallback",
            )
            return True
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("[episode] distill skipped for %s: %s", session_id[:8], exc)
            return False

    async def sweep(
        self,
        grace_secs: float = 3600.0,
        min_turns: int = 2,
        limit: int = 5,
    ) -> int:
        """Distill sessions that ended without a session-switch trigger
        (restart/crash). Bounded by limit; best-effort. Returns the
        number of episodes written."""
        done = 0
        for session_id in self._store.sessions_needing_episode(
            grace_secs=grace_secs, min_turns=min_turns, limit=limit
        ):
            if await self.distill(session_id, min_turns=min_turns):
                done += 1
        return done

    # ── Internals ──────────────────────────────────────────────────────

    @staticmethod
    def _build_excerpt(history: list) -> str:
        """Compact conversation tail for the summarizer (bounded)."""
        tail = history[-_MAX_DISTILL_MESSAGES:]
        lines = []
        total = 0
        for m in tail:
            role = getattr(m, "role", None)
            content = (getattr(m, "content", "") or "").strip()
            if not content:
                continue
            content = content[:_MAX_MSG_CHARS]
            # Keep internal evidence-recap blocks out of distilled memory —
            # the summary feeds future prompts, and the format must not
            # circulate back to the model.
            if str(getattr(role, "value", role) or "").lower() == "assistant":
                content = strip_worker_reports(content)
            line = f"{role}: {content}"
            total += len(line)
            if total > _MAX_EXCERPT_CHARS:
                break
            lines.append(line)
        return "\n".join(lines)

    async def _summarize(self, excerpt: str) -> Optional[dict]:
        """One LLM call for the episode. None on any failure (adapter
        error, empty stream, timeout, unparseable output)."""
        if not excerpt:
            return None
        adapter = self._adapter_getter()

        async def _call():
            chunks = []
            async for chunk in adapter.chat(
                [
                    {"role": "system", "content": _EPISODE_PROMPT},
                    {"role": "user", "content": f"Conversation:\n{excerpt}"},
                ],
                temperature=0.2,
            ):
                if getattr(chunk, "error", None):
                    return None
                chunks.append(getattr(chunk, "text", None) or "")
            return _parse_episode("".join(chunks).strip())

        try:
            return await asyncio.wait_for(_call(), timeout=_DISTILL_TIMEOUT_SECS)
        except Exception as exc:
            logger.debug("[episode] LLM distill failed (fallback used): %s", exc)
            return None

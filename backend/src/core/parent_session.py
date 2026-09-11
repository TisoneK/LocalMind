"""Per-chat rolling session state for the Parent agent (ADR-52 phase 2).

The ``ParentSession`` lives for the lifetime of a chat session. It carries:

- a **rolling summary** — compacted prose for older turns, so long
  conversations stay bounded in the parent prompt without losing thread;
- a **bounded recent tail** — the exact last N user/assistant pairs, preserved
  verbatim so the most recent verified evidence and the user's own wording
  are never compacted away;
- a **turn counter** — durable across backend restarts.

The kernel (``ParentKernel``) is boot-owned and immutable per settings; the
``ParentSession`` is chat-owned and mutable per turn. Together they form the
ADR-52 two-layer warm context: kernel = static operating context, session =
the rolling conversation memory.

Compaction policy
-----------------
When ``recent_tail`` grows beyond ``RECENT_TAIL_MAX`` pairs, the oldest pair
is folded into ``rolling_summary`` as a one-line "user asked X; assistant
answered Y" entry. The summary itself is bounded: when it exceeds
``SUMMARY_MAX_CHARS`` characters, the oldest third is dropped (the most
recent summary entries are the most relevant for ongoing work).

This module owns only data shape and compaction. Prompt injection and
persistence are the caller's responsibility (``agent_runtime`` and
``storage.db.SessionStore`` respectively).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core.agent.models import strip_worker_reports

logger = logging.getLogger(__name__)

# Maximum number of (user, assistant) pairs kept verbatim in the recent tail.
# Older pairs are folded into the rolling summary. 6 pairs = ~12 messages,
# which is enough to preserve the exact wording of an ongoing multi-step
# task while letting long-ago context compact.
RECENT_TAIL_MAX = 6

# Hard character cap on the rolling summary. When it exceeds this, the oldest
# third is dropped. 4000 chars ≈ ~1000 tokens — bounded but still useful.
SUMMARY_MAX_CHARS = 4000

# Per-message truncation when folding a pair into the summary. The summary is
# a compact pointer, not a full transcript.
SUMMARY_ENTRY_USER_CHARS = 200
SUMMARY_ENTRY_ASSISTANT_CHARS = 280


@dataclass
class ParentSession:
    """Per-chat rolling session state for the Parent agent.

    Mutated in place after each turn; the caller is responsible for
    persisting via ``SessionStore.save_parent_session``.
    """

    session_id: str
    rolling_summary: str = ""
    recent_tail: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    updated_at: float = field(default_factory=time.time)

    # ── Construction ───────────────────────────────────────────────────────

    @classmethod
    def from_store(cls, session_id: str, stored: Optional[dict]) -> "ParentSession":
        """Build a ParentSession from ``SessionStore.get_parent_session`` output.

        A ``None`` stored dict yields a fresh empty session — the caller does
        not need to branch on "first turn vs continuing".
        """
        if not stored:
            return cls(session_id=session_id)
        return cls(
            session_id=session_id,
            rolling_summary=stored.get("rolling_summary") or "",
            recent_tail=list(stored.get("recent_tail") or []),
            turn_count=int(stored.get("turn_count") or 0),
            updated_at=float(stored.get("updated_at") or time.time()),
        )

    def to_store(self) -> dict:
        """Serialize for ``SessionStore.save_parent_session``."""
        return {
            "rolling_summary": self.rolling_summary or None,
            "recent_tail": list(self.recent_tail) or None,
            "turn_count": self.turn_count,
        }

    def to_json(self) -> str:
        """Stable JSON for snapshots/tests."""
        return json.dumps(
            {
                "session_id": self.session_id,
                "rolling_summary": self.rolling_summary,
                "recent_tail": self.recent_tail,
                "turn_count": self.turn_count,
                "updated_at": self.updated_at,
            },
            sort_keys=True,
        )

    # ── Compaction ─────────────────────────────────────────────────────────

    def update_with_turn(
        self,
        user_message: str,
        assistant_message: str,
        *,
        tool_summary: Optional[str] = None,
    ) -> None:
        """Fold a completed turn into the session state.

        - Appends the (user, assistant) pair to ``recent_tail``.
        - When ``recent_tail`` exceeds ``RECENT_TAIL_MAX`` pairs, the oldest
          pair is compacted into ``rolling_summary``.
        - Trims ``rolling_summary`` to ``SUMMARY_MAX_CHARS``.
        - Increments ``turn_count``.

        ``tool_summary`` (optional) is a one-line description of the most
        significant tool action this turn (e.g. ``"shell: ls ~/projects"``).
        It is folded into the summary entry so the summary records what the
        agent *did*, not just what it said.
        """
        user_message = (user_message or "").strip()
        assistant_message = (assistant_message or "").strip()
        if not user_message and not assistant_message:
            return

        # Internal evidence-recap blocks appended to past answers must never
        # enter the session state: recent_tail and the rolling summary are
        # both injected into future prompts, and a model that reads the recap
        # format back starts mimicking it into its answers.
        assistant_message = strip_worker_reports(assistant_message).strip()

        self.recent_tail.append(
            {
                "user": user_message,
                "assistant": assistant_message,
                "tool_summary": (tool_summary or "").strip(),
                "ts": time.time(),
            }
        )
        self.turn_count += 1
        self.updated_at = time.time()

        # Compact oldest pair(s) into the rolling summary when the tail
        # exceeds the bounded window. Loop in case a caller appended more
        # than one pair before calling update (defensive — current callers
        # append one at a time).
        while len(self.recent_tail) > RECENT_TAIL_MAX:
            oldest = self.recent_tail.pop(0)
            self._fold_into_summary(oldest)

        self._trim_summary()

    def _fold_into_summary(self, pair: dict[str, Any]) -> None:
        """Compact one (user, assistant) pair into the rolling summary."""
        user = (pair.get("user") or "").strip()
        assistant = (pair.get("assistant") or "").strip()
        tool = (pair.get("tool_summary") or "").strip()
        if not user and not assistant:
            return
        entry_parts: list[str] = []
        if user:
            entry_parts.append(f"User asked: {user[:SUMMARY_ENTRY_USER_CHARS]}")
        if tool:
            entry_parts.append(f"did {tool[:120]}")
        if assistant:
            entry_parts.append(f"answered: {assistant[:SUMMARY_ENTRY_ASSISTANT_CHARS]}")
        entry = " | ".join(entry_parts)
        if self.rolling_summary:
            self.rolling_summary = f"{self.rolling_summary}\n{entry}"
        else:
            self.rolling_summary = entry

    def _trim_summary(self) -> None:
        """Drop the oldest third of the rolling summary when it exceeds the cap."""
        if len(self.rolling_summary) <= SUMMARY_MAX_CHARS:
            return
        # Keep the most recent 2/3 by character count. The summary is a list
        # of newline-separated entries; trimming by char count from the start
        # preserves the most recent entries (which are at the end).
        keep = self.rolling_summary[-(SUMMARY_MAX_CHARS * 2 // 3):]
        # Snap to the next newline so we don't cut an entry in half.
        nl = keep.find("\n")
        if nl > 0:
            keep = keep[nl + 1:]
        self.rolling_summary = keep.lstrip()

    # ── Prompt injection ───────────────────────────────────────────────────

    def to_prompt_section(self) -> Optional[str]:
        """Return the rolling-summary text to inject into the parent prompt.

        Returns ``None`` when the summary is empty (turn 1 of a fresh chat),
        so the caller can skip the system message entirely. The recent tail
        is *not* included here — it is already injected as ordinary user/
        assistant messages by the runtime.
        """
        if not self.rolling_summary.strip():
            return None
        return (
            "[Conversation so far — compacted summary of earlier turns]\n"
            f"{self.rolling_summary.strip()}\n"
            "[End of summary. The messages that follow are the most recent turns, verbatim.]"
        )

    # ── Read-only views ────────────────────────────────────────────────────

    @property
    def is_empty(self) -> bool:
        return not self.rolling_summary and not self.recent_tail

    def recent_tail_messages(self, *, max_pairs: int = RECENT_TAIL_MAX) -> list[dict[str, str]]:
        """Return the recent tail as ``{"role", "content"}`` dicts for the loop.

        Truncated to ``max_pairs`` (most recent first). The order is
        chronological (oldest first) so the caller can ``extend`` onto the
        prompt's message list directly.
        """
        pairs = self.recent_tail[-max_pairs:] if max_pairs > 0 else self.recent_tail
        out: list[dict[str, str]] = []
        for pair in pairs:
            user = (pair.get("user") or "").strip()
            assistant = (pair.get("assistant") or "").strip()
            if user:
                out.append({"role": "user", "content": user})
            if assistant:
                out.append({"role": "assistant", "content": assistant})
        return out

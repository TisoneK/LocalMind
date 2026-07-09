"""
Persistence mixin — user/assistant message storage helpers.

Extracted from the original engine.py. These methods handle writing
messages to the SessionStore with error handling and deduplication,
including the guaranteed-persist safety net for interrupted generators.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.models import Message, Role

logger = logging.getLogger(__name__)


class _PersistenceMixin:
    """Message persistence methods, mixed into Engine."""

    def _persist_user_message(
        self,
        session_id: str,
        message: str,
        filename: Optional[str] = None,
        original_path: Optional[str] = None,
        file: Optional[bytes] = None,
        content_type: Optional[str] = None,
    ) -> None:
        """Persist the user message IMMEDIATELY at the start of process().

        v0.11 CRITICAL FIX: Previously, the user message was persisted AFTER
        streaming (at the end of process()), alongside the assistant message.
        If the generator was interrupted (client disconnect, exception, GC
        cleanup), the append() calls never executed and the conversation
        history was silently lost. On the next turn, get_history() returned
        empty, and the ThinkingDispatcher said "No prior exchange exists."

        Now: the user message is persisted BEFORE any LLM calls or streaming,
        guaranteeing it's saved even if the generator crashes mid-stream.
        """
        try:
            self._store.append(
                session_id,
                Message(
                    role=Role.USER,
                    content=message,
                    file_name=filename,
                    file_path=original_path,
                    file_size=len(file) if file else None,
                    file_type=content_type,
                ),
            )
        except Exception as e:
            logger.error(
                f"[engine] FAILED to persist user message for session "
                f"{session_id[:8]}: {e}. History will be incomplete!",
                exc_info=True,
            )

    def _persist_assistant_message(
        self,
        session_id: str,
        response_text: str,
    ) -> None:
        """Persist the assistant message with error handling.

        v0.11: Wraps append() in try/except so a DB failure never crashes
        the generator or silently loses history without logging.
        """
        try:
            self._store.append(
                session_id,
                Message(
                    role=Role.ASSISTANT,
                    content=response_text,
                ),
            )
        except Exception as e:
            logger.error(
                f"[engine] FAILED to persist assistant message for session "
                f"{session_id[:8]}: {e}. Response was delivered but history "
                f"will be incomplete on next turn!",
                exc_info=True,
            )

    def _guarantee_persist_assistant(
        self,
        session_id: str,
        response_chunks: list[str],
    ) -> None:
        """Call from API route finally/cleanup to persist assistant message if needed.

        Deduplication: checks if the most recent assistant message in the DB
        already matches the response text. If so, skips persistence.
        This is safe to call even when process() already persisted — it will
        simply detect the duplicate and do nothing.
        """
        response_text = "".join(response_chunks).strip()
        if not response_text:
            return
        try:
            # Check if the most recent assistant message already matches
            recent = self._store.get_history(session_id, limit=2)
            for msg in reversed(recent):
                if msg.role == Role.ASSISTANT and msg.content.strip() == response_text:
                    return  # Already persisted — skip

            self._store.append(
                session_id,
                Message(
                    role=Role.ASSISTANT,
                    content=response_text,
                ),
            )
            logger.info(
                f"[engine] GUARANTEED persist assistant message for session "
                f"{session_id[:8]} ({len(response_text)} chars — generator "
                f"was interrupted before normal persist)"
            )
        except Exception as e:
            logger.error(f"[engine] FAILED guaranteed persist for session {session_id[:8]}: {e}")

"""
Reflection mixin — post-response self-critique quality gate.

Extracted from the original engine.py. This mixin runs a quick LLM
self-critique on the agent's answer to catch fabrication, inaccuracy,
or incompleteness. When issues are found, a correction is stored in
the conversation history and fed back to the flywheel for routing
improvement.
"""

from __future__ import annotations

import logging
import re

from core.agent.constants import REFLECT_ENABLED, REFLECT_INTENTS
from core.config import settings
from core.models import Intent
from core.obs import ObsCollector

logger = logging.getLogger(__name__)


def get_adapter(*args, **kwargs):
    """Deferred-lookup wrapper — see _pipeline.py for rationale."""
    from core.engine import get_adapter as _real

    return _real(*args, **kwargs)


class _ReflectionMixin:
    """Post-response reflection methods, mixed into Engine."""

    async def _reflect_on_answer(
        self,
        response_text: str,
        intent: Intent,
        message: str,
        session_id: str,
        obs: ObsCollector,
    ) -> None:
        """
        Post-hoc reflection: run a quick self-critique on the agent's answer.

        P10 enhancements:
        1. Flywheel accuracy data injected into reflection prompt — the reviewer
           knows which intents the system historically gets wrong, so it can be
           extra cautious in those areas.
        2. Structured output parsing (SCORE/CONFIDENCE/ISSUES/CORRECTION) —
           enables quantitative quality tracking and automated thresholds.
        3. Reflection results fed back to flywheel — when reflection catches
           fabrication, the original routing event is marked as wrong, which
           improves future routing accuracy.

        This is a fire-and-forget quality gate that runs AFTER the response
        has been streamed. It asks the model to check its own answer for
        fabrication, inaccuracy, or incompleteness. If issues are found,
        an obs event is emitted so the frontend can surface a correction,
        AND a correction message is appended to the session history so
        the user sees the fix on their next turn or in a follow-up.

        The reflection step costs one additional LLM call but only runs for
        intents where fabrication is most common (SHELL, FILE_TASK, etc.).
        It's disabled for CHAT because conversation doesn't need self-critique.
        """
        if not REFLECT_ENABLED:
            return
        if intent not in REFLECT_INTENTS:
            return
        # Skip reflection for very short responses — nothing to critique
        if len(response_text.split()) < 20:
            return

        try:
            # P10: Inject flywheel accuracy data for context-aware reflection
            _accuracy = self._flywheel.get_intent_accuracy(min_samples=3)
            _error_patterns = self._flywheel.get_recent_error_patterns(limit=3)
            _accuracy_section = ""
            if _accuracy:
                _weak_intents = [f"{k} ({v:.0%} accurate)" for k, v in _accuracy.items() if v < 0.8]
                if _weak_intents:
                    _accuracy_section = (
                        f"\n\nHistorical accuracy warnings — the system has been wrong "
                        f"before on these intents: {', '.join(_weak_intents[:3])}. "
                        f"Be extra cautious when reviewing answers in these areas."
                    )
            if _error_patterns:
                _recent_errors = "; ".join(
                    f"'{e['query'][:40]}' was routed to {e['routed_to']} but should have been {e['should_have_been']}"
                    for e in _error_patterns
                    if e.get("should_have_been")
                )
                if _recent_errors:
                    _accuracy_section += (
                        f"\n\nRecent routing errors: {_recent_errors}. If this answer seems misrouted, flag it."
                    )

            reflect_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a quality reviewer for LocalMind, a local AI assistant. "
                        "Examine the assistant's answer below for:\n"
                        "1. FABRICATION: any specific details (file names, folder contents, numbers, paths) "
                        "that were NOT in the tool results\n"
                        "2. INACCURACY: any claims that contradict the tool output\n"
                        "3. COMPLETENESS: whether the answer fully addresses the user's question\n\n"
                        "Respond in this structured format:\n"
                        "SCORE: <1-10 quality rating>\n"
                        "CONFIDENCE: <high/medium/low>\n"
                        "VERDICT: OK or ISSUE\n"
                        "If ISSUE:\n"
                        "ISSUE: <brief description of what's wrong>\n"
                        "CORRECTION: <the corrected facts>"
                        f"{_accuracy_section}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User asked: {message}\n\n"
                        f"Assistant answered:\n{response_text[:3000]}\n\n"
                        "Review this answer for fabrication, inaccuracy, or incompleteness."
                    ),
                },
            ]

            adapter = get_adapter(settings.localmind_adapter)
            chunks = []
            async for chunk in adapter.chat(reflect_messages, temperature=0.0):
                if chunk.error:
                    logger.warning("[reflection] adapter error: %s", chunk.error[:120])
                    break
                chunks.append(chunk.text)

            review = "".join(chunks).strip()

            # P10: Parse structured output for quality metrics
            _score = 0
            _score_match = re.search(r"SCORE:\s*(\d+)", review)
            if _score_match:
                _score = int(_score_match.group(1))

            _confidence = "medium"
            _conf_match = re.search(r"CONFIDENCE:\s*(high|medium|low)", review, re.IGNORECASE)
            if _conf_match:
                _confidence = _conf_match.group(1).lower()

            _is_issue = "ISSUE:" in review.upper() or "VERDICT: ISSUE" in review.upper()

            # Emit structured reflection metrics
            obs.emit(
                "reflection_complete",
                intent=intent.value,
                score=_score,
                confidence=_confidence,
                has_issue=_is_issue,
                review_length=len(review),
            )

            if _is_issue:
                issue_text = ""
                _issue_match = re.search(
                    r"ISSUE:\s*(.+?)(?:\n(?:CORRECTION|SCORE|CONFIDENCE|VERDICT)|$)",
                    review,
                    re.IGNORECASE | re.DOTALL,
                )
                if _issue_match:
                    issue_text = _issue_match.group(1).strip()
                else:
                    # Fallback: grab text after ISSUE:
                    _issue_fallback = re.search(r"ISSUE:\s*(.+)", review, re.IGNORECASE)
                    if _issue_fallback:
                        issue_text = _issue_fallback.group(1).strip()

                logger.info(
                    "[reflect] self-critique caught issue: %s (intent=%s, session=%s, score=%d, confidence=%s)",
                    issue_text[:100],
                    intent.value,
                    session_id[:8],
                    _score,
                    _confidence,
                )
                obs.emit(
                    "reflection_issue",
                    intent=intent.value,
                    issue=issue_text[:200],
                    score=_score,
                    confidence=_confidence,
                )

                # P10: Feed reflection result back to flywheel
                # If reflection catches fabrication/inaccuracy on a low-score answer,
                # mark the routing event as potentially wrong. This creates a feedback
                # loop: reflection → flywheel → router → better routing.
                if _score <= 4 and _confidence == "low":
                    # Find the most recent flywheel event for this session/intent
                    # and mark it as wrong. This is conservative — only low-score,
                    # low-confidence reflections trigger flywheel feedback.
                    try:
                        with self._flywheel._lock:
                            conn = self._flywheel._connect()
                            conn.execute(
                                """UPDATE flywheel_events SET outcome = 'wrong'
                                WHERE session_id = ? AND final_intent = ?
                                AND outcome IS NULL
                                ORDER BY ts DESC LIMIT 1""",
                                (session_id, intent.value),
                            )
                            conn.commit()
                            conn.close()
                        logger.debug(
                            "[reflect] fed back to flywheel: marked %s/%s as wrong (score=%d)",
                            session_id[:8],
                            intent.value,
                            _score,
                        )
                    except Exception:
                        pass  # Non-critical — flywheel feedback is best-effort

                # Extract correction if provided
                _correction = ""
                _corr_match = re.search(
                    r"CORRECTION:\s*(.+?)(?:\n(?:SCORE|CONFIDENCE|VERDICT|ISSUE)|$)",
                    review,
                    re.IGNORECASE | re.DOTALL,
                )
                if _corr_match:
                    _correction = _corr_match.group(1).strip()

                # Store a correction in history so the user sees it
                # on their next turn. This is the key improvement:
                # reflection isn't just logging — it actively improves
                # the conversation by surfacing the fix.
                if _correction and len(_correction) > 10:
                    _correction_msg = f"⚠️ **Self-correction:** {_correction}"
                    # Append correction as an assistant message in history
                    # so it's visible in the conversation and informs future turns.
                    self._persist_assistant_message(session_id, _correction_msg)
                    obs.emit(
                        "reflection_correction",
                        intent=intent.value,
                        correction=_correction[:200],
                    )
                    logger.info(
                        "[reflect] stored correction in history (session=%s): %s",
                        session_id[:8],
                        _correction[:80],
                    )
            else:
                logger.debug(
                    "[reflect] answer passed self-critique (intent=%s, score=%d)",
                    intent.value,
                    _score,
                )

        except Exception as e:
            logger.debug("[reflect] reflection failed (non-critical): %s", e)

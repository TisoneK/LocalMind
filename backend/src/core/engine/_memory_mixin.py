"""
Memory mixin — fact extraction, validation, and storage.

Extracted from the original engine.py. These methods handle:
  - Extracting facts from user messages and assistant responses
  - Validating facts against a negative-learning safety gate (blocks
    prompt-injection / jailbreak facts from being stored)
  - Deduplicating against existing memory
  - Storing valid facts with importance scoring
"""

from __future__ import annotations

import logging
import re

from core.obs import ObsCollector

from ._helpers import MEMORY_DEDUP_THRESHOLD

logger = logging.getLogger(__name__)


class _MemoryMixin:
    """Memory fact extraction and storage methods, mixed into Engine."""

    # ── Memory helpers ─────────────────────────────────────────────────────

    async def _extract_and_store_facts(
        self, message: str, session_id: str, obs: ObsCollector
    ) -> None:
        fact = re.sub(
            r"^\s*(remember|note|store|keep in mind)\s*(that\s*)?",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip()
        if not fact:
            return
        await self._store_fact_if_valid(fact, session_id, obs, source="user", message=message)

    async def _maybe_store_response_facts(
        self,
        response_text: str,
        session_id: str,
        obs: ObsCollector,
        user_message: str = "",
    ) -> None:
        """
        Post-response memory update: extract candidate facts from both the
        user's message and the assistant's response.

        Two extraction paths:
        1. USER-INITIATED: The user's message contains explicit fact signals
           ("remember", "my name is", "I prefer", etc.)
        2. RESPONSE-CONFIRMED: The assistant's response confirms a durable
           fact about the user (preferences, environment, plans).

        Markers are intentionally selective: only store facts that represent
        durable, cross-session knowledge. Conversational references like
        "you mentioned" are excluded — they cause cross-session context leakage.
        """
        # ── Path 1: User-initiated fact extraction ───────────────────────
        # Expanded signal set: catches more natural ways people share
        # durable facts about themselves. Still selective — we don't
        # want to store every conversational utterance.
        if user_message:
            _USER_FACT_SIGNALS = [
                # Identity & profession
                r"\bmy name is\b",
                r"\bi(?:'m| am)\b.{0,5}\b(?:a |an )?(?:developer|designer|engineer|student|teacher|writer|researcher|manager|analyst|architect|consultant|devops|admin|freelancer)\b",  # noqa: E501
                # Preferences & habits
                r"\bi (?:prefer|like|love|hate|always|usually|never|typically|normally)\b",
                r"\b(?:remember|note|store|keep in mind|don't forget)\b",
                r"\bmy (?:favorite|preferred|default|usual|main|go-to|primary)\b",
                # Work context
                r"\bi (?:work|am working|am based|was working)\b.{0,3}\b(?:at|in|on|for|with)\b",
                r"\bmy (?:project|repo|repository|codebase|app|website|server|team|company|org)\b",
                # Technical environment
                r"\bi(?:'m| am) (?:using|running|on|with|switching to|migrating to)\b.{0,15}\b(?:python|node|rust|java|go|linux|mac|windows|docker|kubernetes|aws|gcp|azure)\b",  # noqa: E501
                r"\bmy (?:stack|setup|environment|workflow|pipeline|editor|ide|terminal|shell)\b",
                # Life context that affects how we work together
                r"\bi'm (?:new to|learning|studying|struggling with|stuck on)\b",
                r"\b(?:i have|i've got)\b.{0,10}\b(?:deadline|meeting|exam|presentation|release)\b",
                # Explicit memory commands
                r"\b(?:save|store|remember|note)\s+(?:that|this|the fact)\b",
            ]
            for pattern in _USER_FACT_SIGNALS:
                match = re.search(pattern, user_message, re.IGNORECASE)
                if match:
                    # Extract the full sentence containing the signal
                    sentence_start = max(0, match.start() - 60)
                    sentence_end = min(len(user_message), match.end() + 80)
                    candidate = user_message[sentence_start:sentence_end].strip()
                    # Clean up — remove leading/trailing partial words
                    if sentence_start > 0:
                        candidate = candidate.split(None, 1)[-1] if " " in candidate else candidate
                    if len(candidate) > 20:
                        await self._store_fact_if_valid(
                            candidate, session_id, obs, source="user", message=user_message
                        )
                    break  # one fact per user message max

        # ── Path 2: Response-confirmed fact extraction ───────────────────
        # Markers that indicate a confirmed, durable user fact.
        # Expanded to catch more natural response patterns.
        _FACT_MARKERS = [
            "you prefer",
            "you always",
            "your name is",
            "you like",
            "you hate",
            "you work",
            "your project",
            "your codebase",
            "your setup",
            "you're using",
            "you are using",
            "your environment",
            "you mentioned you",
            "you told me you",
            "since you're",
            "given you're",
            "as a",
            "your stack",
            "your workflow",
            "your preferred",
            "you normally",
            "you typically",
            "you usually",
            "your team",
            "your company",
            "your org",
            "you're learning",
            "you're new to",
            "you're building",
        ]
        response_lower = response_text.lower()

        # Skip short responses — greetings, acks, one-liners never contain storable facts.
        if len(response_text.split()) < 30:
            return

        if not any(marker in response_lower for marker in _FACT_MARKERS):
            return

        # Extract the sentence containing the marker as a candidate fact
        sentences = re.split(r"(?<=[.!?])\s+", response_text)
        _regex_found = False
        for sentence in sentences:
            s_lower = sentence.lower()
            if any(marker in s_lower for marker in _FACT_MARKERS) and len(sentence) > 30:
                await self._store_fact_if_valid(
                    sentence.strip(), session_id, obs, source="assistant"
                )
                _regex_found = True
                break  # one fact per response max — avoid over-storing

        # ── Path 3 (P11): LLM-based fact extraction as fallback ──────────
        # When regex patterns don't match, use LLM to extract complex facts.
        # Only fires for longer conversations (>80 words in response) to
        # avoid wasting LLM calls on short exchanges. Rate-limited to avoid
        # excessive cost: only runs every 3rd eligible turn per session.
        if not _regex_found and len(response_text.split()) > 80 and user_message:
            _llm_extract_key = f"_llm_extract_count_{session_id}"
            _count = getattr(self, _llm_extract_key, 0)
            if _count % 3 == 0:  # Every 3rd eligible turn
                try:
                    _llm_facts = await self._memory.extract_facts_with_llm(
                        user_message=user_message,
                        assistant_response=response_text,
                        session_id=session_id,
                    )
                    for fact in _llm_facts:
                        await self._store_fact_if_valid(
                            fact, session_id, obs, source="llm_extracted", message=user_message
                        )
                        obs.emit("memory_llm_extracted", fact_preview=fact[:60])
                except Exception as e:
                    logger.debug("[memory] LLM extraction fallback failed (non-critical): %s", e)
            setattr(self, _llm_extract_key, _count + 1)

    async def _store_fact_if_valid(
        self,
        fact: str,
        session_id: str,
        obs: ObsCollector,
        source: str = "user",
        message: str = "",
    ) -> None:
        """
        Shared fact validation + storage used by both user and response paths.
        Applies: negative learning gate → deduplication gate → importance scoring → store.
        """

        _BLOCKED_PATTERNS = [
            r"\b(ignore|bypass|override|disable|forget)\b.{0,30}\b(safety|rules|guidelines|instructions|system prompt|restrictions)\b",  # noqa: E501
            r"\byou (are|must|should|will)\b.{0,40}\b(lie|deceive|pretend|ignore|always agree|never refuse)\b",
            r"\b(always|never) (tell|say|respond|answer|agree|refuse)\b",
            r"\bact (as|like)\b.{0,30}\b(jailbreak|unrestricted|dan|evil|unfiltered)\b",
            r"\byou (are|were) (wrong|stupid|dumb|useless|broken|terrible|awful|bad)\b",
            r"\b(hate|despise|dislike) (you|yourself|itself)\b",
            r"(system|assistant|user)\s*:\s*(ignore|disregard|forget)",
            r"<\s*(system|instruction|prompt)\s*>",
            r"\b(lie|make up|fabricate|hallucinate)\b.{0,20}\b(answers?|results?|facts?|data)\b",
        ]
        fact_lower = fact.lower()
        for pattern in _BLOCKED_PATTERNS:
            if re.search(pattern, fact_lower, re.IGNORECASE):
                logger.warning(f"[memory gate] blocked harmful fact: {fact[:80]}")
                obs.emit("memory_blocked", reason="negative_learning_gate", preview=fact[:60])
                return

        # Deduplication gate: skip if a near-identical fact already exists
        existing_facts = await self._memory.search(query=fact, session_id=session_id, top_k=3)
        for existing in existing_facts:
            similarity = self._simple_similarity(fact, existing.content)
            if similarity >= MEMORY_DEDUP_THRESHOLD:
                logger.debug(
                    f"[memory dedup] skipped near-duplicate fact (sim={similarity:.2f}): {fact[:60]}"
                )
                obs.emit("memory_deduped", similarity=round(similarity, 2), preview=fact[:60])
                return

        importance = (
            0.8
            if any(
                w in (message or fact).lower() for w in ["prefer", "always", "never", "important"]
            )
            else 0.5
        )
        stored = await self._memory.store(
            fact=fact,
            session_id=session_id,
            memory_type="semantic",
            source=source,
            importance=importance,
        )
        if stored:
            obs.emit("memory_stored", fact_preview=fact[:60], importance=importance, source=source)

    @staticmethod
    def _simple_similarity(a: str, b: str) -> float:
        """
        Lightweight Jaccard similarity on word sets.
        Fast enough for dedup gating — no embedding call needed.
        Replace with cosine similarity on embeddings for higher accuracy.
        """
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

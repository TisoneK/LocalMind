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
        # The shared deterministic extractor is the single
        # source of truth for cue-prefix removal — the local regex copy
        # missed "remember this:" (colon after the demonstrative) and stored
        # the framing as the fact.
        from core.memory_intent import extract_memory_content

        fact = extract_memory_content(message)
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

        Three extraction paths:
        1. PASSIVE CONTEXT: durable self-facts stated incidentally — location,
           identity, work context — with no explicit memory cue (the
           conversation-signal half of the user profile; the boot-deduced
           machine half lives in core/user_context.py). One pass, one visible
           event per ACTUAL write (ADR-64: proactive memory writes are
           visible, never silent).
        2. RESPONSE-CONFIRMED: the assistant's response confirms a durable
           fact about the user (preferences, environment, plans).
        3. DETERMINISTIC CANDIDATES from chat evidence (corrections, stated
           preferences, source knowledge from tool outcomes) — runs without
           any explicit "remember" cue and without an LLM call.
        """
        # ── Path 1: passive context (conversation-signal self-facts) ─────
        # Sentences the passive pass claims, whatever the write path decides
        # — a volatile-refused or deduped sentence must not fire a second
        # time through the generic candidate path below (one fact, one
        # event). Initialized outside the try so the candidate path can
        # always read it.
        claimed: set[str] = set()
        try:
            from core.memory_intent import (
                canonical_key,
                extract_passive_facts,
            )

            for passive in extract_passive_facts(user_message):
                claimed.add(" ".join(passive.content.lower().split()))
                # A subject-hinted key: a casually-worded location statement
                # lands on the same single-valued row the boot deduction and
                # explicit "I live in X" writes use — restatement replaces,
                # never accumulates.
                _passive_key = canonical_key(
                    passive.content, subject_hint=passive.subject_hint or None
                )
                _stored = await self._store_fact_if_valid(
                    passive.content,
                    session_id,
                    obs,
                    source="conversation",
                    message=user_message,
                    key=_passive_key,
                )
                if _stored:
                    # Visible, and only when the write actually landed —
                    # blocked, volatile-refused, and deduped candidates say
                    # nothing (the store's state did not change).
                    obs.emit(
                        "passive_context_stored",
                        fact_preview=passive.content[:60],
                        memory_type=passive.memory_type.value,
                        subject=passive.subject_hint or "general",
                    )
        except Exception:
            logger.debug(
                "[memory] passive context extraction skipped (non-critical)", exc_info=True
            )

        # ── Path 4: deterministic candidate extraction from
        # chat evidence (corrections, stated preferences, source knowledge
        # from tool outcomes). This is the autonomous "gather correct
        # information from chat evidence" tier — it runs without any explicit
        # "remember" cue and without an LLM call. Wired up from
        # extract_memory_candidates()/should_store_candidate() which were
        # defined but never called.
        #
        # Placed BEFORE Path 2's early returns: corrections ("No, that's not
        # right") and source knowledge are usually short turns that Path 2
        # would skip (it requires >= 30 response words + a fact marker).
        try:
            from core.memory_intent import extract_memory_candidates, should_store_candidate

            # Tool outcomes from this turn's obs history — the evidence for
            # source-knowledge candidates ("this site gave useful info").
            tool_results = []
            for evt in obs.history():
                if evt.type == "tool_call" and evt.data.get("output"):
                    out = str(evt.data.get("output"))
                    if len(out) > 20 and len(out) < 4000:
                        tool_results.append(out)

            candidates = extract_memory_candidates(
                user_message=user_message,
                assistant_response=response_text,
                tool_results=tool_results[:3],  # one source per turn max
            )
            for cand in candidates:
                if " ".join(cand.content.lower().split()) in claimed:
                    # Already proposed (and answered) by the passive pass —
                    # same fact must not reach the store twice per turn.
                    continue
                if not should_store_candidate(cand):
                    continue
                _wrote = await self._store_fact_if_valid(
                    cand.content,
                    session_id,
                    obs,
                    source=cand.source,
                    message=user_message,
                )
                # Visible (and honest) only when the write actually landed —
                # a blocked/deduped candidate leaves the store unchanged, so
                # it says nothing rather than claiming a write.
                if _wrote:
                    obs.emit(
                        "memory_candidate_stored",
                        fact_preview=cand.content[:60],
                        importance=cand.importance,
                        memory_type=cand.memory_type.value,
                        source=cand.source,
                    )
        except Exception as e:
            logger.debug("[memory] candidate extraction skipped (non-critical): %s", e)

        # ── Path 2: Response-confirmed fact extraction ───────────────────
        # Markers that indicate a CONFIRMED user fact — the assistant
        # completing a statement ABOUT the user, in the user's own voice
        # ("…, you prefer concise answers" — an answer echo). Deliberately
        # NOT "you prefer"/"you like" bare: those strings are how every
        # assistant hedges a suggestion ("If you prefer X, do Y"), so the
        # old marker list stored the MODEL'S OWN PROSE as the user's
        # preference — a pollution source since the file's first commit
        # (live-caught by the passive-context harness, 2026-09-19).
        _FACT_MARKERS = [
            "your name is",
            "you told me you",
            "you mentioned you",
            "you're using",
            "you are using",
            "you're building",
            "your project",
            "your codebase",
            "your setup",
            "your stack",
            "your environment",
            "your team",
            "your company",
            "you work",
        ]
        response_lower = response_text.lower()

        # Skip short responses — greetings, acks, one-liners never contain storable facts.
        if len(response_text.split()) < 30:
            return

        if not any(marker in response_lower for marker in _FACT_MARKERS):
            return

        # Suggestion shapes — the assistant offering, not completing. The
        # second pattern is anchored on the marker ITSELF ("If you prefer…",
        # "Whether you like…", "you can", "feel free"): the hedge sits left
        # of the marker, so a fixed list of sentence openers cannot catch it.
        _SUGGESTION_SHAPES = re.compile(
            r"\b(?:if|whether|when|whenever|should|since|because|although)\s+you\b"
            r"|\b(?:you (?:can|could|may|might|might want to|can also|could also)\b)"
            r"|\bfeel free\b"
            r"|\bwant me to\b",
            re.IGNORECASE,
        )

        # Extract the sentence containing the marker as a candidate fact
        sentences = re.split(r"(?<=[.!?])\s+", response_text)
        _regex_found = False
        for sentence in sentences:
            s_lower = sentence.lower()
            if _SUGGESTION_SHAPES.search(sentence):
                continue
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
        kind_override: str | None = None,
        key: str | None = None,
    ) -> bool:
        """
        Shared fact validation + storage used by every memory path.
        Applies: negative learning gate → durability policy → deduplication
        gate → importance scoring → keyed store.

        Returns True only when the fact was actually written — blocked,
        volatile-refused, and deduped facts all return False. Callers that
        surface a write to the user (e.g. a visible reflection-lesson log)
        must check this instead of assuming success (ADR-18/63: a claim
        about a mutation is derived from its outcome, not from intent).

        `kind_override` tags the stored `memory_kind` metadata with a value
        other than the durability profile's own classification — used by
        the self-reflection loop to mark a row "lesson" while the volatile
        gate still runs against the fact's actual content.

        `key` overrides the derived canonical identity — used by the passive
        context path to land a casually-worded statement on the same
        single-valued row as an explicitly-worded one.
        """
        from core.memory_intent import MemoryDurability, canonical_key, durability_profile

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
                return False

        # Durability gate — the autonomous paths need the same policy as the
        # explicit one, or a live value simply arrives by another door (the
        # passive path is where the machine's IP/ISP got stored).
        _durability = durability_profile(fact)
        if _durability.kind is MemoryDurability.VOLATILE:
            logger.info(f"[memory gate] refused volatile fact: {fact[:80]}")
            obs.emit("memory_blocked", reason="volatile_fact", preview=fact[:60])
            return False

        # Deduplication gate: skip if a near-identical fact already exists
        existing_facts = await self._memory.search(query=fact, session_id=session_id, top_k=3)
        for existing in existing_facts:
            similarity = self._simple_similarity(fact, existing.content)
            if similarity >= MEMORY_DEDUP_THRESHOLD:
                logger.debug(
                    f"[memory dedup] skipped near-duplicate fact (sim={similarity:.2f}): {fact[:60]}"
                )
                obs.emit("memory_deduped", similarity=round(similarity, 2), preview=fact[:60])
                return False

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
            # The key is the fact's identity: re-stating it replaces its row
            # instead of appending another near-copy. A caller-provided key
            # (the passive path's subject hint) wins over the derived one.
            key=key or canonical_key(fact),
            extra_metadata={
                "memory_kind": kind_override or _durability.kind.value,
                "memory_freshness": _durability.freshness,
                "memory_confidence": str(_durability.confidence),
            },
        )
        if stored:
            obs.emit("memory_stored", fact_preview=fact[:60], importance=importance, source=source)
        return bool(stored)

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

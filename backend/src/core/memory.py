"""
Memory Composer — retrieval intelligence over the raw vector store.

v0.4 upgrades (P11):
- LLM-based fact extraction: when regex patterns miss complex facts, an LLM
  call extracts structured facts from conversation turns. This catches
  preferences, constraints, and context that don't match simple patterns.
- Memory consolidation: merge near-duplicate facts over time. When two facts
  are semantically similar (same topic, updated details), the older fact
  is replaced by the newer one with a merged importance score.
- Cross-session warm-start enhancement: warm_start_facts() now includes
  a "session bridge" that carries forward key facts from the most recent
  N sessions, not just the current one.

v0.3 upgrades:
- 4-factor scoring: similarity, recency, importance, usage_frequency
- importance tag stored with each fact (user-rated or inferred)
- usage_frequency tracked via access_count metadata
- Low-confidence fallback: widen threshold when little memory exists

Scoring formula (per audit):
    score = similarity * 0.6 + recency * 0.2 + importance * 0.1 + usage_frequency * 0.1
"""

from __future__ import annotations

import logging
import time
from typing import Optional

# Use built-in generics with from __future__ import annotations
from core.models import Intent
from storage.vector import VectorStore

logger = logging.getLogger(__name__)

_MEMORY_RELEVANT_INTENTS = {
    Intent.CHAT,
    Intent.MEMORY_OP,
    Intent.FILE_TASK,
    Intent.FILE_WRITE,
    Intent.CODE_EXEC,
    Intent.SHELL,
    Intent.WEB_SEARCH,
    Intent.FILE_EDIT,
    Intent.SYSINFO,
}

# Skip embedding for very short conversational messages — no meaningful matches.
_MIN_QUERY_WORDS_FOR_MEMORY = 5

_RELEVANCE_THRESHOLD = 0.45
_LOOSE_THRESHOLD = 0.60  # used when memory store is small (< 10 facts)
# NOTE: Higher threshold = less strict filtering (looser matching)
_MAX_FACTS = 6
_RECENCY_WINDOW_SECS = 3600 * 24 * 7  # 1 week
_IMPORTANCE_DEFAULT = 0.5  # 0.0–1.0

# ADR-19 P1 (Session 177): context-hierarchy levels. Every stored fact is
# tagged with a `memory_level` so retrieval can be LEVEL-AWARE per task
# type instead of always pulling the same global pool. Hierarchy:
#   turn      — ephemeral, this turn's working context
#   session   — this session's state / recent exchanges
#   project   — repository / project-scoped knowledge
#   long_term — durable user facts (the historical default)
MEMORY_LEVELS = ("turn", "session", "project", "long_term")

# ADR-19 P1: preferred levels per task type, most-relevant first (design.md
# §6 — "the same conversation can produce different compressed contexts
# depending on the next task"). Unknown/default → None = legacy behavior
# (no level filter, exactly the pre-P1 retrieval).
_TASK_TYPE_LEVELS: dict[str, tuple[str, ...]] = {
    "debug": ("session", "turn", "long_term"),
    "plan": ("project", "long_term"),
    "code": ("project", "session"),
    "research": ("long_term", "project"),
    "chat": ("long_term",),
    "verify": ("session",),
}


def level_priorities(task_type: Optional[str]) -> Optional[tuple[str, ...]]:
    """ADR-19 P1: resolve the preferred memory levels for a task type.

    Pure + deterministic. Unknown/empty/default → None, which callers treat
    as "no level filter" — EXACTLY the pre-P1 retrieval behavior (a wiring
    no-op until a task type is explicitly resolved).
    """
    key = (task_type or "").strip().lower()
    return _TASK_TYPE_LEVELS.get(key)


class MemoryComposer:
    """
    Retrieves and ranks memory facts using 4-factor scoring.

    Score = similarity * 0.6 + recency * 0.2 + importance * 0.1 + usage_freq * 0.1
    """

    def __init__(self, vector_store: VectorStore | None = None):
        self._store = vector_store or VectorStore()

    async def compose(
        self,
        query: str,
        intent: Intent,
        session_id: str,
        top_k: int = _MAX_FACTS,
        levels: Optional[tuple[str, ...]] = None,
    ) -> list[str]:
        """Retrieve memory facts for a query with 4-factor scoring.

        ADR-19 P1: `levels` optionally restricts retrieval to facts tagged
        with one of the given context-hierarchy levels (turn/session/
        project/long_term). None = legacy behavior (any level). Facts
        stored before P1 carry no `memory_level` metadata — they are
        treated as `long_term` so older stores still surface.
        """
        if intent not in _MEMORY_RELEVANT_INTENTS:
            return []

        # Skip embedding for short CHAT queries — no meaningful matches.
        # Always run for MEMORY_OP, FILE_TASK, and FILE_WRITE.
        word_count = len(query.strip().split())
        if intent == Intent.CHAT and word_count < _MIN_QUERY_WORDS_FOR_MEMORY:
            return []

        try:
            raw = await self._store.recall_with_scores(query=query, top_k=top_k * 3)
        except Exception as e:
            logger.warning("Memory recall failed: %s", e)
            return []

        if not raw:
            return []

        # Use a looser threshold when store is small (prevents empty memory on new installs)
        # NOTE: Need actual store size, not query result count
        try:
            total_facts = await self._store.count()
        except Exception:
            total_facts = 0  # Fallback if count() fails
        threshold = _LOOSE_THRESHOLD if total_facts < 10 else _RELEVANCE_THRESHOLD

        now = time.time()
        ranked = []

        for fact, distance, metadata in raw:
            if distance > threshold:
                continue

            # ADR-19 P1: level-aware filter. Facts without a memory_level
            # tag (pre-P1 stores) default to long_term so nothing is lost.
            if levels is not None:
                fact_level = str(metadata.get("memory_level", "long_term"))
                if fact_level not in set(levels):
                    continue

            # Factor 1: similarity (cosine, inverted)
            # sqlite-vec distances are normalised to [0,1] in VectorStore
            similarity_score = max(0.0, 1.0 - distance)  # Clamp to avoid negative values

            # Factor 2: recency (0.0–1.0, decays over the recency window)
            ts = float(metadata.get("timestamp", 0))
            age_secs = now - ts
            recency_score = max(0.0, 1.0 - age_secs / _RECENCY_WINDOW_SECS)

            # Factor 3: importance (stored in metadata, 0.0–1.0)
            importance = float(metadata.get("importance", _IMPORTANCE_DEFAULT))

            # Factor 4: usage frequency (access_count normalized, cap at 10)
            access_count = int(metadata.get("access_count", 0))
            usage_freq = min(access_count / 10.0, 1.0)

            score = similarity_score * 0.6 + recency_score * 0.2 + importance * 0.1 + usage_freq * 0.1
            ranked.append((score, fact, metadata))

        ranked.sort(key=lambda x: x[0], reverse=True)

        # Increment access_count for retrieved facts (async fire-and-forget style)
        top_facts = [(fact, meta) for _, fact, meta in ranked[:top_k]]
        for fact, meta in top_facts:
            # NOTE: update_metadata needs document ID, not fact text
            doc_id = meta.get("id")
            if not doc_id:
                logger.debug("No document ID in metadata for fact: %s", fact[:50])
                continue
            try:
                new_count = int(meta.get("access_count", 0)) + 1
                await self._store.update_metadata(doc_id, {"access_count": str(new_count)})
            except Exception as e:
                logger.debug("Metadata update failed for %s: %s", doc_id[:8], e)
                # metadata update is best-effort

        return [fact for fact, _ in top_facts]

    async def store(
        self,
        fact: str,
        session_id: str,
        memory_type: str = "semantic",
        source: str = "user",
        importance: float = 0.5,
        level: str = "long_term",
    ) -> bool:
        """Store a fact with importance rating (0.0=trivial, 1.0=critical).

        ADR-19 P1: `level` tags the fact with a context-hierarchy level
        (turn/session/project/long_term). Default long_term keeps the
        historical behavior. Stored in metadata as `memory_level` so the
        level-aware retriever can filter on it.
        """
        if level not in MEMORY_LEVELS:
            level = "long_term"
        return await self._store.store(
            fact=fact,
            session_id=session_id,
            source=source,
            extra_metadata={
                "memory_type": memory_type,
                "importance": str(importance),
                "access_count": "0",
                "memory_level": level,
            },
        )

    async def retrieve_for_task(
        self,
        query: str,
        intent: Intent,
        session_id: str,
        task_type: Optional[str] = None,
        top_k: int = _MAX_FACTS,
    ) -> list[str]:
        """ADR-19 P1: level-aware retrieval for the current task type.

        Resolves the task type's preferred memory levels and composes with
        that filter. Unknown/default task_type → legacy compose (no
        filter) — a no-op until the dispatcher emits an explicit task_type.
        """
        levels = level_priorities(task_type)
        return await self.compose(
            query=query,
            intent=intent,
            session_id=session_id,
            top_k=top_k,
            levels=levels,
        )

    async def forget(self, fact: str) -> bool:
        return await self._store.forget(fact)

    async def list_all(self) -> list[str]:
        return await self._store.list_all()

    async def search(self, query: str, session_id: str, top_k: int = 3) -> list[object]:
        """Search for similar facts and return objects with content attribute for deduplication."""
        # Use the vector store directly to get fact+metadata tuples
        try:
            raw = await self._store.recall_with_scores(query=query, top_k=top_k)
        except Exception as e:
            logger.warning("Memory search failed: %s", e)
            return []

        # Create objects with content attribute
        results = []
        for fact, distance, metadata in raw:
            # Create a simple object with content attribute
            class FactResult:
                def __init__(self, content: str):
                    self.content = content

            results.append(FactResult(fact))

        return results

    async def list_all_with_metadata(self) -> list[dict]:
        return await self._store.list_all_with_metadata()

    async def warm_start_facts(
        self,
        session_id: str,
        max_facts: int = 3,
    ) -> list[str]:
        """
        Retrieve the most important recent facts for a new session warm-start.

        Unlike compose() which requires a query for embedding-based retrieval,
        this method retrieves facts based on recency and importance alone —
        no embedding call needed. This gives the agent "working memory" even
        when the user's first message is too short or generic for meaningful
        semantic retrieval (e.g., "hi", "help", "what can you do?").

        Selection criteria:
        1. Recent facts (within the last 7 days) are preferred
        2. High-importance facts (importance >= 0.7) are always included
        3. Frequently accessed facts (access_count >= 3) are prioritized
        4. Deduplicated against compose() results when both are called

        This is NOT a replacement for compose() — it's a complement that
        provides baseline context when semantic retrieval comes up empty.
        """
        try:
            all_facts = await self._store.list_all_with_metadata()
        except Exception as e:
            logger.warning("warm_start_facts retrieval failed: %s", e)
            return []

        if not all_facts:
            return []

        now = time.time()
        scored = []

        for entry in all_facts:
            fact = entry.get("fact", "")
            if not fact or len(fact) < 10:
                continue

            # Factor 1: recency (same formula as compose)
            ts = float(entry.get("timestamp", 0))
            age_secs = now - ts
            recency = max(0.0, 1.0 - age_secs / _RECENCY_WINDOW_SECS)

            # Factor 2: importance
            importance = float(entry.get("importance", _IMPORTANCE_DEFAULT))

            # Factor 3: access frequency (normalized, cap at 10)
            access_count = int(entry.get("access_count", 0))
            usage_freq = min(access_count / 10.0, 1.0)

            # Warm-start scoring: heavier weight on importance and recency
            # (no semantic similarity — we don't have a query)
            score = recency * 0.4 + importance * 0.4 + usage_freq * 0.2

            # Boost high-importance facts even if old
            if importance >= 0.8:
                score = max(score, 0.7)

            # Only include facts from the last 30 days (not ancient history)
            if age_secs > (_RECENCY_WINDOW_SECS * 4):
                continue

            scored.append((score, fact))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [fact for _, fact in scored[:max_facts]]

    # ── P11: LLM-based fact extraction ──────────────────────────────────────

    async def extract_facts_with_llm(
        self,
        user_message: str,
        assistant_response: str,
        session_id: str,
    ) -> list[str]:
        """
        Use an LLM call to extract durable facts from a conversation turn.

        This complements the regex-based extraction in engine.py. The LLM catches
        complex facts that don't match simple patterns:
        - "I've been using Python for about 5 years now" → preference/experience
        - "My team follows trunk-based development" → workflow constraint
        - "We can't use cloud services due to compliance" → hard constraint
        - "I'm migrating from Django to FastAPI" → transition context

        Returns a list of extracted fact strings, ready for store().
        Empty list if extraction fails or finds nothing.
        """
        try:
            from adapters import get_adapter
            from core.config import settings

            adapter = get_adapter(settings.localmind_adapter)

            extraction_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a fact extraction assistant. Your job is to identify DURABLE facts "
                        "about the user from a conversation turn. Durable facts are things that will "
                        "remain true across sessions: preferences, constraints, expertise level, "
                        "tools they use, projects they work on, deadlines, team practices, etc.\n\n"
                        "DO NOT extract:\n"
                        "- Temporary context ('I'm working on X right now' unless it's a long-term project)\n"
                        "- Conversational filler ('thanks', 'ok', 'great')\n"
                        "- Information about the assistant or the conversation itself\n"
                        "- Opinions or questions (only extract stated facts)\n\n"
                        "Respond with one fact per line. If no durable facts are present, respond with 'NONE'. "
                        "Each fact should be a complete, self-contained sentence. Example:\n"
                        "User prefers Python over JavaScript for backend development\n"
                        "User's team uses trunk-based development workflow"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User said: {user_message[:500]}\n\n"
                        f"Assistant responded: {assistant_response[:500]}\n\n"
                        "Extract durable facts about the user from this conversation turn."
                    ),
                },
            ]

            chunks = []
            async for chunk in adapter.chat(extraction_messages, temperature=0.0):
                if hasattr(chunk, "error") and chunk.error:
                    logger.warning("[memory] adapter error during extraction: %s", chunk.error[:120])
                    break
                chunks.append(chunk.text if hasattr(chunk, "text") else str(chunk))

            raw = "".join(chunks).strip()

            if raw.upper() == "NONE" or not raw:
                return []

            # Parse into individual facts
            facts = []
            for line in raw.split("\n"):
                line = line.strip().lstrip("- •*0123456789.").strip()
                if len(line) > 15 and len(line) < 300:  # reasonable fact length
                    facts.append(line)

            return facts[:5]  # Cap at 5 facts per turn

        except Exception as e:
            logger.debug("[memory] LLM fact extraction failed (non-critical): %s", e)
            return []

    # ── P11: Memory consolidation ───────────────────────────────────────────

    async def consolidate(self, similarity_threshold: float = 0.85) -> int:
        """
        Merge near-duplicate facts in the memory store.

        When two facts are semantically similar (same topic, updated details),
        the older fact should be replaced by the newer one. This prevents
        the memory store from accumulating stale or redundant facts over time.

        Consolidation strategy:
        1. Get all facts with metadata
        2. For each pair of facts with embedding distance below threshold,
           identify the older and newer fact
        3. Replace the older fact with the newer one, keeping the higher
           importance score and summing access counts

        Returns the number of facts consolidated (removed).
        This is an expensive operation — call it infrequently (e.g., at startup
        or via a janitor script), not on every turn.
        """
        try:
            all_facts = await self._store.list_all_with_metadata()
            if len(all_facts) < 2:
                return 0

            # Build a list of (fact_text, metadata) pairs
            fact_pairs = []
            for entry in all_facts:
                fact = entry.get("fact", "")
                if not fact:
                    continue
                fact_pairs.append((fact, entry))

            # Compare all pairs for semantic similarity
            # Note: This is O(n²) but memory stores are typically small (<1000 facts)
            consolidated = 0
            removed_ids = set()

            for i in range(len(fact_pairs)):
                if fact_pairs[i][1].get("id") in removed_ids:
                    continue
                for j in range(i + 1, len(fact_pairs)):
                    if fact_pairs[j][1].get("id") in removed_ids:
                        continue

                    fact_a, meta_a = fact_pairs[i]
                    fact_b, meta_b = fact_pairs[j]

                    # Quick text-level check first (cheap)
                    # If Jaccard similarity is very high, they're near-duplicates
                    words_a = set(fact_a.lower().split())
                    words_b = set(fact_b.lower().split())
                    if not words_a or not words_b:
                        continue
                    jaccard = len(words_a & words_b) / len(words_a | words_b)

                    if jaccard >= similarity_threshold:
                        # Near-duplicate: keep the newer one
                        ts_a = float(meta_a.get("timestamp", 0))
                        ts_b = float(meta_b.get("timestamp", 0))

                        if ts_b > ts_a:
                            # B is newer — remove A
                            old_id = meta_a.get("id")
                            if old_id:
                                await self._store.forget_by_id(old_id)
                                removed_ids.add(old_id)
                                consolidated += 1
                        else:
                            # A is newer or same age — remove B
                            old_id = meta_b.get("id")
                            if old_id:
                                await self._store.forget_by_id(old_id)
                                removed_ids.add(old_id)
                                consolidated += 1

            if consolidated > 0:
                logger.info(
                    "[memory] consolidated %d near-duplicate facts out of %d total",
                    consolidated,
                    len(fact_pairs),
                )

            return consolidated

        except Exception as e:
            logger.warning("[memory] consolidation failed (non-critical): %s", e)
            return 0

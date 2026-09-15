"""
Memory tool — handles explicit memory operations.

For MEMORY_OP intent:
- "remember X" → stores X
- "what do you know about me" → lists all facts
- "forget X" → deletes X

The MemoryComposer handles passive retrieval during every turn.
This tool handles explicit user-initiated memory operations.

Registered as Intent.MEMORY_OP in the tool registry.
"""

from __future__ import annotations

import logging
import re
import time as _time

from core.memory_intent import extract_memory_content
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

_FORGET_PAT = re.compile(r"\b(forget|delete|remove)\b.{0,40}", re.IGNORECASE)
_LIST_PAT = re.compile(
    r"\b(what do you (know|remember)|list (all |my )?facts|show (me )?memory|recall all)\b",
    re.IGNORECASE,
)
# "recall X" / "search memory for X" — a targeted recall of
# facts matching X. The schema advertises operation=recall; without this the
# message fell through to the STORE path and stored "recall" as a junk fact.
_RECALL_PAT = re.compile(
    r"^\s*(?:please\s+)?(?:recall|search(?:\s+memory)?|find(?:\s+in\s+memory)?)\s+(.+)$",
    re.IGNORECASE,
)

# A durable fact should be a short, meaningful statement — not a
# raw paste. When the user said "remember this source" + a 6KB weather-JSON dump,
# the whole blob was stored verbatim as one "fact". Cap the size and distill: a
# large/dump-shaped blob that contains a URL is almost always "remember THIS
# source" — store the URL; a large blob with no URL is stored-as-garbage, so ask
# for the specific fact instead of persisting the wall of text.
_MAX_FACT_CHARS = 400
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)


def _looks_like_dump(text: str) -> bool:
    """Heuristic: raw tool output / JSON / a big paste rather than a stated fact."""
    if len(text) > _MAX_FACT_CHARS:
        return True
    stripped = text.lstrip()
    if stripped[:1] in "{[" and ('":' in text or '" :' in text):
        return True  # JSON-ish object/array
    # Many quoted key/value pairs across lines = structured dump, not prose.
    return text.count('":') >= 3


def _distill_fact(message: str, fact: str) -> tuple[str | None, str | None]:
    """Reduce a store request to a concise durable fact.

    Returns ``(fact_to_store, note)``:
      * ``(fact, None)``            — store ``fact`` as-is (already concise).
      * ``(distilled, note)``       — store ``distilled`` (e.g. a URL pulled from
                                       a paste); ``note`` explains what was kept.
      * ``(None, guidance)``        — do NOT store; return ``guidance`` asking the
                                       user for the specific fact.
    """
    fact = (fact or "").strip()
    if not _looks_like_dump(fact):
        return fact, None
    urls = _URL_RE.findall(fact)
    if urls:
        # De-dup preserving order; a "source"/"url" cue keeps the natural label.
        seen: list[str] = []
        for u in urls:
            if u not in seen:
                seen.append(u)
        label = "Source" if re.search(r"\bsource\b", message, re.IGNORECASE) else "URL"
        distilled = f"{label}: {seen[0]}" if len(seen) == 1 else f"{label}s: {', '.join(seen[:5])}"
        return distilled, f"kept the {label.lower()} from the pasted content"
    return None, (
        "That's a large block of text — I don't want to store the whole thing as one "
        "memory. Tell me the specific fact to remember, e.g. \"remember my weather "
        "source is https://wttr.in/{place}?format=j1\"."
    )


async def memory_op(
    message: str,
    content: str | None = None,
    memory_type: str | None = None,
) -> ToolResult:
    """
    Store, recall, or delete facts from persistent semantic memory.

    Args:
        message: the raw user message.
        content: optional pre-extracted fact (classifier output).
            When provided, it is stored VERBATIM instead of re-extracting
            with the regex below — the classifier's extraction is more
            accurate ("note down my project" must not store "down my
            project").
        memory_type: optional category tag (user_preference / user_fact /
            source_knowledge / project_decision / general). Falls back to
            "semantic" when not provided.
    """
    from storage.vector import VectorStore

    store = VectorStore()

    # ── List all facts ────────────────────────────────────────────────────
    if _LIST_PAT.search(message):
        facts = await store.list_all_with_metadata()
        if not facts:
            return ToolResult(
                content="No facts stored in memory yet.",
                risk=RiskLevel.LOW,
                source="memory",
            )
        lines = []
        for f in facts:
            mtype = f.get("memory_type", "?")
            imp = float(f.get("importance", 0.5))
            lines.append(f"- [{mtype} | importance={imp:.1f}] {f['fact']}")
        content = f"**Stored memory ({len(facts)} facts):**\n" + "\n".join(lines)
        return ToolResult(
            content=content,
            risk=RiskLevel.LOW,
            source="memory",
            metadata={"fact_count": len(facts)},
        )

    # ── Forget a fact ─────────────────────────────────────────────────────
    if _FORGET_PAT.search(message):
        # Extract what to forget — everything after the trigger word
        fact = re.sub(r"^\s*(forget|delete|remove)\b\s*", "", message, flags=re.IGNORECASE).strip()
        if fact:
            success = await store.forget(fact)
            if success:
                return ToolResult(
                    content=f"Removed from memory: *{fact}*",
                    risk=RiskLevel.LOW,
                    source="memory",
                )
        return ToolResult(
            content="Couldn't find that specific fact to remove. Try listing memory first.",
            risk=RiskLevel.LOW,
            source="memory",
        )

    # ── Recall a fact (targeted search) ──────────────────────────────────
    # The tool advertises operation=recall. Do a keyword match
    # over stored facts — this works even when embeddings are unavailable
    # (the fallback store writes plain text; vector search can't find it).
    _recall_m = _RECALL_PAT.match(message)
    # Bare "recall" (no query content) — the model sometimes emits the
    # operation without a query. Never fall through to STORE for a recall
    # intent: surface recent facts instead.
    if message.strip().lower().startswith("recall") and not _recall_m:
        return await _recall_recent(store)
    if _recall_m:
        query = _recall_m.group(1).strip()
        q_words = set(re.findall(r"\w+", query.lower()))
        if not q_words:
            return await _recall_recent(store)
        facts = await store.list_all_with_metadata()
        scored = []
        for f in facts:
            f_text = str(f.get("fact", "")).lower()
            f_words = set(re.findall(r"\w+", f_text))
            if not f_words:
                continue
            # Match on exact tokens OR prefix overlap ("prefer" ~
            # "preferences") so recalls work without embeddings.
            matched = 0
            for qw in q_words:
                if qw in f_words:
                    matched += 1
                elif any(qw.startswith(fw) or fw.startswith(qw) for fw in f_words):
                    matched += 1
            overlap = matched / max(1, len(q_words))
            if overlap >= 0.4:  # at least ~half the query words match
                scored.append((overlap, f["fact"]))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [fact for _, fact in scored[:3]]
        if not top:
            # Fallback: when nothing matches, surface the most recent facts
            # rather than an empty miss — better than telling the user
            # there's nothing when the store has content.
            recent = [f["fact"] for f in facts[-3:]]
            if recent:
                content = (
                    "I couldn't find a specific match, but here's what I have "
                    "stored recently:\n"
                    + "\n".join(f"- {f}" for f in reversed(recent))
                )
            else:
                content = "I couldn't find anything matching that in memory."
            return ToolResult(
                content=content,
                risk=RiskLevel.LOW,
                source="memory",
                metadata={"match_count": 0},
            )
        content = "**From memory:**\n" + "\n".join(f"- {f}" for f in top)
        return ToolResult(
            content=content,
            risk=RiskLevel.LOW,
            source="memory",
            metadata={"match_count": len(top)},
        )

    # ── Store a fact ──────────────────────────────────────────────────────
    # Use the classifier's extraction when provided — it handles
    # cue prefixes the regex misses ("note down", "keep in mind", "remember
    # this:" with punctuation). Without the shared extractor the framing
    # survives ("this: my project is called Falcon. Just acknowledge") and the
    # store keeps the user's instruction as the fact.
    fact = (content or "").strip() if content else extract_memory_content(message)
    if not fact:
        return ToolResult(
            content="I didn't catch what you'd like me to remember. Try: 'remember that I prefer Python'",
            risk=RiskLevel.LOW,
            source="memory",
        )

    # Distill a raw paste to a concise fact (or ask for one)
    # instead of persisting a wall of text as a single "memory".
    _distilled, _distill_note = _distill_fact(message, fact)
    if _distilled is None:
        return ToolResult(
            content=_distill_note or "Tell me the specific fact you'd like me to remember.",
            risk=RiskLevel.LOW,
            source="memory",
            metadata={"declined_reason": "content_too_large"},
        )
    fact = _distilled

    # Infer importance from wording
    importance = (
        0.8
        if any(w in message.lower() for w in ["always", "never", "prefer", "important", "critical"])
        else 0.5
    )

    # Use the canonical session_id so facts are retrievable in the same session scope.
    # Falls back to a named bucket for CLI/direct tool calls without a session.
    effective_session_id = "explicit_memory_op"
    success = await store.store(
        fact=fact,
        session_id=effective_session_id,
        source="user",
        extra_metadata={
            "memory_type": memory_type or "semantic",
            "importance": str(importance),
            "access_count": "0",
        },
    )

    # Fallback to plain SQLite storage when the vector store
    # fails (sqlite-vec not installed, embedding service unavailable, etc.)
    # The user should never see "Memory storage is unavailable" for a simple
    # "remember this" — the fact is stored as plain text in vector_facts
    # and retrievable by keyword match even without vector search.
    if not success:
        try:
            import json as _json
            import os as _os
            import sqlite3 as _sqlite3

            from core.config import settings

            db_path = _os.path.join(
                str(settings.localmind_home or _os.path.expanduser("~/LocalMind")),
                "localmind.db",
            )
            conn = _sqlite3.connect(db_path)
            # Ensure the table exists (VectorStore creates it, but it may not
            # have been created yet if VectorStore init failed)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vector_facts (
                    id          TEXT PRIMARY KEY,
                    content     TEXT NOT NULL,
                    metadata    TEXT NOT NULL DEFAULT '{}',
                    created_at  REAL NOT NULL DEFAULT (unixepoch('now'))
                )
            """)
            import uuid as _uuid
            metadata = _json.dumps({
                "session_id": effective_session_id,
                "source": "user",
                "memory_type": memory_type or "semantic",
                "importance": str(importance),
                "access_count": "0",
                "fallback": "true",  # stored without embedding
                # The vector path writes a timestamp; the fallback
                # MUST too, or warm_start_facts treats the fact as ancient and
                # the agent never sees it (age = now - 0 > 30 days → dropped).
                "timestamp": str(_time.time()),
            })
            conn.execute(
                "INSERT INTO vector_facts (id, content, metadata) VALUES (?, ?, ?)",
                (str(_uuid.uuid4()), fact, metadata),
            )
            conn.commit()
            conn.close()
            success = True
            logger.info("[memory_op] vector store failed — stored as plain text fallback")
        except Exception as fallback_exc:
            logger.warning("[memory_op] fallback storage also failed: %s", fallback_exc)

    if success:
        _msg = f"Remembered: *{fact}*"
        if _distill_note:
            _msg += f"\n\n(I {_distill_note} rather than storing the whole block.)"
        return ToolResult(
            content=_msg,
            risk=RiskLevel.LOW,
            source="memory",
            metadata={"fact": fact, "importance": importance},
        )
    return ToolResult(
        content="Got it — I'll remember that.",
        risk=RiskLevel.LOW,
        source="memory",
        success=False,
    )


async def _recall_recent(store) -> ToolResult:
    """Surface the most recent stored facts (bare/no-match recall).

    A recall intent must NEVER fall through to the store path
    (which persisted "recall" as a junk fact). When there's no query or no
    match, show what's actually stored.
    """
    facts = await store.list_all_with_metadata()
    if not facts:
        return ToolResult(
            content="No facts stored in memory yet.",
            risk=RiskLevel.LOW,
            source="memory",
        )
    recent = [f["fact"] for f in facts[-3:]]
    content = "**From memory (recent):**\n" + "\n".join(f"- {f}" for f in reversed(recent))
    return ToolResult(
        content=content,
        risk=RiskLevel.LOW,
        source="memory",
        metadata={"match_count": len(recent)},
    )


# Register
register_tool(
    Intent.MEMORY_OP,
    memory_op,
    description="Store, recall, or delete facts from persistent semantic memory",
    cost=0.01,
    latency_ms=200,
)

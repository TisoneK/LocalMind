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

from core.memory_intent import (
    MemoryDurability,
    canonical_key,
    durability_profile,
    extract_memory_content,
)
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
# A fact id as the list output prints it ("#3f2a91cd") or a full 16-char id.
# Ids make a specific fact addressable — the user can see one and ask for it
# back without quoting the stored wording.
_FACT_ID_RE = re.compile(r"(?:#\s*)?\b([0-9a-f]{8,16})\b", re.IGNORECASE)

# The tool schema advertises operation = store|recall|forget|list, so the
# dispatcher can hand us the operation WORD alone ("list", no content). That
# must mean that operation: it used to fall through to the store path and
# persist "list" as a fact, which is both a junk memory and a garbled list.
# Exact word (plus optional colon) only — "list my project files" is not a
# memory listing.
_BARE_OP_RE = re.compile(r"^(store|recall|forget|list|facts|memory)\s*[:;]?\s*$", re.IGNORECASE)
_LIST_WORDS = {"list", "facts", "memory"}

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

    # A bare operation word is that operation, not a fact to store.
    _bare = _BARE_OP_RE.match(message.strip())
    _bare_word = _bare.group(1).lower() if _bare else ""
    if _bare_word == "recall":
        return await _recall_recent(store)
    if _bare_word == "forget":
        return ToolResult(
            content=(
                "Which fact should I remove? Ask me to list memory and give me its id, "
                "or quote the fact."
            ),
            risk=RiskLevel.LOW,
            source="memory",
        )
    if _bare_word == "store":
        return ToolResult(
            content="What should I remember? Give me the fact and I'll keep it.",
            risk=RiskLevel.LOW,
            source="memory",
        )

    # ── List all facts ────────────────────────────────────────────────────
    if _LIST_PAT.search(message) or _bare_word in _LIST_WORDS:
        return await _list_facts(store)

    # ── Forget a fact ─────────────────────────────────────────────────────
    if _FORGET_PAT.search(message):
        # Extract what to forget — everything after the trigger word. A
        # discourse marker ("forget THAT I prefer dark mode") is part of the
        # sentence, not of the stored fact, so it goes too.
        fact = re.sub(
            r"^\s*(?:forget|delete|remove)\b\s*(?:that\s+|about\s+|the fact that\s+)?",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip()
        if fact:
            return await _forget_with_read_back(store, fact)
        return ToolResult(
            content=(
                "Tell me which fact to remove — for example \"forget that I prefer dark mode\" "
                "or \"forget #3f2a91cd\" from the list."
            ),
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

    # Durability policy, enforced here rather than asked for in the prompt:
    # a live value is refused at the door. Storing one guarantees a stale fact
    # the agent later has to hunt down, and the prompt that asked nicely does
    # not hold on every model.
    _durability = durability_profile(fact)
    if _durability.kind is MemoryDurability.VOLATILE:
        return ToolResult(
            content=(
                f"I'd rather not keep *{fact}* — {_durability.reason}. "
                "Ask me for it and I'll read it fresh instead. If part of that is "
                "durable, tell me that part and I'll keep it."
            ),
            risk=RiskLevel.LOW,
            source="memory",
            metadata={"declined_reason": "volatile_fact", "fact": fact},
        )

    # Infer importance from wording
    importance = (
        0.8
        if any(w in message.lower() for w in ["always", "never", "prefer", "important", "critical"])
        else 0.5
    )

    # Use the canonical session_id so facts are retrievable in the same session scope.
    # Falls back to a named bucket for CLI/direct tool calls without a session.
    effective_session_id = "explicit_memory_op"
    _key = canonical_key(fact)
    _metadata = {
        "memory_type": memory_type or "semantic",
        "importance": str(importance),
        "access_count": "0",
        "memory_key": _key,
        "memory_kind": _durability.kind.value,
        "memory_freshness": _durability.freshness,
        "memory_confidence": str(_durability.confidence),
    }
    success = await store.store(
        fact=fact,
        session_id=effective_session_id,
        source="user",
        extra_metadata=_metadata,
        key=_key,
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
            metadata = _json.dumps({
                "session_id": effective_session_id,
                "source": "user",
                "fallback": "true",  # stored without embedding
                # The vector path writes a timestamp; the fallback
                # MUST too, or warm_start_facts treats the fact as ancient and
                # the agent never sees it (age = now - 0 > 30 days → dropped).
                "timestamp": str(_time.time()),
                **_metadata,
            })
            # Keyed id + REPLACE, not a fresh uuid: a write that cannot embed
            # must still land on the fact's one row, or every re-statement
            # appends another copy (this is how the same fact ended up stored
            # several times over while embeddings were unavailable).
            conn.execute(
                "INSERT OR REPLACE INTO vector_facts (id, content, metadata) VALUES (?, ?, ?)",
                (store.fact_id_for_key(_key), fact, metadata),
            )
            conn.commit()
            conn.close()
            success = True
            logger.info("[memory_op] vector store failed — stored as plain text fallback")
        except Exception as fallback_exc:
            logger.warning("[memory_op] fallback storage also failed: %s", fallback_exc)

    if not success:
        # Never present intent as state: without a write there is nothing to
        # claim, and a cheerful "I'll remember that" is a lie the user only
        # discovers later.
        return ToolResult(
            content=(
                "That didn't reach memory — the store refused the write. "
                "Want me to try again?"
            ),
            risk=RiskLevel.LOW,
            source="memory",
            success=False,
            metadata={"fact": fact, "stored": False},
        )

    # Read back before claiming anything: the confirmation reports the state
    # that is actually in the store, not the state the write intended. A store
    # that fails the read is an unverified write, never a raised turn.
    try:
        _verified = await store.find_by_key(_key)
    except Exception as exc:  # pragma: no cover - store failure is environment
        logger.warning("[memory_op] read-back failed: %s", exc)
        _verified = None
    if _verified is None:
        return ToolResult(
            content=(
                f"I tried to store *{fact}* but it isn't there when I read memory "
                "back — so I won't claim it's saved. Want me to try again?"
            ),
            risk=RiskLevel.LOW,
            source="memory",
            success=False,
            metadata={"fact": fact, "stored": False, "verified": False},
        )

    _msg = f"Remembered: *{fact}*"
    if _distill_note:
        _msg += f"\n\n(I {_distill_note} rather than storing the whole block.)"
    return ToolResult(
        content=_msg,
        risk=RiskLevel.LOW,
        source="memory",
        metadata={
            "fact": fact,
            "fact_id": _verified.get("id", ""),
            "importance": importance,
            "memory_kind": _durability.kind.value,
            "stored": True,
            "verified": True,
        },
    )


async def _list_facts(store) -> ToolResult:
    """List every stored fact, each named by the short id it can be acted on."""
    facts = await store.list_all_with_metadata()
    if not facts:
        return ToolResult(
            content="No facts stored in memory yet.",
            risk=RiskLevel.LOW,
            source="memory",
            metadata={"fact_count": 0, "fact_ids": []},
        )
    lines = []
    for f in facts:
        mtype = f.get("memory_type", "?")
        imp = float(f.get("importance", 0.5))
        # The short id is load-bearing: it is how a single fact is named later
        # (forget/recall) without re-quoting its wording.
        lines.append(f"- #{str(f.get('id', ''))[:8]} [{mtype} | importance={imp:.1f}] {f['fact']}")
    content = f"**Stored memory ({len(facts)} facts):**\n" + "\n".join(lines)
    return ToolResult(
        content=content,
        risk=RiskLevel.LOW,
        source="memory",
        metadata={"fact_count": len(facts), "fact_ids": [f.get("id", "") for f in facts]},
    )


async def _forget_with_read_back(store, target: str) -> ToolResult:
    """Remove the facts `target` names, then report from the state it left.

    The failure this closes is a claim, not a deletion: "Done — I've cleaned up
    your memory entry" arriving while the row was still there. So the message
    is built from a read-back AFTER the delete, and a miss says so plainly
    instead of reusing the old "couldn't find that" line for both cases.
    """
    candidates: list[str] = []
    id_match = _FACT_ID_RE.search(target)
    if id_match:
        token = id_match.group(1)
        # An explicit id: either marked with "#" as the list prints it, a full
        # 16-char id, or the whole target being the id token.
        if "#" in id_match.group(0) or len(token) == 16 or _content_words(target) == 1:
            candidates.append(token)
    candidates.extend(store.matching_ids(target))
    candidates = list(dict.fromkeys(candidates))

    if not candidates:
        total = await store.count()
        if total:
            return ToolResult(
                content=(
                    f"Nothing in memory matches *{target}* — {total} fact(s) are stored; "
                    "ask me to list them and I'll show you their ids."
                ),
                risk=RiskLevel.LOW,
                source="memory",
                metadata={"removed": 0},
            )
        return ToolResult(
            content="There's nothing in memory to remove yet.",
            risk=RiskLevel.LOW,
            source="memory",
            metadata={"removed": 0},
        )

    for fact_id in candidates:
        await store.forget_by_id(fact_id)

    still_there = [fid for fid in candidates if await store.get_fact(fid) is not None]
    removed = len(candidates) - len(still_there)
    if not removed:
        return ToolResult(
            content=(
                f"I couldn't remove *{target}* — it's still in memory. "
                "Nothing was deleted, so tell me again if you want it gone."
            ),
            risk=RiskLevel.LOW,
            source="memory",
            success=False,
            metadata={"removed": 0, "remaining": len(still_there)},
        )

    _msg = f"Removed from memory: *{target}*"
    if removed > 1:
        _msg += f" ({removed} matching facts)"
    if still_there:
        _msg += f" — {len(still_there)} matching entr(y/ies) could not be removed."
    return ToolResult(
        content=_msg,
        risk=RiskLevel.LOW,
        source="memory",
        metadata={"removed": removed, "remaining": len(still_there)},
    )


def _content_words(text: str) -> int:
    """How many words carry meaning — "#3f2a91cd" is one, a sentence is not."""
    return len(re.findall(r"[a-z0-9]+", (text or "").lower()))


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

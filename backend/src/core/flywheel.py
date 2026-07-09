"""
Flywheel Logger — v1.0

Captures every routing decision and behavioral signal needed to build a
self-improving classifier. The hot path writes to a WAL-mode SQLite table
in microseconds. The Janitor script reads it offline.

Schema
──────
flywheel_events
  id            TEXT  PK  — uuid4 hex
  ts            REAL      — unix timestamp
  session_id    TEXT      — for rephrase detection (same session proximity)
  query         TEXT      — the raw user message
  rule_scores   TEXT      — JSON dict {intent_value: score}
  final_intent  TEXT      — the intent the router acted on
  final_conf    REAL      — confidence at decision time
  zone          TEXT      — green | amber | red
  path          TEXT      — resolution_path for debugging
  llm_result    TEXT      — what the LLM said (null if timed out)
  llm_conf      REAL      — LLM confidence (null if timed out)
  outcome       TEXT      — null → "correct" | "wrong" | "wrong_tool_params" (filled by Janitor)
  target_label  TEXT      — null → correct intent (filled by Janitor or rephrase detector)

flywheel_rephrases
  id            TEXT  PK
  ts            REAL
  session_id    TEXT
  query_a_id    TEXT  FK → flywheel_events.id
  query_b_id    TEXT  FK → flywheel_events.id
  similarity    REAL
  delta_secs    REAL
  — Populated by the rephrase detector on every new event.
  — Janitor uses this table to auto-label query_a as "wrong".

Behavioral signal detection
───────────────────────────
On every log() call, the logger looks back at the last N events in the same
session (in-memory ring buffer — no extra DB read). If the new query arrives
within REPHRASE_WINDOW_SECS and is Jaccard-similar to the previous one but
resolves to a different intent, it files a rephrase record and marks the
previous event's outcome as "wrong".

This gives the Janitor pre-labeled data without needing any user interaction.
"""

from __future__ import annotations

import collections
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# How close in time two queries must be to count as a rephrase (seconds).
REPHRASE_WINDOW_SECS: float = 15.0

# Jaccard similarity above which two queries are "probably about the same thing".
REPHRASE_SIMILARITY_THRESHOLD: float = 0.40

# How many recent events per session to keep in the in-memory buffer for
# rephrase detection. Low number — we only care about the immediately
# preceding query.
_SESSION_BUFFER_SIZE: int = 3

# Only log Amber and Red zone events by default — Green events are high-
# confidence and add noise to the training set. Set to True to log everything
# (useful during development to verify coverage).
LOG_GREEN_ZONE: bool = False


@dataclass
class _RecentEvent:
    event_id: str
    ts: float
    intent: str
    query: str


class FlywheelLogger:
    """
    Thread-safe flywheel event logger.

    One instance per process. The Engine / RiskAwareRouter holds a reference.
    The Janitor script reads the DB directly.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from core.config import settings

            db_path = settings.localmind_db_path
        self._db_path = db_path
        self._lock = threading.Lock()
        # Per-session ring buffer: {session_id: deque[_RecentEvent]}
        self._session_buf: dict[str, collections.deque] = {}
        self._init_db()

    # ── Setup ─────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self) -> None:
        try:
            conn = self._connect()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS flywheel_events (
                    id           TEXT PRIMARY KEY,
                    ts           REAL NOT NULL,
                    session_id   TEXT NOT NULL DEFAULT '',
                    query        TEXT NOT NULL,
                    rule_scores  TEXT NOT NULL DEFAULT '{}',
                    final_intent TEXT NOT NULL,
                    final_conf   REAL NOT NULL,
                    zone         TEXT NOT NULL,
                    path         TEXT NOT NULL DEFAULT '',
                    llm_result   TEXT,
                    llm_conf     REAL,
                    outcome      TEXT,
                    target_label TEXT
                );

                CREATE INDEX IF NOT EXISTS fw_ts ON flywheel_events(ts);
                CREATE INDEX IF NOT EXISTS fw_session ON flywheel_events(session_id, ts);
                CREATE INDEX IF NOT EXISTS fw_zone ON flywheel_events(zone);
                CREATE INDEX IF NOT EXISTS fw_outcome ON flywheel_events(outcome);

                CREATE TABLE IF NOT EXISTS flywheel_rephrases (
                    id          TEXT PRIMARY KEY,
                    ts          REAL NOT NULL,
                    session_id  TEXT NOT NULL,
                    query_a_id  TEXT NOT NULL,
                    query_b_id  TEXT NOT NULL,
                    similarity  REAL NOT NULL,
                    delta_secs  REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS fwr_session ON flywheel_rephrases(session_id);
                CREATE INDEX IF NOT EXISTS fwr_a ON flywheel_rephrases(query_a_id);
            """)
            conn.commit()
            conn.close()
            logger.debug("[flywheel] DB ready at %s", self._db_path)
        except Exception as exc:
            logger.error("[flywheel] DB init failed: %s", exc)

    # ── Behavioral feedback ─────────────────────────────────────────────

    def get_intent_accuracy(self, min_samples: int = 5) -> dict[str, float]:
        """
        Compute per-intent accuracy from flywheel events.

        Returns a dict mapping intent_value → accuracy (0.0–1.0).
        Only includes intents with at least `min_samples` labeled events
        (correct or wrong). Intents with fewer samples are omitted —
        the data is too sparse to be actionable.

        Used by the router to auto-adjust confidence thresholds:
        intents with low accuracy get a confidence penalty, making the
        router more cautious about routing to them.
        """
        try:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    """
                    SELECT final_intent,
                           COUNT(*) as total,
                           SUM(CASE WHEN outcome = 'correct' THEN 1 ELSE 0 END) as correct
                    FROM flywheel_events
                    WHERE outcome IS NOT NULL
                    GROUP BY final_intent
                    HAVING COUNT(*) >= ?
                """,
                    (min_samples,),
                ).fetchall()
                conn.close()

            accuracy = {}
            for row in rows:
                total = row["total"]
                correct = row["correct"]
                accuracy[row["final_intent"]] = correct / total if total > 0 else 0.0
            return accuracy
        except Exception as exc:
            logger.debug("[flywheel] intent_accuracy query failed: %s", exc)
            return {}

    def get_zone_error_rate(self, zone: str, min_samples: int = 3) -> float:
        """
        Compute the error rate for a specific zone (green/amber/red).

        Returns the fraction of events in this zone that were later
        labeled 'wrong'. Returns 0.0 if there aren't enough samples.

        Used to auto-adjust zone thresholds: if the amber zone has a
        high error rate, we can raise AMBER_THRESHOLD to route more
        queries to the LLM for confirmation.
        """
        try:
            with self._lock:
                conn = self._connect()
                row = conn.execute(
                    """
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN outcome = 'wrong' THEN 1 ELSE 0 END) as wrong
                    FROM flywheel_events
                    WHERE zone = ? AND outcome IS NOT NULL
                """,
                    (zone,),
                ).fetchone()
                conn.close()

            if row and row["total"] >= min_samples:
                return row["wrong"] / row["total"] if row["total"] > 0 else 0.0
            return 0.0
        except Exception as exc:
            logger.debug("[flywheel] zone_error_rate query failed: %s", exc)
            return 0.0

    # ── Public API ────────────────────────────────────────────────────────

    def log(
        self,
        query: str,
        session_id: str,
        query_id: str,
        rule_scores: dict[str, float],
        final_intent: str,
        final_conf: float,
        zone: str,
        path: str,
        llm_result: Optional[str],
        llm_conf: Optional[float],
    ) -> str:
        """
        Record a routing decision. Returns the event ID.
        Silently drops write errors — logging must never affect the hot path.
        """
        if zone == "green" and not LOG_GREEN_ZONE:
            return ""

        event_id = query_id or uuid.uuid4().hex
        ts = time.time()

        try:
            with self._lock:
                conn = self._connect()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO flywheel_events
                        (id, ts, session_id, query, rule_scores, final_intent,
                         final_conf, zone, path, llm_result, llm_conf)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        ts,
                        session_id,
                        query,
                        json.dumps(rule_scores),
                        final_intent,
                        final_conf,
                        zone,
                        path,
                        llm_result,
                        llm_conf,
                    ),
                )
                conn.commit()

                # Rephrase detection — compare against recent events in the same session.
                rephrase = self._detect_rephrase(
                    conn, event_id, ts, session_id, query, final_intent
                )
                if rephrase:
                    prev_id, similarity, delta = rephrase
                    rephrase_id = uuid.uuid4().hex
                    conn.execute(
                        """
                        INSERT INTO flywheel_rephrases
                            (id, ts, session_id, query_a_id, query_b_id, similarity, delta_secs)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (rephrase_id, ts, session_id, prev_id, event_id, similarity, delta),
                    )
                    # Auto-label the previous event as wrong.
                    conn.execute(
                        "UPDATE flywheel_events SET outcome = 'wrong', target_label = ? WHERE id = ?",
                        (final_intent, prev_id),
                    )
                    conn.commit()
                    logger.info(
                        "[flywheel] rephrase detected: prev=%s sim=%.2f Δ=%.1fs → prev labeled 'wrong'",
                        prev_id[:8],
                        similarity,
                        delta,
                    )

                conn.close()

                # Update in-memory session buffer.
                buf = self._session_buf.setdefault(
                    session_id, collections.deque(maxlen=_SESSION_BUFFER_SIZE)
                )
                buf.append(_RecentEvent(event_id=event_id, ts=ts, intent=final_intent, query=query))

        except Exception as exc:
            logger.debug("[flywheel] write failed (non-critical): %s", exc)

        return event_id

    def mark_tool_failure(self, event_id: str, reason: str = "wrong_tool_params") -> None:
        """
        Called by the engine when a tool dispatch fails (null result / exception).
        Provides the structural feedback signal described in the architecture doc.
        """
        if not event_id:
            return
        try:
            with self._lock:
                conn = self._connect()
                conn.execute(
                    "UPDATE flywheel_events SET outcome = ? WHERE id = ? AND outcome IS NULL",
                    (reason, event_id),
                )
                conn.commit()
                conn.close()
        except Exception as exc:
            logger.debug("[flywheel] mark_tool_failure non-critical: %s", exc)

    def mark_correct(self, event_id: str) -> None:
        """Explicitly mark an event as correct (e.g. from explicit user thumbs-up)."""
        if not event_id:
            return
        try:
            with self._lock:
                conn = self._connect()
                conn.execute(
                    "UPDATE flywheel_events SET outcome = 'correct' WHERE id = ? AND outcome IS NULL",
                    (event_id,),
                )
                conn.commit()
                conn.close()
        except Exception as exc:
            logger.debug("[flywheel] mark_correct non-critical: %s", exc)

    def get_recent_error_patterns(self, limit: int = 5) -> list[dict]:
        """
        Return recent wrong/outcome events for reflection context.

        Each entry contains: query, final_intent, zone, target_label (what it
        should have been). This gives the reflection step historical context
        about what the system has gotten wrong recently — so it can be extra
        cautious in those areas.

        Used by _reflect_on_answer() to inject error awareness into the
        reflection prompt. This is the key P10 improvement: reflection isn't
        just about the current answer, it's informed by historical mistakes.
        """
        try:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    """
                    SELECT query, final_intent, zone, target_label
                    FROM flywheel_events
                    WHERE outcome = 'wrong'
                    ORDER BY ts DESC
                    LIMIT ?
                """,
                    (limit,),
                ).fetchall()
                conn.close()

            return [
                {
                    "query": row["query"][:100],
                    "routed_to": row["final_intent"],
                    "should_have_been": row["target_label"],
                    "zone": row["zone"],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.debug("[flywheel] recent_error_patterns failed: %s", exc)
            return []

    # ── Rephrase detection ────────────────────────────────────────────────

    def _detect_rephrase(
        self,
        conn: sqlite3.Connection,
        current_id: str,
        current_ts: float,
        session_id: str,
        query: str,
        current_intent: str,
    ) -> Optional[tuple[str, float, float]]:
        """
        Compare the current query against the in-memory session buffer.
        Returns (prev_event_id, similarity, delta_secs) if a rephrase is detected,
        None otherwise.

        A rephrase requires:
          1. Same session, within REPHRASE_WINDOW_SECS.
          2. High Jaccard similarity (same topic).
          3. Different resolved intent (the first resolution was probably wrong).
        """
        buf = self._session_buf.get(session_id)
        if not buf:
            return None

        query_words = set(query.lower().split())

        for prev in reversed(buf):
            delta = current_ts - prev.ts
            if delta > REPHRASE_WINDOW_SECS:
                break  # buf is chronological; older entries won't qualify either
            if prev.intent == current_intent:
                continue  # same intent → not a correction
            prev_words = set(prev.query.lower().split())
            sim = _jaccard(query_words, prev_words)
            if sim >= REPHRASE_SIMILARITY_THRESHOLD:
                return prev.event_id, sim, delta

        return None


# ── Utilities ─────────────────────────────────────────────────────────────────


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

"""Boot-time system-info cache in SQLite.

Persists the structured snapshot from ``core.system_snapshot`` so the agent has
system knowledge WITHOUT calling the sysinfo tool. Volatility split:

  * STATIC fields (os, cpu, total RAM, hostname…) are written ONCE and SKIPPED
    on later boots — they don't change, so re-collecting is waste.
  * MUTATING fields (free/total disk, free RAM, uptime) are UPDATED every boot.

``refresh_at_boot()`` is called from the server lifespan startup; it is
best-effort and never raises (a failed cache must not block boot). Phase 3 wires
``get_summary()`` into the system prompt and ``get_all()`` into memory.
"""

from __future__ import annotations

import logging
import sqlite3
import time

from core.system_snapshot import collect_system_snapshot, format_system_summary

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_info (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- 'static' | 'mutating'
    updated_at  REAL NOT NULL
);
"""


class SystemInfoStore:
    def __init__(self, db_path: str):
        self._db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute(_SCHEMA)
        return conn

    def refresh_at_boot(self) -> dict[str, int]:
        """Collect a snapshot; INSERT static keys only if absent (skip), UPSERT
        mutating keys. Returns a small counters dict for logging. Never raises."""
        counters = {"static_new": 0, "static_skipped": 0, "mutating_updated": 0}
        try:
            snap = collect_system_snapshot()
            now = time.time()
            conn = self._connect()
            try:
                existing = {
                    row[0] for row in conn.execute(
                        "SELECT key FROM system_info WHERE kind='static'"
                    )
                }
                for key, value in snap.get("static", {}).items():
                    if key in existing:
                        counters["static_skipped"] += 1
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO system_info (key, value, kind, updated_at) "
                        "VALUES (?, ?, 'static', ?)",
                        (key, str(value), now),
                    )
                    counters["static_new"] += 1
                for key, value in snap.get("mutating", {}).items():
                    conn.execute(
                        "INSERT INTO system_info (key, value, kind, updated_at) "
                        "VALUES (?, ?, 'mutating', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                        (key, str(value), now),
                    )
                    counters["mutating_updated"] += 1
                conn.commit()
            finally:
                conn.close()
            logger.info(
                "[system_info] boot cache: %d static new, %d skipped, %d mutating updated",
                counters["static_new"], counters["static_skipped"], counters["mutating_updated"],
            )
        except Exception as exc:  # never block boot
            logger.warning("[system_info] boot cache refresh failed: %s", exc)
        return counters

    def get_all(self) -> dict[str, dict[str, str]]:
        """Return {'static': {...}, 'mutating': {...}} from the cache. Never raises."""
        out: dict[str, dict[str, str]] = {"static": {}, "mutating": {}}
        try:
            conn = self._connect()
            try:
                for key, value, kind in conn.execute("SELECT key, value, kind FROM system_info"):
                    out.setdefault(kind, {})[key] = value
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("[system_info] read failed: %s", exc)
        return out

    def get_summary(self) -> str:
        """Compact one-line `System:` summary from the cache (for prompt injection)."""
        data = self.get_all()
        return format_system_summary(data.get("static", {}), data.get("mutating", {}))

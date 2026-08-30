"""B-2026-08-30-17 Phase 2: boot-time system-info snapshot + cache.

The agent had zero system knowledge until it called the sysinfo tool (and
over-called it). These pin the structured snapshot + the DB cache's volatility
contract: static fields written once and SKIPPED on later boots, mutating fields
UPDATED every boot.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.system_snapshot import collect_system_snapshot, format_system_summary
from storage.system_info_store import SystemInfoStore


class TestSnapshot:
    def test_snapshot_has_static_and_mutating_and_never_raises(self):
        snap = collect_system_snapshot()
        assert set(snap.keys()) == {"static", "mutating"}
        # os + arch are available on every supported platform
        assert snap["static"].get("os")
        assert snap["static"].get("arch")
        # disk is the reliably-collectable mutating field cross-platform
        assert "disk_total_gb" in snap["mutating"]
        assert "snapshot_at" in snap["mutating"]

    def test_summary_is_a_compact_system_line(self):
        snap = collect_system_snapshot()
        summary = format_system_summary(snap["static"], snap["mutating"])
        assert summary.startswith("System:")
        assert snap["static"]["os"] in summary

    def test_summary_empty_when_nothing_collected(self):
        assert format_system_summary({}, {}) == ""


class TestSystemInfoStore:
    def _store(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        return SystemInfoStore(str(db))

    def test_static_written_once_then_skipped_mutating_updated(self):
        store = self._store()
        b1 = store.refresh_at_boot()
        assert b1["static_new"] > 0 and b1["mutating_updated"] > 0
        assert b1["static_skipped"] == 0
        # second boot: static already stored → SKIPPED, mutating → UPDATED
        b2 = store.refresh_at_boot()
        assert b2["static_new"] == 0
        assert b2["static_skipped"] == b1["static_new"]
        assert b2["mutating_updated"] > 0

    def test_get_all_and_summary_reflect_the_cache(self):
        store = self._store()
        store.refresh_at_boot()
        data = store.get_all()
        assert data["static"].get("os")
        assert "disk_total_gb" in data["mutating"]
        assert store.get_summary().startswith("System:")

    def test_refresh_never_raises_on_bad_db_path(self):
        # a directory that can't be opened as a db → best-effort, no raise
        bad = SystemInfoStore("/nonexistent-dir/definitely/not/here.db")
        counters = bad.refresh_at_boot()  # must not raise
        assert counters == {"static_new": 0, "static_skipped": 0, "mutating_updated": 0}

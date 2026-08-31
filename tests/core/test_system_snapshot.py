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


# ── Phase 3: the cached summary is injected into the first-call prompt ────────


def test_cached_summary_injected_into_bootstrap_prompt():
    from core.agent.prompts import build_agent_system_prompt
    from core.models import Intent
    from core.system_snapshot import set_cached_summary
    from tools import available_tools

    set_cached_summary("System: TestOS 1.0, x86_64, 4 CPUs, 8.6 GB RAM, 121 GB disk (4.3 GB free)")
    try:
        prompt = build_agent_system_prompt(
            intent=Intent.SHELL, available_tools=available_tools(),
            tool_defs=None, native_bootstrap=True,
        )
        assert "8.6 GB RAM" in prompt and "TestOS 1.0" in prompt
        assert "sysinfo" in prompt.lower()  # the "only call sysinfo for..." guidance
    finally:
        set_cached_summary("")


def test_no_system_section_when_cache_unset():
    from core.agent.prompts import _system_env_line
    from core.system_snapshot import set_cached_summary

    set_cached_summary("")
    assert _system_env_line() == ""


def test_cached_summary_injected_into_chat_prompt():
    """A system question routed to conversation mode (Intent.CHAT) also carries
    the system summary, so the agent answers from it without a tool."""
    from core.agent.prompts import build_agent_system_prompt
    from core.models import Intent
    from core.system_snapshot import set_cached_summary
    from tools import available_tools

    set_cached_summary("System: TestOS 9, arm64, 8 CPUs, 16 GB RAM, 500 GB disk")
    try:
        prompt = build_agent_system_prompt(
            intent=Intent.CHAT, available_tools=available_tools(), tool_defs=None,
        )
        assert "16 GB RAM" in prompt and "TestOS 9" in prompt
    finally:
        set_cached_summary("")

"""Structured system snapshot — the data layer for boot-time sysinfo caching.

B-2026-08-30-17 Phase 2: the agent had ZERO system knowledge until it called the
`sysinfo` tool (and over-called it). This collects a compact, STRUCTURED snapshot
split by volatility so the boot cache can store STATIC fields once and refresh
only the MUTATING ones each boot:

  * static   — OS, arch, CPU, hostname, total RAM, python (don't change per boot)
  * mutating — free/total disk, free RAM, uptime (refresh every boot)

Everything is best-effort and cross-platform: a collector that can't read a field
is simply omitted — this MUST never raise (it runs during server startup).
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import socket
import time

logger = logging.getLogger(__name__)

# B-2026-08-30-17 Phase 3: the compact `System:` summary is computed ONCE at
# boot (from the DB cache) and held here, so the hot prompt-assembly path injects
# it without a DB read every turn. Empty until the boot hook sets it.
_CACHED_SUMMARY = ""


def set_cached_summary(summary: str) -> None:
    global _CACHED_SUMMARY
    _CACHED_SUMMARY = summary or ""


def get_cached_summary() -> str:
    """The boot-cached `System: …` line for prompt injection (empty if unset)."""
    return _CACHED_SUMMARY


def _try(fn):
    try:
        return fn()
    except Exception:
        return None


def _total_ram_gb() -> float | None:
    # POSIX (Linux/macOS): pages * page size.
    try:
        names = getattr(os, "sysconf_names", {})
        if "SC_PHYS_PAGES" in names and "SC_PAGE_SIZE" in names:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            return round(total / 1e9, 1)
    except (ValueError, OSError):
        pass
    return None


def _free_ram_gb() -> float | None:
    # Linux exposes available pages; macOS/Windows need platform tools — best-effort.
    try:
        names = getattr(os, "sysconf_names", {})
        if "SC_AVPHYS_PAGES" in names and "SC_PAGE_SIZE" in names:
            free = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            return round(free / 1e9, 1)
    except (ValueError, OSError):
        pass
    # Linux /proc fallback
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) * 1024 / 1e9, 1)
    except OSError:
        pass
    return None


def _uptime_seconds() -> float | None:
    try:
        with open("/proc/uptime") as fh:  # Linux
            return float(fh.read().split()[0])
    except OSError:
        pass
    return None


def collect_system_snapshot() -> dict[str, dict]:
    """Return ``{"static": {...}, "mutating": {...}}`` — never raises."""
    static: dict[str, str] = {}
    mutating: dict[str, str] = {}

    if v := _try(lambda: f"{platform.system()} {platform.release()}".strip()):
        static["os"] = v
    if v := _try(platform.platform):
        static["platform"] = v
    if v := _try(platform.machine):
        static["arch"] = v
    if v := _try(lambda: platform.processor() or platform.machine()):
        static["cpu"] = v
    if v := _try(lambda: os.cpu_count()):
        static["cpu_count"] = str(v)
    if v := _try(socket.gethostname):
        static["hostname"] = v
    if v := _try(platform.python_version):
        static["python"] = v
    if (ram := _total_ram_gb()) is not None:
        static["ram_total_gb"] = str(ram)

    if (du := _try(lambda: shutil.disk_usage(os.path.expanduser("~")))) is not None:
        mutating["disk_total_gb"] = str(round(du.total / 1e9, 1))
        mutating["disk_free_gb"] = str(round(du.free / 1e9, 1))
    if (free := _free_ram_gb()) is not None:
        mutating["ram_free_gb"] = str(free)
    if (up := _uptime_seconds()) is not None:
        mutating["uptime_hours"] = str(round(up / 3600, 1))
    mutating["snapshot_at"] = str(round(time.time(), 0))

    return {"static": static, "mutating": mutating}


def format_system_summary(static: dict, mutating: dict) -> str:
    """Compact one-line-ish `System:` summary for prompt injection (Phase 3)."""
    parts: list[str] = []
    if static.get("os"):
        parts.append(static["os"])
    if static.get("arch"):
        parts.append(static["arch"])
    if static.get("cpu_count"):
        parts.append(f"{static['cpu_count']} CPUs")
    if static.get("ram_total_gb"):
        ram = f"{static['ram_total_gb']} GB RAM"
        if mutating.get("ram_free_gb"):
            ram += f" ({mutating['ram_free_gb']} GB free)"
        parts.append(ram)
    if mutating.get("disk_total_gb"):
        disk = f"{mutating['disk_total_gb']} GB disk"
        if mutating.get("disk_free_gb"):
            disk += f" ({mutating['disk_free_gb']} GB free)"
        parts.append(disk)
    if static.get("hostname"):
        parts.append(f"host {static['hostname']}")
    return "System: " + ", ".join(parts) if parts else ""

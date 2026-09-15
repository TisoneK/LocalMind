"""Sysinfo reports CPU/RAM/disk/uptime without psutil.

psutil is now a declared dependency, but if it is ever
unavailable (a platform with no wheel, a broken install) the system overview
must still populate from native/stdlib sources rather than degrading to
"(requires psutil)". These tests force the no-psutil path.
"""

from __future__ import annotations

import tools.sysinfo as si


def test_native_cpu_line_reports_processors() -> None:
    line = si._native_cpu_line()
    assert line is not None
    assert line.startswith("CPU:")
    assert "processor" in line.lower()


def test_native_disk_line_reports_totals() -> None:
    line = si._native_disk_line("/", "root")
    # shutil.disk_usage("/") works on every supported OS.
    assert line is not None
    assert "GB total" in line and "GB free" in line


def test_default_summary_populates_without_psutil(monkeypatch) -> None:
    monkeypatch.setattr(si, "_HAS_PSUTIL", False)
    summary = si._default_summary()
    # OS/hostname always present; the native block must add at least CPU + disk.
    assert "OS:" in summary
    assert "CPU:" in summary
    assert "Disk (" in summary
    assert "requires psutil" not in summary


def test_disk_all_info_native_without_psutil(monkeypatch) -> None:
    monkeypatch.setattr(si, "_HAS_PSUTIL", False)
    out = si._disk_all_info()
    assert "requires psutil" not in out
    assert "Mounted filesystems" in out or out == "Disk info unavailable."

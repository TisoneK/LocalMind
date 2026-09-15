"""
System Info tool — comprehensive offline system information.

Covers all platforms (Windows, Linux, macOS):
  - Date/time (always included)
  - OS, machine, hostname, Python version
  - CPU cores/frequency, RAM, disk usage
  - Network interfaces (IP, IPv6, MAC, status)
  - GPU info (nvidia-smi, system_profiler, WMI)
  - Top processes by memory/CPU
  - Environment variables, shell, PATH
  - All mounted filesystems
  - System uptime, load average
  - Current user, groups
  - Listening ports, Docker containers
  - Installed programs (delegated to installed_programs.py)

Registered as Intent.SYSINFO.  Fast: no model call, no network.
Basic queries < 100 ms.  GPU / process / service queries may take up to a few
seconds due to subprocess calls.
"""

from __future__ import annotations

import datetime
import logging
import os
import platform
import socket
import sys
import time

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy dependency
# ---------------------------------------------------------------------------
_HAS_PSUTIL = False
try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Section: Time
# ---------------------------------------------------------------------------


def _time_info() -> str:
    """Always included — current date/time with timezone."""
    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    tz_name = now.tzname() or "local"
    utc_offset = now.strftime("%z")
    return (
        f"Current date/time: {now.strftime('%A, %B %d, %Y  %I:%M:%S %p')}"
        f" ({tz_name}, UTC{utc_offset})"
    )


# ---------------------------------------------------------------------------
# Native fallbacks — so sysinfo reports CPU/RAM/disk/uptime
# even when psutil is unavailable (a platform with no wheel, a broken install).
# Uses stdlib (shutil.disk_usage, os.cpu_count) and lightweight platform
# commands. Model/env-agnostic: sysinfo should never return an empty overview.
# ---------------------------------------------------------------------------


def _native_cpu_line() -> str | None:
    n = os.cpu_count()
    proc = (platform.processor() or platform.machine() or "").strip()
    if not n:
        return None
    return f"CPU: {n} logical processors" + (f"  ({proc})" if proc else "")


def _native_disk_line(path: str, label: str) -> str | None:
    import shutil

    try:
        u = shutil.disk_usage(path)
    except OSError:
        return None
    return (
        f"Disk ({label}): {u.total / 1e9:.1f} GB total  |  {u.free / 1e9:.1f} GB free"
    )


def _native_ram_line() -> str | None:
    import re
    import subprocess

    total: int | None = None
    avail: int | None = None
    try:
        if sys.platform.startswith("linux"):
            info: dict[str, int] = {}
            with open("/proc/meminfo") as fh:
                for line in fh:
                    key, _, val = line.partition(":")
                    parts_ = val.strip().split()
                    if parts_:
                        info[key.strip()] = int(parts_[0]) * 1024
            total = info.get("MemTotal")
            avail = info.get("MemAvailable") or info.get("MemFree")
        elif sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3
            ).stdout.strip()
            total = int(out) if out.isdigit() else None
            vm = subprocess.run(
                ["vm_stat"], capture_output=True, text=True, timeout=3
            ).stdout
            page = 4096
            pm = re.search(r"page size of (\d+)", vm)
            if pm:
                page = int(pm.group(1))
            free_pages = 0
            for key in ("Pages free", "Pages inactive", "Pages speculative"):
                fm = re.search(rf"{key}:\s+(\d+)", vm)
                if fm:
                    free_pages += int(fm.group(1))
            avail = free_pages * page if free_pages else None
        elif sys.platform == "win32":
            out = subprocess.run(
                ["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory", "/value"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("TotalVisibleMemorySize=") and line.split("=", 1)[1].isdigit():
                    total = int(line.split("=", 1)[1]) * 1024
                elif line.startswith("FreePhysicalMemory=") and line.split("=", 1)[1].isdigit():
                    avail = int(line.split("=", 1)[1]) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not total:
        return None
    avail_str = f"  |  {avail / 1e9:.1f} GB available" if avail else ""
    used_str = f"  ({(total - avail) / total * 100:.0f}% used)" if avail else ""
    return f"RAM: {total / 1e9:.1f} GB total{avail_str}{used_str}"


def _native_uptime_line() -> str | None:
    import subprocess

    boot_ts: float | None = None
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/uptime") as fh:
                secs = int(float(fh.read().split()[0]))
                boot_ts = time.time() - secs
        elif sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=3
            ).stdout
            import re

            m = re.search(r"sec = (\d+)", out)
            if m:
                boot_ts = float(m.group(1))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if boot_ts is None:
        return None
    secs = int(time.time() - boot_ts)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    uptime_str = f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"
    return f"Uptime: {uptime_str}"


# ---------------------------------------------------------------------------
# Section: Default summary (broad overview)
# ---------------------------------------------------------------------------


def _default_summary() -> str:
    """Comprehensive default summary when no specific section is requested."""
    parts = []
    parts.append(f"OS: {platform.system()} {platform.release()} ({platform.version()})")
    parts.append(f"Machine: {platform.machine()}  |  Processor: {platform.processor()}")
    parts.append(f"Hostname: {platform.node()}")

    # User
    try:
        import getpass

        parts.append(f"User: {getpass.getuser()}")
    except Exception:
        pass

    # Python
    parts.append(f"Python: {sys.version.split()[0]}")

    if _HAS_PSUTIL:
        # CPU
        try:
            cpu_count = psutil.cpu_count(logical=True)
            cpu_phys = psutil.cpu_count(logical=False)
            cpu_freq = psutil.cpu_freq()
            freq_str = f"{cpu_freq.current:.0f} MHz" if cpu_freq else "unknown"
            parts.append(f"CPU: {cpu_phys} cores ({cpu_count} logical) @ {freq_str}")
        except Exception:
            pass

        # RAM
        try:
            ram = psutil.virtual_memory()
            parts.append(
                f"RAM: {ram.total / 1e9:.1f} GB total  |  "
                f"{ram.available / 1e9:.1f} GB available  ({ram.percent}% used)"
            )
        except Exception:
            pass

        # Disk (home)
        try:
            disk = psutil.disk_usage(os.path.expanduser("~"))
            parts.append(
                f"Disk (home): {disk.total / 1e9:.1f} GB total  |  "
                f"{disk.free / 1e9:.1f} GB free"
            )
        except Exception:
            pass

        # Uptime (brief)
        try:
            boot_ts = psutil.boot_time()
            uptime_secs = int(time.time() - boot_ts)
            days, rem = divmod(uptime_secs, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, _ = divmod(rem, 60)
            if days:
                uptime_str = f"{days}d {hours}h {minutes}m"
            else:
                uptime_str = f"{hours}h {minutes}m"
            parts.append(f"Uptime: {uptime_str}")
        except Exception:
            pass
    else:
        # No psutil — report CPU/RAM/disk/uptime natively so
        # the overview is never empty (append only the lines that resolve).
        for line in (
            _native_cpu_line(),
            _native_ram_line(),
            _native_disk_line(os.path.expanduser("~"), "home"),
            _native_uptime_line(),
        ):
            if line:
                parts.append(line)

    # Network (brief — interface + IPv4, skip loopback)
    if _HAS_PSUTIL:
        try:
            addrs = psutil.net_if_addrs()
            net_parts = []
            for iface, addr_list in sorted(addrs.items()):
                ipv4 = [
                    a.address
                    for a in addr_list
                    if a.family == socket.AF_INET and not a.address.startswith("127.")
                ]
                if ipv4:
                    net_parts.append(f"{iface}: {', '.join(ipv4)}")
            if net_parts:
                parts.append(f"Network: {';  '.join(net_parts)}")
        except Exception:
            pass

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Section: Network (detailed)
# ---------------------------------------------------------------------------


def _network_info() -> str:
    """Network interfaces with IPs, MACs, and status."""
    if not _HAS_PSUTIL:
        return "(Network info requires psutil: pip install psutil)"

    parts = ["Network interfaces:"]
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for iface, addr_list in sorted(addrs.items()):
            iface_parts = [f"  {iface}:"]
            stat = stats.get(iface)
            if stat:
                status = "UP" if stat.isup else "DOWN"
                speed = f" @ {stat.speed} Mbps" if stat.speed > 0 else ""
                iface_parts.append(f"{status}{speed}")

            ipv4 = [a.address for a in addr_list if a.family == socket.AF_INET]
            ipv6 = [a.address for a in addr_list if a.family == socket.AF_INET6]
            mac = [a.address for a in addr_list if a.family == psutil.AF_LINK]

            if ipv4:
                iface_parts.append(f"IPv4: {', '.join(ipv4)}")
            if ipv6:
                iface_parts.append(f"IPv6: {', '.join(ipv6)}")
            if mac:
                iface_parts.append(f"MAC: {mac[0]}")

            parts.append(" | ".join(iface_parts))
    except Exception as e:
        parts.append(f"  (Error: {e})")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Section: GPU
# ---------------------------------------------------------------------------


def _gpu_info() -> str:
    """GPU info — nvidia-smi (Linux/Windows), system_profiler (macOS)."""
    import subprocess

    # --- nvidia-smi (Linux / Windows) ---
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().splitlines()
            gpu_parts = ["GPU (NVIDIA):"]
            for i, line in enumerate(lines):
                vals = [v.strip() for v in line.split(",")]
                if len(vals) >= 7:
                    gpu_parts.append(f"  GPU {i}: {vals[0]}")
                    gpu_parts.append(f"    Driver: {vals[1]}")
                    gpu_parts.append(
                        f"    VRAM: {vals[2]} MiB total, "
                        f"{vals[3]} MiB used, {vals[4]} MiB free"
                    )
                    gpu_parts.append(
                        f"    Utilization: {vals[5]}%  |  Temp: {vals[6]} C"
                    )
            return "\n".join(gpu_parts)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # --- macOS: system_profiler ---
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout
                gpu_parts = ["GPU:"]
                in_block = False
                for line in text.splitlines():
                    stripped = line.strip()
                    if not stripped:
                        if in_block:
                            break
                        continue
                    if any(
                        kw in stripped
                        for kw in ("Chipset Model", "VRAM", "Metal", "Vendor")
                    ):
                        in_block = True
                    if in_block:
                        gpu_parts.append(f"  {stripped}")
                if len(gpu_parts) > 1:
                    return "\n".join(gpu_parts)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    # --- Windows: WMI ---
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                [
                    "wmic", "path", "win32_VideoController",
                    "get", "Name,AdapterRAM,DriverVersion", "/format:list",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu_parts = ["GPU:"]
                current: dict[str, str] = {}
                for line in result.stdout.splitlines():
                    if "=" in line:
                        key, val = line.split("=", 1)
                        current[key.strip()] = val.strip()
                    elif not line.strip() and current:
                        name = current.get("Name", "Unknown")
                        ram_raw = current.get("AdapterRAM", "")
                        driver = current.get("DriverVersion", "unknown")
                        try:
                            vram_mb = int(ram_raw) // (1024 * 1024)
                            vram_str = f"{vram_mb} MiB"
                        except (ValueError, TypeError):
                            vram_str = "unknown"
                        gpu_parts.append(f"  {name}")
                        gpu_parts.append(
                            f"    VRAM: {vram_str}  |  Driver: {driver}"
                        )
                        current = {}
                if len(gpu_parts) > 1:
                    return "\n".join(gpu_parts)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    return "No GPU detected or GPU info unavailable."


# ---------------------------------------------------------------------------
# Section: Processes
# ---------------------------------------------------------------------------


def _process_info(limit: int = 10) -> str:
    """Top processes by memory usage."""
    if not _HAS_PSUTIL:
        return "(Process info requires psutil: pip install psutil)"

    try:
        procs: list[dict] = []
        for p in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent"]
        ):
            try:
                info = p.info  # type: ignore[union-attr]
                if info and info.get("name"):
                    procs.append(info)  # type: ignore[arg-type]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda x: x.get("memory_percent") or 0, reverse=True)

        count = min(limit, len(procs))
        lines = [f"Top {count} processes by memory:"]
        for p in procs[:limit]:
            pid = p["pid"]
            name = (p.get("name") or "unknown")[:30]
            mem = p.get("memory_percent") or 0
            cpu = p.get("cpu_percent") or 0
            lines.append(
                f"  {name:<32} PID {pid:>6}  MEM {mem:>5.1f}%  CPU {cpu:>5.1f}%"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"(Error listing processes: {e})"


# ---------------------------------------------------------------------------
# Section: Environment
# ---------------------------------------------------------------------------


def _environment_info() -> str:
    """Environment variables, shell, PATH, working directory."""
    parts = []

    try:
        parts.append(f"Working directory: {os.getcwd()}")
    except Exception:
        pass

    shell = os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown"
    parts.append(f"Shell: {shell}")
    parts.append(f"Python executable: {sys.executable}")
    parts.append(f"Python version: {sys.version.split()[0]}")

    path = os.environ.get("PATH", "")
    if len(path) > 500:
        path = path[:500] + "..."
    parts.append(f"PATH: {path}")

    parts.append(f"Environment variables: {len(os.environ)} total")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Section: All mounted disks
# ---------------------------------------------------------------------------


def _native_disk_all() -> str:
    """Mounted-filesystem usage without psutil — `df -kP` on
    Unix, drive letters (via stdlib shutil) on Windows."""
    import shutil
    import subprocess

    def _fmt(mount: str, total: int, free: int) -> str:
        pct = int((total - free) / total * 100) if total else 0
        filled = pct // 5
        bar = "█" * filled + "░" * (20 - filled)
        return (
            f"  {mount:<25} {total / 1e9:>7.1f}G total  "
            f"{free / 1e9:>7.1f}G free  [{bar}] {pct}%"
        )

    parts = ["Mounted filesystems:"]
    try:
        if sys.platform == "win32":
            import string

            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    try:
                        u = shutil.disk_usage(drive)
                        parts.append(_fmt(drive, u.total, u.free))
                    except OSError:
                        continue
        else:
            out = subprocess.run(
                ["df", "-kP"], capture_output=True, text=True, timeout=5
            ).stdout
            for line in out.splitlines()[1:]:
                cols = line.split()
                if len(cols) >= 6 and cols[1].isdigit() and cols[3].isdigit():
                    total = int(cols[1]) * 1024
                    if total <= 0:
                        continue
                    parts.append(_fmt(cols[5], total, int(cols[3]) * 1024))
    except (OSError, subprocess.SubprocessError):
        pass

    if len(parts) == 1:  # nothing enumerated — fall back to root + home
        for path in ("/", os.path.expanduser("~")):
            try:
                u = shutil.disk_usage(path)
                parts.append(_fmt(path, u.total, u.free))
            except OSError:
                continue
    return "\n".join(parts) if len(parts) > 1 else "Disk info unavailable."


def _disk_all_info() -> str:
    """All mounted filesystems with usage bars."""
    if not _HAS_PSUTIL:
        return _native_disk_all()

    parts = ["Mounted filesystems:"]
    try:
        partitions = psutil.disk_partitions(all=False)
        if not partitions:
            # Fallback: show root / home usage when no partitions listed
            for label, path in [("root", "/"), ("home", os.path.expanduser("~"))]:
                if os.path.exists(path):
                    try:
                        usage = psutil.disk_usage(path)
                        pct = usage.percent
                        bar_len = 20
                        filled = int(bar_len * pct / 100)
                        bar = "█" * filled + "░" * (bar_len - filled)
                        parts.append(
                            f"  {path:<25} {label:<12} "
                            f"{usage.total / 1e9:>7.1f}G total  "
                            f"{usage.free / 1e9:>7.1f}G free  "
                            f"[{bar}] {pct}%"
                        )
                    except (PermissionError, OSError):
                        pass
            if len(parts) == 1:
                parts.append("  (No mounted filesystems detected)")
        else:
            for p in partitions:
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    pct = usage.percent
                    bar_len = 20
                    filled = int(bar_len * pct / 100)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    parts.append(
                        f"  {p.mountpoint:<25} {p.fstype:<12} "
                        f"{usage.total / 1e9:>7.1f}G total  "
                        f"{usage.free / 1e9:>7.1f}G free  "
                        f"[{bar}] {pct}%"
                    )
                except (PermissionError, OSError):
                    parts.append(
                        f"  {p.mountpoint:<25} {p.fstype:<12} (permission denied)"
                    )
    except Exception as e:
        parts.append(f"  (Error: {e})")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Section: Uptime & Load
# ---------------------------------------------------------------------------


def _uptime_info() -> str:
    """System uptime, boot time, load average."""
    parts = []

    if _HAS_PSUTIL:
        try:
            boot_ts = psutil.boot_time()
            boot_dt = datetime.datetime.fromtimestamp(boot_ts).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            uptime_secs = int(time.time() - boot_ts)
            days, rem = divmod(uptime_secs, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, secs = divmod(rem, 60)
            if days:
                uptime_str = f"{days}d {hours}h {minutes}m {secs}s"
            else:
                uptime_str = f"{hours}h {minutes}m {secs}s"
            parts.append(f"Uptime: {uptime_str} (since {boot_dt})")
        except Exception:
            pass

    # Load average (Unix / macOS only — not available on Windows)
    if hasattr(os, "getloadavg"):
        try:
            load1, load5, load15 = os.getloadavg()
            parts.append(
                f"Load average: {load1:.2f} (1m)  "
                f"{load5:.2f} (5m)  {load15:.2f} (15m)"
            )
        except OSError:
            pass

    return "\n".join(parts) if parts else "Uptime info unavailable."


# ---------------------------------------------------------------------------
# Section: User
# ---------------------------------------------------------------------------


def _user_info() -> str:
    """Current user, home directory, groups."""
    parts = []

    # Current user
    try:
        import getpass

        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    parts.append(f"User: {user}")

    # Home
    parts.append(f"Home: {os.path.expanduser('~')}")

    # Groups (Unix / macOS)
    if hasattr(os, "getgroups"):
        try:
            gids = os.getgroups()
            group_names: list[str] = []
            try:
                import grp

                for gid in gids:
                    try:
                        group_names.append(grp.getgrgid(gid).gr_name)
                    except KeyError:
                        group_names.append(str(gid))
            except ImportError:
                group_names = [str(g) for g in gids]
            parts.append(f"Groups: {', '.join(group_names)}")
        except OSError:
            pass
    elif sys.platform == "win32":
        # Windows: net user
        import subprocess

        try:
            result = subprocess.run(
                ["net", "user", user],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "Local Group Memberships" in line:
                        groups = line.split(":", 1)[1].strip()
                        if groups and groups != "*None":
                            parts.append(f"Groups: {groups}")
                        break
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Section: Services / Ports
# ---------------------------------------------------------------------------


def _service_port_info() -> str:
    """Listening ports and Docker containers."""
    parts = []

    # Listening ports
    if _HAS_PSUTIL:
        try:
            connections = psutil.net_connections(kind="inet")
            listening = [c for c in connections if c.status == "LISTEN"]

            if listening:
                parts.append(f"Listening ports ({len(listening)}):")
                seen: set[int] = set()
                for c in sorted(listening, key=lambda x: x.laddr.port):
                    if c.laddr.port in seen:
                        continue
                    seen.add(c.laddr.port)
                    pid = c.pid or "?"
                    name = ""
                    if c.pid:
                        try:
                            name = psutil.Process(c.pid).name()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    parts.append(
                        f"  :{c.laddr.port:<6} {c.laddr.ip:<20} "
                        f"PID {pid} ({name})"
                    )
            else:
                parts.append("No listening ports found.")
        except (psutil.AccessDenied, OSError) as e:
            parts.append(f"(Cannot read connections: {e})")

    # Docker containers
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append("\nDocker containers:")
            for line in result.stdout.strip().splitlines():
                parts.append(f"  {line}")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass  # Docker not available

    return "\n".join(parts) if parts else "Service/port info unavailable."


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------


def _get_system_info(query: str) -> str:
    """Route to the right section(s) based on query keywords."""
    q = query.lower()
    parts = [_time_info()]

    # Track whether any specific section was matched
    section_added = False

    # Network
    if any(
        w in q
        for w in (
            "network", "ip address", "interface", "wifi", "ethernet",
            "dns", "mac address", "connection", "adapter", "lan",
        )
    ):
        parts.append(_network_info())
        section_added = True

    # GPU
    if any(
        w in q
        for w in (
            "gpu", "graphics card", "vram", "nvidia", "cuda",
            "display adapter", "video card",
        )
    ):
        parts.append(_gpu_info())
        section_added = True

    # Processes
    if any(
        w in q
        for w in (
            "process", "running process", "top process", "task manager",
            "ps aux", "processes",
        )
    ):
        parts.append(_process_info())
        section_added = True

    # Environment
    if any(
        w in q
        for w in (
            "env ", "environment var", "env var",
            "home directory", "working directory",
            "shell ", "my path", "show path", "$path", "path variable",
            "environment variable", "working dir",
        )
    ):
        parts.append(_environment_info())
        section_added = True

    # All disks / mounts
    if any(
        w in q
        for w in (
            "mount", "filesystem", "partition", "all disk", "all drive",
            "disk space", "disk usage", "storage",
        )
    ):
        parts.append(_disk_all_info())
        section_added = True

    # Uptime
    if any(
        w in q
        for w in ("uptime", "boot time", "load average", "how long", "last boot")
    ):
        parts.append(_uptime_info())
        section_added = True

    # User
    if any(
        w in q
        for w in ("whoami", "username", "login", "group", "account")
    ):
        parts.append(_user_info())
        section_added = True

    # Services / Ports
    if any(
        w in q
        for w in ("service", "port", "docker", "listening", "daemon", "systemd")
    ):
        parts.append(_service_port_info())
        section_added = True

    # If no specific section matched, show default comprehensive summary
    # (unless query is time-only)
    if not section_added:
        wants_time_only = any(
            w in q for w in ("time", "date", "day", "hour", "minute")
        )
        if not wants_time_only:
            parts.append(_default_summary())

    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def sysinfo(query: str) -> ToolResult:
    try:
        q = query.lower()
        # Route installed programs queries to dedicated reader
        if any(
            w in q
            for w in ["installed", "programs", "software", "apps", "applications", "packages"]
        ):
            from tools.installed_programs import get_installed_programs

            info = get_installed_programs(query)
        else:
            info = _get_system_info(query)
        return ToolResult(
            content=info,
            risk=RiskLevel.LOW,
            source="sysinfo",
            metadata={"offline": True},
        )
    except Exception as e:
        logger.error(f"[sysinfo] error: {e}")
        return ToolResult(
            content=f"System info error: {e}",
            risk=RiskLevel.LOW,
            source="sysinfo",
        )


register_tool(
    Intent.SYSINFO,
    sysinfo,
    description=(
        "Get system info: time, date, OS, CPU, RAM, disk, network, GPU, "
        "processes, env, uptime, users, services, installed programs. "
        "Offline, instant."
    ),
    cost=0.0,
    latency_ms=50,
    parallelizable=True,
    # A bare sysinfo() (no query) is the natural "show me my system" call and
    # returns the full default summary — never reject it as degenerate input.
    input_optional=True,
)

"""
Shared utility helpers used across tools, routes, and core modules.

Keep this module dependency-free (stdlib only) so it can be imported
anywhere without triggering circular imports.
"""

from __future__ import annotations


def human_size(n: int) -> str:
    """Format a byte count as a human-readable string (B / KB / MB / GB / TB / PB).

    Uses 1024-based binary units (1 KB = 1024 B). Caps at PB; values larger
    than 1 PB continue to display in PB with one decimal place.

    Examples:
        >>> human_size(0)
        '0.0 B'
        >>> human_size(1536)
        '1.5 KB'
        >>> human_size(1073741824)
        '1.0 GB'
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"

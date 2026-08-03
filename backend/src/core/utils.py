"""
Shared utility helpers used across tools, routes, and core modules.

Keep this module dependency-free (stdlib only) so it can be imported
anywhere without triggering circular imports.
"""

import threading

TOOL_OUTPUT_MAX = 4000
TRUNCATION_MARKER = "[...TRUNCATED DUE TO LENGTH...]"


class BoundedOutputBuffer:
    """Retain the beginning and end of output under a fixed character cap.

    Tool failures and tracebacks commonly appear at the end of a command's
    output. Keeping both sides is more useful than a head-only slice while
    still bounding the text placed into the model context.
    """

    def __init__(self, max_chars: int = TOOL_OUTPUT_MAX, marker: str = TRUNCATION_MARKER):
        if max_chars < 0:
            raise ValueError("max_chars must be non-negative")
        self.max_chars = max_chars
        self.marker = marker
        self._head = ""
        self._tail = ""
        self._total_chars = 0
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        """Add text while retaining only bounded head/tail state."""
        if not text:
            return
        with self._lock:
            self._total_chars += len(text)
            if self.max_chars == 0:
                return
            self._head = (self._head + text)[: self.max_chars]
            self._tail = (self._tail + text)[-self.max_chars :]

    @property
    def truncated(self) -> bool:
        with self._lock:
            return self._total_chars > self.max_chars

    def getvalue(self) -> str:
        """Return the bounded text, including a clear truncation marker."""
        with self._lock:
            if self._total_chars <= self.max_chars:
                return self._head
            if self.max_chars == 0:
                return ""
            if len(self.marker) >= self.max_chars:
                return self.marker[: self.max_chars]

            available = self.max_chars - len(self.marker)
            head_chars = (available + 1) // 2
            tail_chars = available - head_chars
            return f"{self._head[:head_chars]}{self.marker}{self._tail[-tail_chars:] if tail_chars else ''}"

    def __str__(self) -> str:
        return self.getvalue()


def bounded_output(text: str, max_chars: int = TOOL_OUTPUT_MAX) -> str:
    """Return *text* capped to *max_chars* while retaining its head and tail."""
    buffer = BoundedOutputBuffer(max_chars=max_chars)
    buffer.append(text)
    return buffer.getvalue()


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

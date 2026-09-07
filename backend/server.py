"""
LocalMind server entrypoint.
Run directly: python server.py
Or via uvicorn: uvicorn server:app

NOTE: Backend source lives in src/ — add it to sys.path so that
      `from api.app import ...` resolves correctly when running
      server.py from the backend/ directory.
"""

import logging
import os
import signal
import socket
import sys

import uvicorn

# Ensure src/ is on the import path when running from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from api.app import create_app
from core.config import settings

logging.basicConfig(
    level=getattr(logging, settings.localmind_log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

# Configure httpx to log requests in the same format
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.INFO)
# Use same format as basicConfig
formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s", "%H:%M:%S")
# Add custom handler with same format
handler = logging.StreamHandler()
handler.setFormatter(formatter)
httpx_logger.handlers = [handler]
# Prevent propagation to avoid duplicate logs
httpx_logger.propagate = False

app = create_app()


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is already bound by another process.

    POSIX: bind-probe with SO_REUSEADDR — matches uvicorn's own binding, so
    lingering TIME_WAIT sockets from the previous instance don't produce a
    FALSE "port in use" (Session 188), while a genuinely LISTENING process
    still fails the bind.

    Windows flips SO_REUSEADDR's meaning: a probe socket WITH the flag can
    bind over another process's ACTIVE listener, so a bind-probe reports
    genuinely-busy ports as free. Probe by connecting instead: a listening
    owner completes (or rejects) the connection → in use; TIME_WAIT
    leftovers refuse it → free, preserving the Session 188 restart behavior.
    """
    if sys.platform == "win32":
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False  # Port is free
        except OSError:
            return True  # Port is already in use


if __name__ == "__main__":
    # Pre-check: fail fast if port is already in use by another LocalMind instance.
    # This prevents the infinite restart loop in Electron when the user
    # manually runs `python server.py` before launching the Electron app.
    if is_port_in_use(settings.localmind_port, settings.localmind_host):
        logger = logging.getLogger("localmind")
        logger.error(
            "[startup] Port %s:%s is already in use — another instance may be running. "
            "Use `netstat -ano | findstr :%s` (Windows) or `lsof -i :%s` (macOS/Linux) "
            "to find and kill the process, then try again.",
            settings.localmind_host,
            settings.localmind_port,
            settings.localmind_port,
            settings.localmind_port,
        )
        sys.exit(42)  # Exit code 42 = port in use (convention shared with Electron)

    # ── Graceful shutdown via uvicorn.Server ──────────────────────────────
    # Using uvicorn.Server directly (instead of uvicorn.run()) gives us full
    # control over the shutdown sequence. When SIGINT/SIGTERM arrives we set
    # server.should_exit = True, which triggers uvicorn's built-in graceful
    # shutdown: it drains active connections, runs the FastAPI shutdown event,
    # then exits cleanly — no ugly CancelledError / SystemExit traceback.
    config = uvicorn.Config(
        "server:app",
        host=settings.localmind_host,
        port=settings.localmind_port,
        reload=False,
        log_level=settings.localmind_log_level.lower(),
    )
    server = uvicorn.Server(config)

    def _signal_handler(sig_num, frame):
        """Trigger uvicorn's graceful shutdown instead of sys.exit()."""
        logger = logging.getLogger("localmind")
        sig_name = signal.Signals(sig_num).name
        logger.info("Received signal %s — shutting down gracefully...", sig_name)
        server.should_exit = True

    # Register signal handlers for both SIGINT (Ctrl+C) and SIGTERM (kill)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        server.run()
    except KeyboardInterrupt:
        # Fallback — should not normally reach here since signal handler
        # sets should_exit, but just in case.
        print("\nLocalMind stopped by user")
    except Exception as e:
        print(f"\nServer error: {e}")
        sys.exit(1)

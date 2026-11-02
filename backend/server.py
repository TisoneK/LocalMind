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
import sys

import uvicorn

# Ensure src/ is on the import path when running from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from api.app import create_app
from core.config import settings
from core.ports import is_port_in_use, occupant_is_localmind

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


if __name__ == "__main__":
    # Pre-check: fail fast when the preferred port is held by another process.
    # The server layer stays strict on purpose — flexibility lives one layer up,
    # in scripts/dev-full.js, which resolves free ports BEFORE spawning and
    # propagates them through env to every consumer (vite, Electron, CORS).
    # This guard names the occupant instead of telling the user to run netstat
    # and guess: a healthy LocalMind instance is a different situation from a
    # foreign application holding the port.
    if is_port_in_use(settings.localmind_port, settings.localmind_host):
        logger = logging.getLogger("localmind")
        if occupant_is_localmind(settings.localmind_host, settings.localmind_port):
            logger.error(
                "[startup] Port %s:%s is already serving a healthy LocalMind instance — "
                "stop that one first, or just open it; `npm start` reuses an existing "
                "healthy backend automatically.",
                settings.localmind_host,
                settings.localmind_port,
            )
        else:
            logger.error(
                "[startup] Port %s:%s is held by a different application. Free it "
                "(find the holder: `netstat -ano | findstr :%s` on Windows or "
                "`lsof -i :%s` on macOS/Linux) or run LocalMind elsewhere: set "
                "LOCALMIND_PORT (backend) and LOCALMIND_FRONTEND_PORT (UI) before "
                "starting, or just use `npm start`, which picks free ports for you.",
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

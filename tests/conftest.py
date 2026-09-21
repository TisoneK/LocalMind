"""
Shared pytest fixtures for all LocalMind tests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Data-home isolation — MUST run before any backend/src import.
#
# The app resolves its data directory from LOCALMIND_HOME, defaulting to
# <user home>/LocalMind — the REAL application home with the user's chats.
# Engine/store tests read that home and write test sessions into the
# production database. Stage a fresh temp home here, at conftest import
# time, whenever the incoming value is unset or IS the real home; a home
# staged deliberately by a live-test harness or a developer is respected.
if sys.platform == "win32":
    _home_base = Path(os.environ.get("USERPROFILE", Path.home()))
else:
    _home_base = Path.home()
_staged_home = os.environ.get("LOCALMIND_HOME", "")
if not _staged_home or Path(_staged_home).expanduser().resolve() == (_home_base / "LocalMind").resolve():
    import tempfile

    os.environ["LOCALMIND_HOME"] = tempfile.mkdtemp(prefix="localmind-test-home-")
# ---------------------------------------------------------------------------

# Ensure backend/src/ is on sys.path so test modules can import
# `from tools.file_reader import ...`, `from adapters.ollama import ...`, etc.
# The pyproject.toml `pythonpath = ["src"]` setting should handle this, but
# some pytest versions don't honor it reliably — this is a guaranteed fallback.
_BACKEND_SRC = str(Path(__file__).resolve().parent.parent / "backend" / "src")
if _BACKEND_SRC not in sys.path:
    sys.path.insert(0, _BACKEND_SRC)


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Ensure tests never hit a real Ollama instance or write to production DB."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:19999")  # nothing listens here
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.setenv("LOCALMIND_CODE_EXEC_ENABLED", "true")
    monkeypatch.setenv("LOCALMIND_LOG_LEVEL", "WARNING")
    # Pin chat mode to the product default so tests are hermetic against a
    # polluted runtime settings.json. The config singleton loads
    # ~/LocalMind/settings.json at import, and both the running app and any
    # live-test that POSTs /api/settings/chat-mode write `chat_mode` there —
    # leaving it on "agent"/"direct" silently disables the loop's pre-init
    # deterministic guards (they gate on `_chat_mode != 'agent'`) and breaks
    # unrelated tests. A test that needs a non-default mode sets it itself;
    # monkeypatch restores this after each test.
    from core.config import settings as _settings

    monkeypatch.setattr(_settings, "localmind_chat_mode", "auto", raising=False)
    # Same hermeticity for the engine and the shell tool: the developer's runtime settings.json /
    # backend/.env must not decide the result (with the shell tool off in .env, loop/shell tests that
    # run commands failed on one machine and passed on another — B-2026-09-21-14).
    monkeypatch.setattr(_settings, "localmind_engine", "classic", raising=False)
    monkeypatch.setattr(_settings, "localmind_shell_enabled", True, raising=False)


@pytest.fixture
def tmp_db(tmp_path):
    """Return a path to a temporary SQLite DB that is cleaned up after the test."""
    return str(tmp_path / "test.db")


@pytest.fixture
def sample_pdf_bytes():
    """Minimal valid PDF bytes for testing the file reader."""
    # Smallest valid PDF structure
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R"
        b"/Contents 4 0 R>>endobj\n"
        b"4 0 obj<</Length 44>>stream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello LocalMind) Tj ET\n"
        b"endstream\nendobj\n"
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        b"trailer<</Size 5/Root 1 0 R>>\n"
        b"startxref\n9\n%%EOF"
    )


@pytest.fixture
def sample_txt_bytes():
    return b"This is a test document.\n\nIt has two paragraphs.\n\nAnd a third one."

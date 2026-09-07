"""Regression guard: a pytest run must never resolve the app data home to
the real user home.

The suite constructs engines and stores whose data directory comes from
LOCALMIND_HOME, which defaults to ``<user home>/LocalMind`` — the REAL
application home. tests/conftest.py stages a temp home at import time
instead. If this test fails, that isolation was removed or broke, and any
suite run will read real settings and write test chats/workspaces into
production data.
"""

import os
import sys
from pathlib import Path


def _real_default_home() -> Path:
    # Mirror the app's own platform-specific default-home resolution.
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", Path.home()))
    else:
        base = Path.home()
    return (base / "LocalMind").resolve()


def test_pytest_data_home_is_isolated_from_the_real_app_home():
    raw = os.environ.get("LOCALMIND_HOME")
    assert raw, "tests/conftest.py must stage LOCALMIND_HOME before any app import"
    assert Path(raw).expanduser().resolve() != _real_default_home(), (
        "pytest is resolving the app data home to the real application home; "
        "test runs would write into production data"
    )

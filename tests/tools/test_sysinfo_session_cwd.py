"""sysinfo's environment report must reflect the session-tracked CWD, not
the server process's own os.getcwd() -- the two can diverge (e.g. the
server started from one directory while the session `cd`'d elsewhere),
which is exactly what set_session_cwd() exists to prevent for the other
CWD-aware tools (shell, git, process).
"""

from __future__ import annotations

import os

import tools.sysinfo as si


def test_environment_info_uses_session_cwd_when_set(tmp_path):
    si.set_session_cwd(str(tmp_path))
    try:
        out = si._environment_info()
    finally:
        si.set_session_cwd(None)

    assert f"Working directory: {tmp_path}" in out


def test_environment_info_falls_back_to_process_cwd_when_unset():
    si.set_session_cwd(None)
    out = si._environment_info()
    assert f"Working directory: {os.getcwd()}" in out


def test_environment_info_ignores_stale_session_cwd_that_no_longer_exists(tmp_path):
    gone = tmp_path / "deleted"
    gone.mkdir()
    si.set_session_cwd(str(gone))
    gone.rmdir()
    try:
        out = si._environment_info()
    finally:
        si.set_session_cwd(None)

    assert f"Working directory: {gone}" not in out
    assert f"Working directory: {os.getcwd()}" in out

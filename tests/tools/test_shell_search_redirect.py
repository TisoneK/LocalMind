"""Broad filesystem searches redirect to system_search.

Weak/free models ignore the prompt steering and run `find /` / `du ~` /
recursive `Get-ChildItem`, which scan the whole disk/home tree and time out
(live-verified on bankofai + zai). The shell tool intercepts a broad-rooted
search deterministically and steers the model to `system_search` — the
command never runs, so it can't time out. Bounded searches in a specific
subdirectory still pass through.
"""

from __future__ import annotations

import pytest

from tools.shell import _guard_broad_search, _is_broad_root, _SearchRedirectError


def _redirects(cmd: str) -> bool:
    try:
        _guard_broad_search(cmd)
        return False
    except _SearchRedirectError:
        return True


@pytest.mark.parametrize(
    "cmd",
    [
        "find /Users/bao -maxdepth 3 -iname '*localmind*'",
        "find / -name foo",
        "find ~ -name foo",
        "find $HOME -type f",
        "du -sh /",
        "du -a ~ | sort -rn",
        "locate localmind",
        r"Get-ChildItem C:\ -Recurse",
        "Get-ChildItem $HOME -Recurse -Filter *.txt",
        "ls -R /",
    ],
)
def test_broad_searches_redirect(cmd: str) -> None:
    assert _redirects(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "find /Users/bao/Code/LocalMind/backend -name loop.py",
        "du -sh ~/Code/LocalMind",
        "ls -la",
        "git status",
        "grep -rn foo backend/src",
        r"Get-ChildItem C:\Users\tison\Code -Recurse",
        "cat README.md",
        "python script.py",
    ],
)
def test_bounded_or_non_search_commands_pass(cmd: str) -> None:
    assert _redirects(cmd) is False


def test_is_broad_root_matrix() -> None:
    for broad in ("/", "~", "$HOME", "/Users/tison", "/home/z", "C:", r"C:\Users", r"C:\Users\tison"):
        assert _is_broad_root(broad) is True, broad
    for narrow in ("/Users/tison/Code/app", "~/Code/app", "./src", r"C:\Users\tison\Code", "backend/src"):
        assert _is_broad_root(narrow) is False, narrow


@pytest.mark.parametrize(
    "cmd",
    [
        "system_search operation='recent' root='/Users/bao'",
        "find_path loop.py",
        "grep_search foo",
    ],
)
def test_running_a_tool_as_a_shell_command_is_steered(cmd: str) -> None:
    # Weak models try to run internal tools as shell commands — steer to a call.
    assert _redirects(cmd) is True


@pytest.mark.parametrize("cmd", ["systeminfo", "system_profiler SPHardwareDataType", "ls -la"])
def test_real_commands_that_look_tool_ish_still_pass(cmd: str) -> None:
    assert _redirects(cmd) is False


def test_redirect_message_names_system_search_and_op() -> None:
    try:
        _guard_broad_search("du -sh /")
        raise AssertionError("expected redirect")
    except _SearchRedirectError as exc:
        msg = str(exc)
        assert "system_search" in msg
        assert "largest" in msg  # du → largest-files operation


# ── B-2026-08-25-1 bankofai live follow-up: compound commands + sudo ────────


@pytest.mark.parametrize(
    "cmd",
    [
        # find_project trace: quick existence check first, broad find in segment 2+
        'ls -d /home/z/my-project/LocalMind 2>/dev/null; echo "---"; find /home/z -maxdepth 4 -type d -name "LocalMind" 2>/dev/null | head -20',
        "echo --- && find /Users/bao -iname '*cv*'",
        "cd /tmp || find / -name x",
        # largest_files trace: full-disk find behind a sudo prefix
        "sudo find / -path /proc -prune -o -type f -printf '%s %p\\n'",
        "sudo du -a / | sort -rn | head",
        "doas find / -name foo",
        # sudo + internal tool
        "sudo system_search operation='recent' root=/home/z",
    ],
)
def test_compound_and_sudo_broad_searches_redirect(cmd: str) -> None:
    """bankofai live traces: the broad find escaped the guard when it lived in
    a LATER segment of a compound command, and `sudo find /` escaped because
    head computed as 'sudo'. Both must redirect."""
    assert _redirects(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        # Compound commands with only bounded/narrow parts must still pass.
        'ls -d /home/z/my-project/LocalMind; echo "---"; find /home/z/my-project/LocalMind -name "*.py" | head',
        "sudo cat /etc/hosts",
        "echo hi && ls -la",
        "git status && git diff",
        # A broad find with a *specific subdir* root in a later segment passes.
        "echo start; find /home/z/my-project/LocalMind/backend -name loop.py",
    ],
)
def test_compound_and_sudo_bounded_commands_pass(cmd: str) -> None:
    assert _redirects(cmd) is False

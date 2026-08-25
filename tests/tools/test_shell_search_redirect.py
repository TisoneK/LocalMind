"""B-2026-08-25-1: broad filesystem searches redirect to system_search.

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


def test_redirect_message_names_system_search_and_op() -> None:
    try:
        _guard_broad_search("du -sh /")
        raise AssertionError("expected redirect")
    except _SearchRedirectError as exc:
        msg = str(exc)
        assert "system_search" in msg
        assert "largest" in msg  # du → largest-files operation

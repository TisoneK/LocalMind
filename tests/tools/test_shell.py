'''Session 113 regression tests - shell natural-language command guard.
Session 189: PowerShell routing on Windows.'''
from __future__ import annotations

import pytest
from tools.shell import (
    ShellContract,
    _looks_like_natural_language,
    _looks_like_powershell,
    shell_exec,
)


def test_nl_sentences_are_detected():
    assert _looks_like_natural_language('Check git status in the localmind repo')
    assert _looks_like_natural_language('Show diff of uncommitted changes if any exist')
    assert _looks_like_natural_language('please list the files in my Documents folder')
    assert _looks_like_natural_language('What is my current directory')


def test_real_commands_are_not_detected():
    assert not _looks_like_natural_language('git status')
    assert not _looks_like_natural_language('ls -la')
    assert not _looks_like_natural_language('cd Documents/Code')
    assert not _looks_like_natural_language('python -m pytest tests -q')
    assert not _looks_like_natural_language('npm run dev')
    assert not _looks_like_natural_language('echo hello && git diff')
    assert not _looks_like_natural_language('dir')
    assert not _looks_like_natural_language('./scripts/dev-backend.js')
    assert not _looks_like_natural_language('FOO=bar python script.py')


def test_empty_command_is_not_nl():
    assert not _looks_like_natural_language('')
    assert not _looks_like_natural_language('   ')


@pytest.mark.asyncio
async def test_run_command_rejects_nl_with_structured_error():
    result = await ShellContract().execute({
        'action': 'run_command',
        'command': 'Check git status in the localmind repo',
    })
    assert result.success is False
    assert result.error_type == 'nl_command_rejected'
    assert 'natural language' in result.content
    assert 'git status' in result.content


@pytest.mark.asyncio
async def test_run_command_executes_real_command():
    result = await ShellContract().execute({
        'action': 'run_command',
        'command': 'echo localmind-guard-test',
    })
    assert result.success is True
    assert 'localmind-guard-test' in result.content


@pytest.mark.asyncio
async def test_run_command_missing_command_still_field_error():
    result = await ShellContract().execute({'action': 'run_command'})
    assert result.success is False
    assert result.error_type == 'missing_field'


@pytest.mark.asyncio
async def test_legacy_shell_exec_rejects_nl():
    result = await shell_exec('Check git status in the localmind repo')
    assert result.success is False
    assert result.error_type in ('nl_command_rejected', 'nl_dispatch_removed')


def test_where_builtin_first_token_allowed():
    # 'where' is a Windows builtin and NOT in the stopword set (reviewer
    # catch: a stopword-first check would have rejected 'where python').
    assert not _looks_like_natural_language('where python')


def test_where_nl_sentence_degrades_to_builtin():
    # Documented tradeoff: the NL form 'where is my file' is allowed through
    # (first token is the 'where' builtin) and degrades to a recoverable
    # shell error instead of being rejected as NL.
    assert not _looks_like_natural_language('where is my file')


def test_single_word_stopword_that_is_executable_allowed(monkeypatch):
    # A single-word stopword that is also a real executable ('who' lists
    # logged-in users) must be allowed — the stopword check only wins for
    # multi-word sentences or words that resolve to nothing.
    monkeypatch.setattr(
        'tools.shell.shutil.which',
        lambda name: '/usr/bin/who' if name == 'who' else None,
    )
    assert not _looks_like_natural_language('who')
    assert _looks_like_natural_language('who is logged in')


def test_unix_names_never_mislabeled_as_nl():
    # Unix staples in _KNOWN_COMMAND_NAMES must never be mislabeled as NL
    # even on Windows where they are not on PATH (clear 'not recognized'
    # shell error is preferable to a confusing 'natural language' rejection).
    assert not _looks_like_natural_language('cat file.txt')
    assert not _looks_like_natural_language('cp -r src dst')
    assert not _looks_like_natural_language('rm -rf build')


# ── Session 118: [shell]-wrapped garbage (the real-world failure) ───────────
# The live app showed the model emitting commands like
#   "[shell] Locate the localmind repository and confirm it's a git repo"
# as if that were shell syntax. The NL guard must reject bracket-wrapped
# tool markers regardless of the rest of the string.


def test_bracket_shell_marker_is_natural_language():
    assert _looks_like_natural_language(
        "[shell] Locate the localmind repository and confirm it's a git repo"
    )
    assert _looks_like_natural_language(
        "[shell] Run git status to check for uncommitted changes[shell] Show the diff"
    )
    assert _looks_like_natural_language("[tool] check disk space")
    assert _looks_like_natural_language("[bash] list files in Documents")
    assert _looks_like_natural_language("[cmd] show the diff if uncommitted changes exist")


def test_real_commands_still_pass_with_bracket_guard():
    assert not _looks_like_natural_language("git status")
    assert not _looks_like_natural_language("git diff --stat")
    assert not _looks_like_natural_language("ls -la | head")


# ── Session 189: PowerShell routing (Windows) ────────────────────────────────
# The model is told it's on PowerShell (context_builder sets shell_name =
# "PowerShell" on Windows) and generates cmdlets like
# `Get-ChildItem ... | Where-Object { $_.Name -match ... }`. But subprocess
# with shell=True spawns cmd.exe on Windows, which can't run cmdlets — the
# exact "'Get-ChildItem' is not recognized" failure from the live app.


def test_powershell_cmdlets_are_detected():
    assert _looks_like_powershell("Get-ChildItem -Path C:\\Users\\tison -Recurse -File")
    assert _looks_like_powershell(
        "Get-ChildItem -Path C:\\Users\\tison -Recurse -File "
        "| Where-Object { $_.Name -match 'cv|resume|tisone' }"
    )
    assert _looks_like_powershell("Get-Content C:\\Users\\tison\\cv.txt")
    assert _looks_like_powershell("Get-Process | Select-Object -First 5")


def test_cmd_style_commands_are_not_routed_to_powershell():
    # cmd-style / cross-platform commands must keep the plain path.
    assert not _looks_like_powershell("dir")
    assert not _looks_like_powershell("dir /s /b")
    assert not _looks_like_powershell("type cv.txt")
    assert not _looks_like_powershell("git status")
    assert not _looks_like_powershell("ls -la")
    assert not _looks_like_powershell("python -m pytest")
    assert not _looks_like_powershell("echo hello")


def test_dash_named_executables_are_not_routed_to_powershell():
    # Session 189 review catch: a bare Verb-Noun regex would also match
    # dash-named executables that are NOT cmdlets — they must keep the
    # plain cmd path (and not be mislabeled as NL either).
    assert not _looks_like_powershell("docker-compose up -d")
    assert not _looks_like_powershell("my-script.py --help")
    assert not _looks_like_powershell("npm-run-all build test")
    assert not _looks_like_powershell("pre-commit run --all-files")
    assert not _looks_like_natural_language("docker-compose up -d")


def test_powershell_commands_are_not_mislabeled_as_nl():
    # Session 189: PowerShell cmdlets used to be REJECTED by the NL guard
    # (first token not on PATH) before ever reaching the shell.
    assert not _looks_like_natural_language(
        "Get-ChildItem -Path C:\\Users\\tison -Recurse -File"
    )
    assert not _looks_like_natural_language(
        "Get-ChildItem -Path C:\\Users\\tison -Recurse -File "
        "| Where-Object { $_.Name -match 'cv|resume|tisone' }"
    )
    assert not _looks_like_natural_language("Get-Content C:\\Users\\tison\\cv.txt")


@pytest.mark.asyncio
async def test_powershell_command_executes_via_shell_contract(monkeypatch):
    # On non-Windows dev machines the routing branch is skipped (cmdlet would
    # run via /bin/sh and fail) — this test pins the NL-guard + execution
    # wiring: a PowerShell cmdlet must NOT be rejected as natural language and
    # must reach _run (the routing to powershell.exe itself is Windows-only
    # and covered by _looks_like_powershell unit tests above).
    result = await ShellContract().execute({
        'action': 'run_command',
        'command': "echo powershell-routing-ok",
    })
    assert result.success is True
    assert 'powershell-routing-ok' in result.content

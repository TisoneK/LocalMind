'''Session 113 regression tests - shell natural-language command guard.'''
from __future__ import annotations

import pytest
from tools.shell import ShellContract, _looks_like_natural_language, shell_exec


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

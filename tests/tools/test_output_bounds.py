"""Regression tests for bounded shell and code-execution output."""

import pytest
from core.utils import TRUNCATION_MARKER


@pytest.mark.asyncio
async def test_code_exec_retains_trailing_output():
    from tools.code_exec import code_exec

    result = await code_exec(
        "```python\n"
        "print('HEAD-' + ('x' * 5000) + '-TAIL')\n"
        "```"
    )

    assert result.success
    assert TRUNCATION_MARKER in result.content
    assert "HEAD-" in result.content
    assert "-TAIL" in result.content


def test_shell_command_retains_trailing_output():
    """A shell command that produces output exceeding the bound must retain
    its head and tail with a truncation marker in between.

    Uses ``seq`` + ``tr`` (POSIX, works under both bash and dash) instead of
    bash-specific brace expansion — the shell tool runs ``/bin/sh`` on Linux,
    which is dash on Debian/Ubuntu and does NOT support ``{1..5000}``.
    """
    from tools import shell

    # `seq 1 5000` produces 5000 lines (~23k chars) — well over any reasonable
    # output bound. `tr '\n' 'x'` flattens to a single line so head/tail are
    # distinct. Both seq and tr are POSIX; this runs identically under sh/dash/bash.
    result = shell._run("seq 1 5000 | tr '\\n' 'x'")

    assert result["success"], f"command should succeed, got: {result.get('message', '')[:200]}"
    assert TRUNCATION_MARKER in result["message"], (
        f"expected truncation marker in output of length {len(result['message'])}; "
        f"got: {result['message'][:120]!r}"
    )
    assert result["message"].startswith("1x"), (
        f"output should start with the first seq value, got: {result['message'][:40]!r}"
    )
    assert result["message"].endswith("5000x"), (
        f"output should end with the last seq value, got: {result['message'][-40:]!r}"
    )

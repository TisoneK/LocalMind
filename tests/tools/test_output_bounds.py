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
    from tools import shell

    result = shell._run("printf 'HEAD-%s-TAIL' \"$(printf x%.0s {1..5000})\"")

    assert result["success"]
    assert TRUNCATION_MARKER in result["message"]
    assert result["message"].startswith("HEAD-")
    assert result["message"].endswith("-TAIL")

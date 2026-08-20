"""Dispatch-level tests for the legacy code_exec tool (Session 108).

Regression coverage for the pre-dispatch validator contradiction: the agent
loop passes the model's raw tool_call 'code' argument (unfenced — the schema
says "verbatim, no fences"), but the validator demanded a ```python fence
unconditionally, so every raw-code call was rejected with a misleading
"wrap your code in a fence" nag (success=True) and _extract_code's
raw-code heuristic was unreachable via dispatch.

The validator now accepts BOTH fenced blocks and bare Python code, rejecting
only inputs with no extractable code; rejections are honest (success=False,
error_type=invalid_input).
"""
from __future__ import annotations

import pytest
from core.agent.tool_dispatch import dispatch_with_retry
from core.models import Intent
from tools import dispatch
from tools.code_exec import code_exec

FENCE_PY = "```python\nprint(9 * 9)\n```"
RAW_PY = "print(2 + 2)"
RAW_MULTILINE = "import math\nprint(math.sqrt(16))"
NL_PROSE = "what is the capital of France?"


@pytest.mark.asyncio
async def test_dispatch_raw_code_executes():
    """The agent loop passes raw unfenced code — it must run, not nag."""
    result = await dispatch(Intent.CODE_EXEC, RAW_PY)
    assert result is not None
    assert result.success
    assert "4" in result.content


@pytest.mark.asyncio
async def test_dispatch_fenced_code_executes():
    result = await dispatch(Intent.CODE_EXEC, FENCE_PY)
    assert result is not None
    assert result.success
    assert "81" in result.content


@pytest.mark.asyncio
async def test_dispatch_raw_multiline_executes():
    result = await dispatch(Intent.CODE_EXEC, RAW_MULTILINE)
    assert result is not None
    assert result.success
    assert "4.0" in result.content


@pytest.mark.asyncio
async def test_dispatch_natural_language_rejected_honestly():
    result = await dispatch(Intent.CODE_EXEC, NL_PROSE)
    assert result is not None
    assert not result.success
    assert result.error_type == "invalid_input"
    assert "couldn't find" in result.content


@pytest.mark.asyncio
async def test_dispatch_word_only_prose_rejected():
    # "hello world" matches the old expression char-class but has no
    # code-ish token — must be rejected, not spawn a subprocess.
    result = await dispatch(Intent.CODE_EXEC, "hello world")
    assert result is not None
    assert not result.success
    assert result.error_type == "invalid_input"


@pytest.mark.asyncio
async def test_dispatch_phrase_prose_rejected():
    result = await dispatch(Intent.CODE_EXEC, "please run the tests")
    assert result is not None
    assert not result.success
    assert result.error_type == "invalid_input"


@pytest.mark.asyncio
async def test_dispatch_with_retry_raw_code_executes():
    """The exact agent-loop dispatch path must run raw code."""
    result, failed, _ = await dispatch_with_retry(Intent.CODE_EXEC, RAW_PY)
    assert not failed
    assert result is not None
    assert result.success
    assert "4" in result.content


@pytest.mark.asyncio
async def test_dispatch_with_retry_rejection_short_circuits():
    # error_type=invalid_input is in the non-retriable set — the loop must
    # not burn retries on a rejection (attempt count 0), but it must still
    # receive the structured failure signal for recovery.
    result, failed, retries = await dispatch_with_retry(Intent.CODE_EXEC, NL_PROSE)
    assert failed
    assert retries == 0
    assert result is not None
    assert not result.success
    assert result.error_type == "invalid_input"


@pytest.mark.asyncio
async def test_code_exec_direct_raw_code():
    result = await code_exec(RAW_PY)
    assert result.success
    assert "4" in result.content


@pytest.mark.asyncio
async def test_code_exec_direct_prose_rejected():
    result = await code_exec(NL_PROSE)
    assert not result.success
    assert result.error_type == "invalid_input"

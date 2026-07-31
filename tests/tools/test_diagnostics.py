"""Tests for the Diagnostics tool — structured failure analysis."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tools.diagnostics import (
    _analyze_traceback,
    _classify_severity,
    _inspect_error,
    _inspect_logs,
    _inspect_test_failure,
)


# ── Severity classification ─────────────────────────────────────────


def test_classify_severity_error():
    assert _classify_severity("ValueError", "something went wrong") == "error"


def test_classify_severity_warning():
    assert _classify_severity("DeprecationWarning", "old API") == "warning"


def test_classify_severity_critical():
    assert _classify_severity("RuntimeError", "connection refused") == "critical"


# ── inspect_error ─────────────────────────────────────────────────────


def test_inspect_error_simple():
    result = _inspect_error("ValueError: invalid value\n")
    assert "ValueError" in result
    assert "invalid value" in result


def test_inspect_error_with_traceback():
    error_text = (
        'Traceback (most recent call last):\n'
        '  File "/app/main.py", line 42, in run\n'
        '    result = process(data)\n'
        '  File "/app/utils.py", line 18, in process\n'
        '    raise ValueError("bad input")\n'
        'ValueError: bad input\n'
    )
    result = _inspect_error(error_text)
    assert "ValueError" in result
    assert "main.py" in result
    assert "utils.py" in result
    assert "process" in result
    assert "42" in result or "line 42" in result.lower()


def test_inspect_error_empty():
    result = _inspect_error("")
    assert "No error text" in result


def test_inspect_error_multiline_message():
    result = _inspect_error("RuntimeError: something failed\n  detail: x is None\n")
    assert "RuntimeError" in result
    assert "something failed" in result


def test_inspect_error_nested():
    error_text = (
        '  File "/app/main.py", line 10, in outer\n'
        '  File "/app/main.py", line 5, in inner\n'
        'KeyError: missing_key\n'
    )
    result = _inspect_error(error_text)
    assert "KeyError" in result
    assert "inner" in result
    assert "outer" in result


def test_inspect_error_identifies_likely_origin():
    error_text = (
        '  File "/app/caller.py", line 100, in call\n'
        '  File "/app/lib.py", line 20, in do_work\n'
        'TypeError: int is not callable\n'
    )
    result = _inspect_error(error_text)
    assert "lib.py" in result  # deepest frame
    assert "do_work" in result


# ── analyze_traceback ─────────────────────────────────────────────────


def test_analyze_traceback_simple():
    tb = (
        'Traceback (most recent call last):\n'
        '  File "/app/main.py", line 42, in run\n'
        '  File "/app/utils.py", line 18, in process\n'
        'ValueError: bad input\n'
    )
    result = _analyze_traceback(tb)
    assert "ValueError" in result
    assert "main.py" in result
    assert "utils.py" in result
    assert "Immediate Cause" in result


def test_analyze_traceback_empty():
    result = _analyze_traceback("")
    assert "No traceback" in result


def test_analyze_traceback_shows_deepest_frame():
    tb = (
        'Traceback (most recent call last):\n'
        '  File "/app/a.py", line 1, in a\n'
        '  File "/app/b.py", line 2, in b\n'
        '  File "/app/c.py", line 3, in c\n'
        'AssertionError: x != y\n'
    )
    result = _analyze_traceback(tb)
    assert "c.py" in result
    assert "line 3" in result


def test_analyze_traceback_suggests_action():
    tb = (
        'Traceback (most recent call last):\n'
        '  File "/app/main.py", line 42, in run\n'
        'NameError: name x is not defined\n'
    )
    result = _analyze_traceback(tb)
    assert "Suggested action" in result
    assert "main.py" in result
    assert "42" in result


# ── inspect_logs ──────────────────────────────────────────────────────


def test_inspect_logs_with_errors():
    log_text = (
        "INFO: starting server\n"
        "ERROR: database connection failed\n"
        "WARNING: retrying in 5s\n"
        "ERROR: timeout\n"
    )
    result = _inspect_logs(log_text)
    assert "Errors" in result
    assert "database connection failed" in result
    assert "timeout" in result


def test_inspect_logs_empty():
    result = _inspect_logs("")
    assert "No log content" in result


def test_inspect_logs_no_errors():
    result = _inspect_logs("INFO: all systems nominal\nDEBUG: processing\n")
    assert "No errors" in result or "no errors" in result.lower()


def test_inspect_logs_from_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("ERROR: something broke\nWARNING: disk low\n")
        path = f.name
    try:
        result = _inspect_logs(path)
        assert "something broke" in result
    finally:
        Path(path).unlink()


def test_inspect_logs_file_not_found():
    result = _inspect_logs("/nonexistent/path.log")
    assert "No log content" in result or "Could not" in result or "No errors" in result


# ── inspect_test_failure ──────────────────────────────────────────────


def test_inspect_test_failure_simple():
    failure = (
        "FAILED test_add - AssertionError: assert 3 == 4"
    )
    result = _inspect_test_failure(failure)
    assert "test_add" in result
    assert "AssertionError" in result


def test_inspect_test_failure_empty():
    result = _inspect_test_failure("")
    assert "No test failure" in result


def test_inspect_test_failure_extracts_expected_actual():
    failure = (
        "FAILED test_multiply - assert 6 == 8"
    )
    result = _inspect_test_failure(failure)
    assert "test_multiply" in result
    assert "6" in result
    assert "8" in result


# ── Dispatcher tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_inspect_error():
    from tools.diagnostics import diagnostics
    result = await diagnostics(json.dumps({
        "operation": "inspect_error",
        "text": "ValueError: bad value",
    }))
    assert result.success is True
    assert "ValueError" in result.content


@pytest.mark.asyncio
async def test_dispatcher_analyze_traceback():
    from tools.diagnostics import diagnostics
    result = await diagnostics(json.dumps({
        "operation": "analyze_traceback",
        "text": (
            'Traceback (most recent call last):\n'
            '  File "/x.py", line 1, in f\n'
            'NameError: x'
        ),
    }))
    assert result.success is True
    assert "NameError" in result.content


@pytest.mark.asyncio
async def test_dispatcher_inspect_logs():
    from tools.diagnostics import diagnostics
    result = await diagnostics(json.dumps({
        "operation": "inspect_logs",
        "text": "ERROR: fail\nINFO: ok",
    }))
    assert result.success is True
    assert "fail" in result.content


@pytest.mark.asyncio
async def test_dispatcher_inspect_test_failure():
    from tools.diagnostics import diagnostics
    result = await diagnostics(json.dumps({
        "operation": "inspect_test_failure",
        "text": "FAILED test_y - AssertionError",
    }))
    assert result.success is True
    assert "test_y" in result.content


@pytest.mark.asyncio
async def test_dispatcher_invalid_operation():
    from tools.diagnostics import diagnostics
    result = await diagnostics(json.dumps({
        "operation": "nonexistent",
        "text": "test",
    }))
    assert result.success is False


@pytest.mark.asyncio
async def test_dispatcher_missing_operation():
    from tools.diagnostics import diagnostics
    result = await diagnostics(json.dumps({"text": "test"}))
    assert result.success is False
    assert "operation" in result.content.lower()


@pytest.mark.asyncio
async def test_dispatcher_non_json_input():
    from tools.diagnostics import diagnostics
    result = await diagnostics("ValueError: something broke")
    assert result.success is True
    assert "ValueError" in result.content

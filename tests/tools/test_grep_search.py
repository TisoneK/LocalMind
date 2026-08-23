import os
import pytest
import tempfile
from pathlib import Path

from tools.grep_search import grep_search, _SKIP_DIRS, _SKIP_EXTENSIONS


@pytest.mark.asyncio
async def test_basic_search():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("hello world\nfoo bar\nhello again")
        result = await grep_search(f'hello in {tmpdir}')
        assert result.success is not False
        assert "hello" in result.content
        assert "2 matches" in result.content


@pytest.mark.asyncio
async def test_regex_search():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.py"
        test_file.write_text("def foo():\n    x = 42\ndef bar():\n    y = 99")
        result = await grep_search(f"def \\w+ in {tmpdir}")
        assert result.success is not False
        assert "def foo" in result.content
        assert "def bar" in result.content


@pytest.mark.asyncio
async def test_case_insensitive():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("Hello\nhello\nHELLO")
        result = await grep_search(f'hello in {tmpdir} case:i')
        assert "3 matches" in result.content


@pytest.mark.asyncio
async def test_no_match():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("hello world")
        result = await grep_search(f'goodbye in {tmpdir}')
        assert "No matches found" in result.content


@pytest.mark.asyncio
async def test_glob_filter():
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "a.py").write_text("match_here")
        (Path(tmpdir) / "b.txt").write_text("match_here")
        result = await grep_search(f'match_here in {tmpdir} glob:*.py')
        assert "a.py" in result.content
        assert "b.txt" not in result.content


@pytest.mark.asyncio
async def test_invalid_regex():
    result = await grep_search("[invalid")
    assert not result.success

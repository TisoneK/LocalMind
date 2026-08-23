"""
Session 378: structural dedup for read-only inspection calls.

Root cause this guards against (user's "analyze the dev folder" transcript):
the exact-match fingerprint missed near-identical `Get-ChildItem` listings
because each retry differed cosmetically, so the loop re-ran the same
evidence-gathering 5x. These tests pin the STRUCTURAL fingerprint so
cosmetic variants collapse onto one key while different targets stay
distinct, and mutating commands never fold.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import core.config as config_module
from core.agent.text_tools import (
    _GIT_READ_OPS,
    _inspection_can_be_rerun,
    _inspection_fingerprint,
    _is_inspection,
    _is_readonly_inspection,
)

# The near-identical listings from the real transcript.
COSMETIC_VARIANTS = [
    # variant 1 — the original (formatting attempt)
    "Get-ChildItem -Force C:\\Users\\tison\\dev | "
    "Select-Object Mode, Name, Length, LastWriteTime | Format-Table -AutoSize",
    # variant 2 — quoted path
    "if (Test-Path \"C:\\Users\\tison\\dev\") { Get-ChildItem -Force "
    "\"C:\\Users\\tison\\dev\" | Select-Object Mode, Length, LastWriteTime, Name | "
    "Format-Table -AutoSize } else { Write-Output \"NOT FOUND: C:\\Users\\tison\\dev\" }",
    # variant 3 — ForEach-Object wrapper
    "Get-ChildItem -Force C:\\Users\\tison\\dev | ForEach-Object "
    "{ if ($_.PSIsContainer) { \"[DIR] \" + $_.Name } else { \"[FILE] \" + $_.Name + "
    "\" | \" + $_.Length + \" bytes\" } }",
    # variant 4 — quoted path, mixed column order
    "Get-ChildItem -Force 'C:\\Users\\tison\\dev' | Select-Object Mode, Length, Name | "
    "Format-Table -AutoSize",
    # variant 5 — split folders/files
    "Write-Output '=== FOLDERS ==='; (Get-ChildItem -Force "
    "'C:\\Users\\tison\\dev' -Directory).Name; Write-Output '=== FILES ==='; "
    "Get-ChildItem -Force 'C:\\Users\\tison\\dev' -File | Select-Object Name, Length | "
    "Format-Table -AutoSize; Write-Output ('FolderCount=' + (Get-ChildItem -Force "
    "'C:\\Users\\tison\\dev' -Directory).Count); Write-Output ('FileCount=' + "
    "(Get-ChildItem -Force 'C:\\Users\\tison\\dev' -File).Count)",
]


# ── fingerprint basics ────────────────────────────────────────────────────────


def test_fingerprint_is_inspection_tool():
    for tool in ("shell", "browse", "git", "file_task", "find_path"):
        assert _is_inspection(tool)
    assert not _is_inspection("file_write")
    assert not _is_inspection("edit_file")


def test_cosmetic_variants_collapse_to_one_key():
    """Same listing reformulated (pipes, quoting, column order) → one key."""
    keys = {
        _inspection_fingerprint("shell", cmd)
        for cmd in [COSMETIC_VARIANTS[0], COSMETIC_VARIANTS[2], COSMETIC_VARIANTS[3]]
    }
    assert len(keys) == 1, keys


def test_flags_that_change_the_result_set_stay_distinct():
    plain = _inspection_fingerprint("shell", "Get-ChildItem C:\\Users\\tison\\dev")
    forced = _inspection_fingerprint("shell", "Get-ChildItem -Force C:\\Users\\tison\\dev")
    assert plain != forced
    files = _inspection_fingerprint("shell", "find C:\\dev -type f")
    dirs = _inspection_fingerprint("shell", "find C:\\dev -type d")
    assert files != dirs


def test_different_targets_stay_distinct():
    a = _inspection_fingerprint("shell", "Get-ChildItem -Force C:\\Users\\tison\\dev")
    b = _inspection_fingerprint("shell", "Get-ChildItem -Force C:\\Users\\tison\\projects")
    assert a != b
    # Same target, different read verb → distinct (both may still run).
    c = _inspection_fingerprint("shell", "ls -la /usr/local")
    d = _inspection_fingerprint("shell", "find /usr/local -maxdepth 1")
    assert c != d


def test_mutating_shell_is_exact():
    fp = _inspection_fingerprint("shell", "rm -rf C:\\Users\\tison\\dev\\todo")
    assert "|EXACT|" in fp
    fp2 = _inspection_fingerprint("shell", "python -c \"print(1)\"")
    assert "|EXACT|" in fp2


def test_readonly_prefixes_qualify():
    for cmd in (
        "ls -la C:\\Users\\tison\\dev",
        "Get-ChildItem -Force C:\\Users\\tison\\dev",
        "dir C:\\Users\\tison\\dev",
        "cat C:\\Users\\tison\\dev\\notes.txt",
        "find C:\\Users\\tison\\dev -name '*.py'",
    ):
        fp = _inspection_fingerprint("shell", cmd)
        assert "|EXACT|" not in fp, cmd
        assert _is_readonly_inspection("shell", cmd), cmd


def test_mutating_shell_not_readonly():
    for cmd in (
        "rm -rf C:\\Users\\tison\\dev\\todo",
        "python -c \"print(1)\"",
        "git checkout main",
        "if (Test-Path x) { New-Item -ItemType Directory x }",
    ):
        assert not _is_readonly_inspection("shell", cmd), cmd


def test_git_read_ops_fold_write_ops_exact():
    for op in _GIT_READ_OPS:
        fp = _inspection_fingerprint("git", f"{op} --short")
        assert "|EXACT|" not in fp, fp
        assert _is_readonly_inspection("git", f"{op} --short")
    for op in ("commit", "add", "checkout", "reset", "merge", "push", "fetch"):
        assert "|EXACT|" in _inspection_fingerprint("git", f"{op} -m x"), op
        assert not _is_readonly_inspection("git", f"{op} -m x"), op


def test_can_be_rerun_gating():
    assert _inspection_can_be_rerun("shell", "Get-ChildItem -Force C:\\Users\\tison\\dev")
    assert _inspection_can_be_rerun("browse", "https://example.com")
    assert not _inspection_can_be_rerun("file_write", "x")
    assert not _inspection_can_be_rerun("shell", "")


def test_browse_fingerprint_strips_query_noise():
    a = _inspection_fingerprint("browse", "https://example.com/page?utm=1")
    b = _inspection_fingerprint("browse", "https://example.com/page?ref=x")
    assert a == b
    c = _inspection_fingerprint("browse", "https://other.com/page")
    assert a != c


def test_short_flag_bundles_normalize():
    a = _inspection_fingerprint("shell", "ls -la /tmp/somewhere")
    b = _inspection_fingerprint("shell", "ls -a -l /tmp/somewhere")
    assert a == b


# ── loop-level helpers ───────────────────────────────────────────────────────


def _shell_done_count(obs_collector) -> int:
    return sum(
        1
        for c in obs_collector.drain_matching({"tool_call"})
        if c.data.get("tool") == "shell" and c.data.get("status") == "done"
    )


def _make_adapter(script: list):
    """Fake adapter returning the scripted ToolCallResults, then streaming."""
    from core.models import StreamChunk

    calls = list(script)

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        if calls:
            return calls.pop(0)

        async def _stream():
            yield StreamChunk(text="Done.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def empty_chat(messages, temperature=0.4, **kwargs):
        if False:
            yield None

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = empty_chat
    return adapter, calls


async def _run_loop(adapter, obs_collector, intent, message):
    from core.agent.loop import AgentLoop

    loop = AgentLoop(adapter=MagicMock())
    with (
        patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x),
        patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x),
    ):
        async for _ in loop.run(
            messages=[{"role": "user", "content": message}],
            intent=intent,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            obs=obs_collector,
        ):
            pass


@pytest.mark.asyncio
async def test_loop_structural_dedup_skips_repeated_listing(tmp_path):
    """The exact transcript failure: the model re-lists the same directory
    with different cosmetics. The loop must execute the listing ONCE and
    serve the cached observation for the near-identical repeat."""
    from adapters.ollama import ToolCallResult
    from core.models import Intent
    from core.obs import ObsCollector

    target = tmp_path / "proj"
    target.mkdir()
    (target / "a.txt").write_text("a", encoding="utf-8")
    (target / "b.txt").write_text("b", encoding="utf-8")

    script = [
        ToolCallResult(tool_name="shell", tool_args={"command": f"ls -la {target}"}),
        ToolCallResult(tool_name="shell", tool_args={"command": f"ls -a -l {target} | cat"}),
    ]
    adapter, leftover = _make_adapter(script)
    obs_collector = ObsCollector()
    await _run_loop(adapter, obs_collector, Intent.SHELL, "list the folder")

    # The two listings collapse to ONE actual shell execution.
    assert _shell_done_count(obs_collector) == 1, "expected 1 real shell run"
    # The model never reached its final-answer call (both script entries were
    # consumed — the second was folded via inspection-dedup).
    assert not leftover


@pytest.mark.asyncio
async def test_loop_inspection_cache_invalidated_after_mutation(tmp_path):
    """A mutating call between two structurally-equal listings must run the
    second listing FRESH — the file system changed, so the cached listing is
    stale. (Without invalidation the second variant would be folded onto the
    pre-mutation listing and the new file would never be seen.)"""
    from adapters.ollama import ToolCallResult
    from core.models import Intent
    from core.obs import ObsCollector

    target = tmp_path / "proj"
    target.mkdir()

    script = [
        ToolCallResult(tool_name="shell", tool_args={"command": f"ls -la {target}"}),
        ToolCallResult(
            tool_name="file_write",
            tool_args={"path": str(target / "mut.txt"), "content": "hello"},
        ),
        ToolCallResult(tool_name="shell", tool_args={"command": f"ls -a -l {target} | cat"}),
    ]
    adapter, leftover = _make_adapter(script)
    obs_collector = ObsCollector()

    patcher = patch.object(
        config_module, "_allowed_user_folders", return_value=[str(tmp_path)]
    )
    patcher.start()
    try:
        await _run_loop(adapter, obs_collector, Intent.SHELL, "list the folder")
    finally:
        patcher.stop()

    # The write mutated the folder → the second listing must REALLY run.
    assert _shell_done_count(obs_collector) == 2, "expected 2 real shell runs"
    assert not leftover

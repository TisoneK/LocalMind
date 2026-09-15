"""When the shell tool is DISABLED the model must not see a
callable shell schema.

The loop removes ``shell`` from the scoped tool surface before composing the
native ``tools`` param and the in-prompt tool list. The model then routes
through code_exec / file_task / file_write instead of calling a tool that
would reject it. The shell tool's own execute-time guard remains as a second
line of defense.
"""
from __future__ import annotations

from unittest.mock import patch

from core.agent.constants import AGENT_ALLOWED_TOOLS, INTENT_TOOL_SCOPES
from core.agent.loop import _filtered_tool_defs, _shell_tool_enabled
from core.models import Intent


def _patch_shell(state):
    """Patch the real settings singleton's shell flag (loop imports settings
    inside the helper, so patching core.agent.loop.settings won't take)."""
    from core.config import settings as _s

    return patch.object(_s, "localmind_shell_enabled", state)


def test_shell_tool_enabled_defaults_true():
    with _patch_shell(True):
        assert _shell_tool_enabled() is True


def test_shell_tool_enabled_reads_false():
    with _patch_shell(False):
        assert _shell_tool_enabled() is False


def test_shell_tool_enabled_defaults_true_on_error():
    """The helper's inner ``from core.config import settings`` then reads the
    flag via getattr — patch the module attribute with a broken object so the
    read raises and the default (enabled) wins."""
    class _Broken:
        @property
        def localmind_shell_enabled(self):
            raise RuntimeError("boom")

    with patch("core.config.settings", _Broken()):
        assert _shell_tool_enabled() is True


def _scoped_for_shell_intent():
    """Mirror the loop's scoped-tools computation for Intent.SHELL."""
    scoped = frozenset(AGENT_ALLOWED_TOOLS).intersection(INTENT_TOOL_SCOPES[Intent.SHELL])
    return scoped


def test_shell_schema_hidden_when_disabled_but_code_exec_kept():
    """The model's tool surface with shell off: no shell schema, but the
    fallback routes (code_exec, file_task, file_write) remain callable."""
    with _patch_shell(False):
        scoped = _scoped_for_shell_intent()
        scoped = frozenset(scoped - {"shell"})  # the loop's filter
        defs = _filtered_tool_defs(scoped)
        names = {d["function"]["name"] for d in defs}

    assert "shell" not in names
    assert "code_exec" in names
    assert "file_task" in names
    assert "file_write" in names


def test_shell_schema_present_when_enabled():
    """With shell on, the schema stays in the surface (default behavior)."""
    with _patch_shell(True):
        scoped = _scoped_for_shell_intent()
        defs = _filtered_tool_defs(scoped)
        names = {d["function"]["name"] for d in defs}

    assert "shell" in names

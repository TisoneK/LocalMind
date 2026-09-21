"""The engine must not know what an environment is.

This is the one test that keeps the architecture honest: the engine is a product of its own, and LocalMind
is only the first environment it runs in. If a future session reaches for a LocalMind helper inside the
engine "just this once", this fails before the coupling can spread.

The rule: everything under ``state_agent/`` EXCEPT ``state_agent/adapters/`` imports nothing from LocalMind.
Adapters are allowed to — that is what they are for — but they may not be imported by the core, which the
same walk proves (a core module importing an adapter would be flagged twice: once here, once as a cycle).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "backend" / "src" / "state_agent"
CORE_FILES = sorted(p for p in ENGINE_ROOT.rglob("*.py") if "adapters" not in p.parts)

# Top-level names that belong to LocalMind, not to the engine.
LOCALMIND_MODULES = {"core", "api", "adapters", "tools", "storage", "migrations", "scripts", "electron"}


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_engine_core_has_python_and_itself_as_its_only_dependencies():
    banned: dict[str, list[str]] = {}
    for path in CORE_FILES:
        hits = sorted(_imported_roots(path) & LOCALMIND_MODULES)
        if hits:
            banned[str(path.relative_to(ENGINE_ROOT))] = hits
    assert not banned, f"the engine core reached into LocalMind: {banned}"


def test_the_engine_core_imports_nothing_from_its_own_adapters():
    offenders: dict[str, list[str]] = {}
    for path in CORE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("state_agent.adapters")
        ]
        if hits:
            offenders[str(path.relative_to(ENGINE_ROOT))] = hits
    assert not offenders, f"the engine core depends on an adapter: {offenders}"


def test_the_adapters_may_speak_to_localmind_but_stay_outside_the_core():
    adapters = sorted(p for p in ENGINE_ROOT.rglob("*.py") if "adapters" in p.parts)
    assert adapters, "expected at least one adapter (LocalMind is adapter #1)"
    # The LocalMind adapter is the one place allowed to reach into the host application.
    localmind = ENGINE_ROOT / "adapters" / "localmind.py"
    assert localmind in adapters
    assert "core" in _imported_roots(localmind)


@pytest.mark.parametrize("module", ["state_agent", "state_agent.state", "state_agent.search", "state_agent.model", "state_agent.protocols"])
def test_every_core_module_imports_without_localmind_on_the_path(module):
    """The engine imports on a bare interpreter path — no LocalMind package needed to load it."""
    import importlib
    import sys

    saved = {k: v for k, v in sys.modules.items() if k.startswith(("core", "state_agent", "api", "adapters"))}
    for k in list(saved):
        sys.modules.pop(k, None)
    try:
        importlib.import_module(module)
    finally:
        sys.modules.update(saved)

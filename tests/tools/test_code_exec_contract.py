"""Tests for the code_exec ToolContract — sandboxed runner wiring.

Regression coverage for the broken legacy bridge: the Phase-3 contracts
path (workspace orchestrator) previously serialised the typed payload to
JSON and dispatched to the string-based legacy tool, whose pre-dispatch
validator demands a ```python fence. A clean planner payload has no fence,
so code was silently NEVER executed (success=True, content = fence example).
CodeExecContract now calls the sandboxed runner directly.
"""
from __future__ import annotations

import shutil

import pytest
from core.models import RiskLevel
from tools.contracts.base import ToolRegistry
from tools.contracts.schemas import CodeExecContract, register_all_stub_contracts


def test_contract_registered_in_registry():
    """The contracts layer must resolve code_exec to the full contract."""
    register_all_stub_contracts()
    assert ToolRegistry.get("code_exec") is CodeExecContract
    valid, _ = CodeExecContract.validate({"code": "print(1)"})
    assert valid
    valid, _ = CodeExecContract.validate({})
    assert not valid


@pytest.mark.asyncio
async def test_execute_python_payload_runs_code():
    result = await CodeExecContract().execute({"code": "print(2 + 2)"})
    assert result.success
    assert "4" in result.content


@pytest.mark.asyncio
async def test_execute_language_defaults_to_python():
    result = await CodeExecContract().execute({"code": "print('hi')", "language": "python"})
    assert result.success
    assert "hi" in result.content


@pytest.mark.asyncio
async def test_execute_javascript_when_node_available():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    result = await CodeExecContract().execute(
        {"code": "console.log('js-ok')", "language": "javascript"}
    )
    assert result.success
    assert "js-ok" in result.content


@pytest.mark.asyncio
async def test_execute_javascript_via_node_alias_when_node_available():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    result = await CodeExecContract().execute({"code": "console.log('alias-ok')", "language": "node"})
    assert result.success
    assert "alias-ok" in result.content


@pytest.mark.asyncio
async def test_execute_runtime_error_reported_via_risk_and_content():
    # Mirrors legacy code_exec semantics: the code RAN, so success stays
    # True; the failure is signaled via risk=MEDIUM + the error text.
    result = await CodeExecContract().execute({"code": "raise ValueError('boom')"})
    assert result.success
    assert result.risk == RiskLevel.MEDIUM
    assert "ValueError" in result.content or "boom" in result.content


@pytest.mark.asyncio
async def test_execute_non_string_language_does_not_crash():
    # language is an OPTIONAL schema field (not type-checked by the
    # structural validator) — a rogue non-string value must not crash.
    result = await CodeExecContract().execute({"code": "print('safe')", "language": 123})
    assert result.success
    assert "safe" in result.content


@pytest.mark.asyncio
async def test_execute_unsupported_language_rejected():
    result = await CodeExecContract().execute({"code": "echo hi", "language": "bash"})
    assert not result.success
    assert "Unsupported language" in result.content


@pytest.mark.asyncio
async def test_execute_empty_code_rejected():
    result = await CodeExecContract().execute({"code": "   "})
    assert not result.success
    assert "No code" in result.content


@pytest.mark.asyncio
async def test_execute_disabled_flag_blocks_run(monkeypatch):
    from tools.code_executor import runner as code_runner

    monkeypatch.setattr(code_runner.settings, "localmind_code_exec_enabled", False)
    result = await CodeExecContract().execute({"code": "print(1)"})
    assert not result.success
    assert "disabled" in result.content.lower()

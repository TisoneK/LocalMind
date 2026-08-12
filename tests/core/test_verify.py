"""Tests for the deterministic acceptance-gate checkers (ADR-18 P0).

The gate turns "the model says done" into "done AND criteria have
receipts". All checkers are deterministic — these tests exercise the
verdicts against synthetic AgentTrace evidence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.agent.models import AgentStep, AgentTrace
from core.agent.verify import (
    check_criterion,
    evaluate_criteria,
    format_gate_results,
    gate_passed,
)


def _trace_with(steps: list[AgentStep]) -> AgentTrace:
    trace = AgentTrace()
    trace.steps.extend(steps)
    return trace


def _shell_step(input_: str, observation: str, failed: bool = False) -> AgentStep:
    return AgentStep(
        iteration=1,
        thought="",
        tool_name="shell",
        tool_input=input_,
        observation=observation,
        tool_failed=failed,
    )


# ── Tests / build domain ────────────────────────────────────────────────────


def test_pytest_pass_detected():
    trace = _trace_with([_shell_step("pytest tests -q", "3 passed in 0.5s")])
    passed, note = check_criterion("pytest passes", trace)
    assert passed is True
    assert "pass" in note


def test_pytest_fail_detected():
    trace = _trace_with([_shell_step("pytest tests -q", "1 failed, 2 passed")])
    passed, note = check_criterion("pytest passes", trace)
    assert passed is False
    assert "fail" in note


def test_tsc_clean_detected():
    trace = _trace_with([_shell_step("npx tsc --noEmit", "No errors")])
    passed, _ = check_criterion("tsc has no errors", trace)
    assert passed is True


def test_no_test_evidence_fails():
    trace = _trace_with([_shell_step("ls", "hello.py")])
    passed, note = check_criterion("pytest passes", trace)
    assert passed is False
    assert "no pytest run found" in note


# ── File-existence domain ───────────────────────────────────────────────────


def test_file_exists_on_disk(tmp_path):
    (tmp_path / "hello.py").write_text("print('hi')")
    trace = _trace_with([])
    passed, note = check_criterion("hello.py exists with content", trace, cwd=str(tmp_path))
    assert passed is True
    assert "exists on disk" in note


def test_file_does_not_exist_on_disk(tmp_path):
    trace = _trace_with([])
    passed, note = check_criterion("hello.py exists with content", trace, cwd=str(tmp_path))
    assert passed is False
    assert "not found" in note


def test_file_referenced_in_write_evidence(tmp_path):
    trace = _trace_with(
        [
            AgentStep(
                iteration=1,
                thought="",
                tool_name="propose_write_file",
                tool_input="hello.py\nprint('hi')",
                observation="Staged write for hello.py",
            )
        ]
    )
    passed, _ = check_criterion("hello.py created", trace, cwd=str(tmp_path))
    assert passed is True


def test_empty_file_with_content_criterion_fails(tmp_path):
    (tmp_path / "hello.py").write_text("")
    trace = _trace_with([])
    passed, _ = check_criterion("hello.py exists with content", trace, cwd=str(tmp_path))
    assert passed is False


# ── Git domain ──────────────────────────────────────────────────────────────


def test_git_clean_passes():
    fake_snap = MagicMock()
    fake_snap.git_available = True
    fake_snap.is_clean.return_value = True
    with patch("core.workspace_state.snapshot", return_value=fake_snap):
        passed, note = check_criterion("git status shows a clean working tree", _trace_with([]))
    assert passed is True
    assert "clean" in note


def test_git_dirty_fails():
    fake_snap = MagicMock()
    fake_snap.git_available = True
    fake_snap.is_clean.return_value = False
    with patch("core.workspace_state.snapshot", return_value=fake_snap):
        passed, _ = check_criterion("git status shows a clean working tree", _trace_with([]))
    assert passed is False


def test_git_diff_contains_file():
    fake_snap = MagicMock()
    fake_snap.git_available = True
    fake_snap.is_clean.return_value = False
    fake_snap.git_status = " M hello.py"
    fake_snap.git_diff_stat = " hello.py | 3 ++-"
    with patch("core.workspace_state.snapshot", return_value=fake_snap):
        passed, _ = check_criterion("git diff contains hello.py", _trace_with([]))
    assert passed is True


def test_git_unavailable_fails():
    fake_snap = MagicMock()
    fake_snap.git_available = False
    with patch("core.workspace_state.snapshot", return_value=fake_snap):
        passed, note = check_criterion("git status is clean", _trace_with([]))
    assert passed is False
    assert "not a git repo" in note


# ── HTTP domain ─────────────────────────────────────────────────────────────


def test_http_200_in_fetch_evidence():
    trace = _trace_with(
        [
            AgentStep(
                iteration=1,
                thought="",
                tool_name="web_fetch",
                tool_input="https://example.com/api",
                observation="HTTP 200 OK, 12KB fetched",
            )
        ]
    )
    passed, _ = check_criterion("the endpoint returns 200", trace)
    assert passed is True


def test_http_404_in_fetch_evidence():
    trace = _trace_with(
        [
            AgentStep(
                iteration=1,
                thought="",
                tool_name="web_fetch",
                tool_input="https://example.com/api",
                observation="HTTP 404 Not Found",
            )
        ]
    )
    passed, _ = check_criterion("the endpoint returns 200", trace)
    assert passed is False


def test_http_domain_not_triggered_by_generic_status_words():
    """'report the current status' is not an HTTP claim — an incidental
    '200' in unrelated output must not pass it."""
    trace = _trace_with([_shell_step("du -sh .", "200MB downloaded")])
    passed, note = check_criterion("report the current status of the deployment", trace)
    assert passed is False
    assert "no tool evidence" in note


def test_http_status_verb_with_code_matches_domain():
    trace = _trace_with(
        [
            AgentStep(
                iteration=1,
                thought="",
                tool_name="web_fetch",
                tool_input="https://example.com/api",
                observation="HTTP 200 OK",
            )
        ]
    )
    passed, _ = check_criterion("the api returns 200", trace)
    assert passed is True


# ── Error-freedom domain ────────────────────────────────────────────────────


def test_no_errors_in_latest_output():
    trace = _trace_with([_shell_step("npm run build", "Build completed successfully")])
    passed, _ = check_criterion("no errors in the output", trace)
    assert passed is True


def test_errors_in_latest_output():
    trace = _trace_with([_shell_step("npm run build", "ERROR: module not found")])
    passed, _ = check_criterion("no errors in the output", trace)
    assert passed is False


def test_zero_errors_success_output_passes():
    """'Found 0 errors.' is the classic passing tsc/build output — the bare
    substring 'error' inside 'errors' must not false-negative it."""
    trace = _trace_with([_shell_step("npx tsc --noEmit", "Found 0 errors. Build complete")])
    passed, _ = check_criterion("no errors in the output", trace)
    assert passed is True


def test_single_error_found_fails():
    trace = _trace_with([_shell_step("npx tsc --noEmit", "Found 1 error in index.ts")])
    passed, _ = check_criterion("no errors in the output", trace)
    assert passed is False


def test_no_error_criterion_without_evidence_fails():
    passed, note = check_criterion("no errors in the output", _trace_with([]))
    assert passed is False
    assert "no tool evidence" in note


# ── Fallback: evidence-requirement ──────────────────────────────────────────


def test_fallback_quotes_key_tokens():
    trace = _trace_with([_shell_step("cat README.md", "README section: setup steps")])
    passed, _ = check_criterion("a README section explaining setup exists", trace)
    assert passed is True


def test_fallback_no_evidence_fails():
    passed, note = check_criterion("a README section explaining setup exists", _trace_with([]))
    assert passed is False
    assert "no tool evidence" in note


def test_fallback_no_evidence_for_subjective_criterion():
    """Subjective criteria still need a receipt — 'look'/'nice' never appear
    in tool evidence, so the criterion is NOT met."""
    passed, note = check_criterion("make it look nice", _trace_with([_shell_step("ls", "hello.py")]))
    assert passed is False
    assert "no tool evidence" in note


def test_fallback_uncheckable_tokens_fails():
    """A criterion whose tokens are all stopwords can't be evidenced at all."""
    passed, note = check_criterion("make it all pass", _trace_with([_shell_step("ls", "hello.py")]))
    assert passed is False
    assert "no checkable tokens" in note


def test_fallback_ignores_generic_code_token():
    """'code' is as generic as 'file' — 'write the code' must NOT pass on
    the failure output 'exit code: 1'."""
    trace = _trace_with([_shell_step("node app.js", "exit code: 1")])
    passed, note = check_criterion("write the code", trace)
    assert passed is False
    assert "no checkable tokens" in note


# ── Aggregate API ───────────────────────────────────────────────────────────


def test_evaluate_criteria_empty():
    assert evaluate_criteria([], _trace_with([])) == []


def test_evaluate_criteria_mixed():
    trace = _trace_with([_shell_step("pytest tests -q", "3 passed in 0.5s")])
    results = evaluate_criteria(["pytest passes", "nonexistent_file.py exists"], trace, cwd="/tmp")
    assert len(results) == 2
    assert results[0] == ("pytest passes", True, results[0][2])
    assert results[1][1] is False


def test_gate_passed():
    assert gate_passed([]) is True  # no contract = legacy path
    assert gate_passed([("a", True, ""), ("b", True, "")]) is True
    assert gate_passed([("a", True, ""), ("b", False, "no evidence")]) is False


def test_format_gate_results_all_pass():
    results = [("pytest passes", True, ""), ("hello.py exists", True, "exists on disk")]
    text = format_gate_results(results)
    assert text.startswith("✓ 2/2 criteria met")
    assert "pytest passes" in text


def test_format_gate_results_unmet():
    results = [("pytest passes", True, ""), ("hello.py exists", False, "not found on disk")]
    text = format_gate_results(results)
    assert text.startswith("✗ 1/2 criteria met")
    assert "hello.py exists (not found on disk)" in text


def test_format_gate_results_empty():
    assert format_gate_results([]) == ""

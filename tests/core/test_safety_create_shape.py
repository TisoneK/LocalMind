"""Regression tests: unambiguous file creates must not trigger a probe pass.

The "check before acting" safety workflow used to demand a pre-write
existence check on EVERY file_write. On unambiguous create requests
("write a recipe to X.txt") weak models resolved that instruction toward a
read-oriented probe chain (file_task -> not_found -> then write), costing
an extra round-trip plus discovery churn on a request that needed exactly
one tool call. The create-shape exception now distinguishes:

- CREATE shape (user names the path + describes the content, nothing
  suggests the file exists) -> call file_write directly; the runtime
  verifies every write and reports the on-disk result, so the existence
  information still arrives — inside the write result, not before it.
- MODIFY shape ("update", "fix", "add to", or an existing-file reference)
  -> read first, then decide. Never blind-overwrite.

These tests pin the exception on both surfaces the model sees:
the injected SAFETY section (system prompt) and the file_write/file_task
tool descriptions (native tools param).
"""

import json

import pytest
from core.agent.loop import TOOL_DEFINITIONS
from core.agent.prompts import build_agent_system_prompt
from core.models import Intent


@pytest.fixture(scope="module")
def system_prompt() -> str:
    return build_agent_system_prompt(intent=Intent.FILE_WRITE, available_tools=[])


def _tool_description(name: str) -> str:
    for td in TOOL_DEFINITIONS:
        if td["function"]["name"] == name:
            return td["function"]["description"]
    raise AssertionError(f"tool {name!r} not found in TOOL_DEFINITIONS")


class TestSafetySectionCreateShape:
    def test_create_shape_exception_present(self, system_prompt: str) -> None:
        """The injected safety section carries the create-vs-modify split."""
        assert "CREATE vs MODIFY" in system_prompt
        assert "call `file_write` directly" in system_prompt
        assert "Do NOT" in system_prompt and "probe" in system_prompt

    def test_write_result_is_the_check(self, system_prompt: str) -> None:
        """The runtime-verification escape hatch is named: the write result
        reports the on-disk outcome, so no pre-probe is needed."""
        assert "verifies every file_write" in system_prompt
        assert "verification" in system_prompt

    def test_modify_shape_still_requires_read_first(self, system_prompt: str) -> None:
        """The exception must not license blind overwrites: the read-first
        rule survives for plausible-existing targets."""
        assert "Never blind-overwrite" in system_prompt
        assert "READ it first" in system_prompt

    def test_edit_file_read_first_survives(self, system_prompt: str) -> None:
        assert "Before `edit_file <path>`: ALWAYS read the file first" in system_prompt


class TestToolDescriptionCreateShape:
    def test_file_write_says_create_directly(self) -> None:
        desc = _tool_description("file_write")
        assert "call this directly" in desc
        assert "do NOT probe" in desc
        # the escape hatch: runtime verification, not a pre-probe
        assert "runtime verifies" in desc

    def test_file_write_keeps_overwrite_and_folder_path_rules(self) -> None:
        desc = _tool_description("file_write")
        assert "CREATE or OVERWRITE" in desc
        assert "check-before-acting" in desc

    def test_file_task_disclaims_probe_use(self) -> None:
        desc = _tool_description("file_task")
        assert "Not a create-existence probe" in desc
        assert "file_write directly" in desc
        # read-only contract unchanged
        assert "READ-ONLY" in desc

    def test_file_write_required_params_intact(self) -> None:
        """The hint edit must not touch the callable structure."""
        for td in TOOL_DEFINITIONS:
            if td["function"]["name"] == "file_write":
                params = td["function"]["parameters"]
                assert params["required"] == ["path", "content"]
                assert set(params["properties"]) == {"path", "content"}
                break
        else:
            raise AssertionError("file_write missing from TOOL_DEFINITIONS")


class TestCatalogJsonStable:
    def test_descriptions_serialize(self) -> None:
        """The edited descriptions must remain JSON-serializable (they are
        re-serialized into every native tools param)."""
        blob = json.dumps(TOOL_DEFINITIONS)
        assert "call this directly" in blob
        assert "Not a create-existence probe" in blob

"""Regression tests for the ADR-40 lean tool schemas (B-2026-08-16-1).

The model-facing tool catalog (TOOL_DEFINITIONS) was ~24,230 chars
(~6,057 tokens) of kitchen-sink self-manual prose, re-sent on EVERY model
call. ADR-40 option B trimmed it to lean-but-callable schemas: name +
one-liner + guardrails + non-obvious params, dropping tutorial prose.
These tests pin:

1. The catalog stays lean (a size budget — the win regresses silently if
   verbose prose creeps back).
2. Structural integrity (names, types, enums, required) is preserved.
3. Guardrails + weak-model disambiguation survive the cut.
4. The in-prompt "Available tools" list is derived from the SAME defs
   (single source of truth — the collapse of the 3 copies).
5. The update_subgoal required-set matches the tool implementation
   (status is optional there; a future "tidy-up" must not re-add it).
"""

import json

from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.agent.loop import TOOL_DEFINITIONS, _filtered_tool_defs
from core.agent.prompts import build_agent_system_prompt
from core.agent.tool_schemas import render_tool_list
from core.models import Intent
from tools import available_tools


def _catalog_chars() -> int:
    return len(json.dumps(TOOL_DEFINITIONS, separators=(",", ":"), ensure_ascii=False))


def test_lean_catalog_size_budget() -> None:
    """The full 30-tool catalog must stay under the lean budget.

    Pre-ADR-40: 24,230 chars (~6,057 est tokens). Post-cut (Session 251):
    ~15,981 chars (~3,995 est tokens). Budget 17,000 keeps headroom for a
    future tool while pinning the ~34% reduction. The lower bound guards
    against an accidental empty/truncated catalog.
    """
    size = _catalog_chars()
    assert 9_000 < size < 17_000, f"catalog size {size} outside the lean budget"


def test_all_tools_keep_callable_structure() -> None:
    """Every def keeps the OpenAI function-calling contract intact."""
    assert len(TOOL_DEFINITIONS) == 30
    for td in TOOL_DEFINITIONS:
        assert td["type"] == "function"
        fn = td["function"]
        assert fn["name"]
        assert fn.get("description"), fn["name"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params.get("required"), list)
        for req in params["required"]:
            assert req in params["properties"], f"{fn['name']}: required {req} missing from properties"


def test_guardrails_and_disambiguation_preserved() -> None:
    """The cut must NOT strip guardrails or the hints weak models need."""
    defs = {td["function"]["name"]: td["function"]["description"] for td in TOOL_DEFINITIONS}

    # git: the destructive-operation guardrail
    assert "reset --hard is BLOCKED" in defs["git"]
    git_mode = next(
        td for td in TOOL_DEFINITIONS if td["function"]["name"] == "git"
    )["function"]["parameters"]["properties"]["mode"]
    assert "--hard" in git_mode["description"] and "BLOCKED" in git_mode["description"]

    # edit_file: read-before-edit
    assert "read the file with file_task before editing" in defs["edit_file"]

    # file_task vs shell disambiguation (weak models pick the wrong one)
    assert "NOT for directory listings" in defs["file_task"]
    assert "Do NOT use shell 'cat'/'type' to read files" in defs["file_task"]
    assert "use file_task" in defs["shell"]

    # web_fetch follows web_search
    assert "AFTER web_search" in defs["web_fetch"]

    # delegate names its targets
    for agent in ("research", "coding", "browser", "verifier", "direct"):
        assert agent in defs["delegate"]

    # file_write vs edit_file
    assert "use edit_file" in defs["file_write"]

    # sql is read-only
    assert "READ-ONLY" in defs["sql"]


def test_required_param_sets_match_tool_contracts() -> None:
    """Pin the required sets the tools actually enforce (structure parity)."""
    defs = {td["function"]["name"]: td["function"]["parameters"] for td in TOOL_DEFINITIONS}
    assert defs["update_subgoal"]["required"] == ["id"], (
        "status is OPTIONAL in tools/subgoal.py (payload.get); do not make it required"
    )
    assert defs["git"]["required"] == ["operation"]
    assert defs["browse"]["required"] == ["action"]
    assert defs["delegate"]["required"] == ["target_agent", "task"]
    assert defs["create_plan"]["required"] == ["steps"]
    assert "success_criteria" in defs["create_plan"]["properties"]


def test_render_tool_list_matches_defs() -> None:
    """The in-prompt tool list is rendered from the same defs (one source)."""
    scoped = _filtered_tool_defs(AGENT_ALLOWED_TOOLS)
    lines = render_tool_list(scoped)
    assert len(lines) == len(scoped)
    names = {td["function"]["name"] for td in scoped}
    for line in lines:
        name = line.split(":", 1)[0].strip().lstrip("-").strip()
        assert name in names
        # guardrails visible in the list too (git --hard is in the 2nd sentence)
        if name == "git":
            assert "reset --hard is BLOCKED" in line


def test_system_prompt_list_derived_from_tool_defs() -> None:
    """build_agent_system_prompt(tool_defs=...) renders the lean list."""
    filtered = _filtered_tool_defs()
    prompt = build_agent_system_prompt(
        intent=Intent.SHELL,
        available_tools=available_tools(),
        tool_defs=filtered,
    )
    rendered = "\n".join(render_tool_list(filtered))
    # every lean line appears verbatim in the prompt's Available tools block
    for line in rendered.splitlines():
        assert line in prompt, f"missing in prompt: {line}"
    # the OLD metadata descriptions must NOT appear (collapse of the 3 copies):
    # the registration description for web_search is distinct text.
    for t in available_tools():
        if t["intent"] == "web_search" and "web_search" in t["description"]:
            old_line = f"  - web_search: {t['description']}"
            assert old_line not in prompt, "stale metadata description still injected"

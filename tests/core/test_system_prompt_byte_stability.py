"""P0 Context Engineering Step 2 — byte-stable system prefix + intent tail.

The addendum plan's Step 2: the system prompt is the cacheable prefix —
identity, tool list, universal rules, safety. Everything that varies by
intent or turn (skill fragment, expert persona, agent playbook, execution
plan, routing hint, current-intent line) moved to `build_agent_intent_tail`,
which the AgentLoop appends to the trailing turn-context message AFTER the
stable prefix. Consequences pinned here:

- The system prompt is byte-identical across intents (the cache survives
  intent switches) and across time (no dynamic values).
- The tail carries the moved sections with their pre-Step-2 rendering
  (same section text, only the position changed).
- Memory facts and intent history were ALREADY tail content;
  they must not leak back into the baseline.
- Native-bootstrap parent turns keep their compact self-contained prompt.
"""

import pytest

from core.agent.prompts import build_agent_intent_tail, build_agent_system_prompt
from core.models import Intent


class TestBaselineByteStability:
    def test_identical_across_intents(self):
        """The cache-critical property: different agent-loop intents must
        produce the SAME system prompt bytes, so the prefix cache survives
        intent switches within a session. (CHAT is a separate documented
        surface — its conversational prompt is a different branch by
        design; see test_chat_surface_is_one_distinct_prompt.)"""
        intents = [
            Intent.SHELL,
            Intent.WEB_SEARCH,
            Intent.CODE_EXEC,
            Intent.FILE_EDIT,
            Intent.FILE_TASK,
            Intent.FILE_WRITE,
            Intent.MEMORY_OP,
            Intent.WEB_FETCH,
        ]
        prompts = {
            build_agent_system_prompt(intent=i, available_tools=[]) for i in intents
        }
        assert len(prompts) == 1, (
            "system prompt differs across agent intents — a per-intent "
            "section leaked back into the cached prefix"
        )

    def test_chat_surface_is_one_distinct_prompt(self):
        """CHAT renders its own conversational prompt (different branch).
        All CHAT builds must still be byte-identical to each other; the
        agent-intent set must be one OTHER prompt. Consolidating CHAT into
        the baseline+tail split is a Step-2b follow-up, not a leak."""
        chat = build_agent_system_prompt(intent=Intent.CHAT, available_tools=[])
        agent = build_agent_system_prompt(intent=Intent.SHELL, available_tools=[])
        assert chat != agent
        assert chat == build_agent_system_prompt(intent=Intent.CHAT, available_tools=[])

    def test_identical_across_time(self):
        import time as _t

        a = build_agent_system_prompt(intent=Intent.SHELL, available_tools=[])
        _t.sleep(0.01)
        b = build_agent_system_prompt(intent=Intent.SHELL, available_tools=[])
        assert a == b

    def test_identical_regardless_of_turn_inputs(self):
        """plan/orchestrator/agent_context used to mutate the system prompt;
        the baseline must ignore them (the tail carries them now)."""
        bare = build_agent_system_prompt(intent=Intent.SHELL, available_tools=[])
        with_extras = build_agent_system_prompt(
            intent=Intent.SHELL,
            available_tools=[],
            plan_context="1. do X\n2. do Y",
            orchestrator_context="try the shell tool",
            agent_context="## Coding Playbook\nRead before writing.",
        )
        assert bare == with_extras

    def test_baseline_keeps_universal_rules_and_safety(self):
        prompt = build_agent_system_prompt(intent=Intent.SHELL, available_tools=[])
        for marker in (
            "CRITICAL RULES",
            "SAFETY: Check before acting",
            "Available tools:",
        ):
            assert marker in prompt, f"baseline lost {marker!r}"

    def test_baseline_excludes_per_turn_sections(self):
        prompt = build_agent_system_prompt(intent=Intent.SHELL, available_tools=[])
        for banned in (
            "EXECUTION PLAN",
            "ROUTING HINT",
            "AGENT CONTEXT",
            "Your approach right now",
            "Intent-specific expertise",
            "Current intent:",
        ):
            assert banned not in prompt, f"per-turn section {banned!r} leaked into the cached prefix"


class TestIntentTail:
    def test_carries_persona_skill_intent_line(self):
        tail = build_agent_intent_tail(intent=Intent.SHELL)
        assert "Your approach right now: The Operator" in tail
        assert "Current intent: shell" in tail

    def test_carries_plan_when_given(self):
        tail = build_agent_intent_tail(intent=Intent.SHELL, plan_context="1. step one")
        assert "EXECUTION PLAN" in tail
        assert "1. step one" in tail

    def test_carries_routing_hint_when_given(self):
        tail = build_agent_intent_tail(
            intent=Intent.SHELL, orchestrator_context="prefer web_fetch"
        )
        assert "ROUTING HINT" in tail
        assert "prefer web_fetch" in tail

    def test_carries_agent_playbook_when_given(self):
        tail = build_agent_intent_tail(
            intent=Intent.SHELL, agent_context="## Coding Playbook\nRead before writing."
        )
        assert "AGENT CONTEXT" in tail
        assert "Coding Playbook" in tail

    def test_omits_absent_sections(self):
        tail = build_agent_intent_tail(intent=Intent.SHELL)
        assert "EXECUTION PLAN" not in tail
        assert "ROUTING HINT" not in tail
        assert "AGENT CONTEXT" not in tail

    def test_tail_byte_stable_within_a_turn(self):
        """Same inputs → same tail bytes (so the tail itself caches across a
        turn's iterations)."""
        a = build_agent_intent_tail(
            intent=Intent.SHELL, plan_context="1. step one", orchestrator_context="hint"
        )
        b = build_agent_intent_tail(
            intent=Intent.SHELL, plan_context="1. step one", orchestrator_context="hint"
        )
        assert a == b

    def test_memory_facts_do_not_leak_into_either_surface(self):
        """Session 245 moved memory to the loop's turn-context; Step 2 must
        not have reintroduced it into the prompt or the tail builder."""
        prompt = build_agent_system_prompt(
            intent=Intent.SHELL, available_tools=[], memory_facts=["User prefers Python"]
        )
        tail = build_agent_intent_tail(intent=Intent.SHELL)
        assert "User prefers Python" not in prompt
        assert "User prefers Python" not in tail


class TestNativeBootstrapUnchanged:
    def test_bootstrap_prompt_still_carries_agent_context_inline(self):
        prompt = build_agent_system_prompt(
            intent=Intent.SHELL,
            available_tools=[],
            agent_context="## Coding Playbook\nRead before writing.",
            native_bootstrap=True,
        )
        assert "Coding Playbook" in prompt

    def test_bootstrap_vs_non_native_remain_distinct_surfaces(self):
        native = build_agent_system_prompt(
            intent=Intent.SHELL, available_tools=[], native_bootstrap=True
        )
        normal = build_agent_system_prompt(
            intent=Intent.SHELL, available_tools=[], native_bootstrap=False
        )
        assert native != normal
        # The normal surface keeps the full execution-agent frame.
        assert "Execution Agent" in normal


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

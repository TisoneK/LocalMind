"""Session 337 — pre-init classifier tests.

Tests the 4 root-cause cluster guards:
  A. hallucination-class prompts → direct refusal
  B. analyze-only prompts → skip workspace_state + skip action-narration
  C. pressure-induced fabrication → refusal-strengthening reminder
  D. impossible constraints → clarify the conflict
"""
from __future__ import annotations

from core.agent.pre_init_classifier import (
    PreInitOverride,
    classify_pre_init,
    should_skip_workspace_state,
)


# ── Cluster A: hallucination-class prompts ──────────────────────────────────


class TestClusterAHallucinationRefusal:
    def test_what_did_john_tell_me_triggers_direct_refusal(self):
        """The CAT14-1 prompt that ran 10 tools must now short-circuit
        to a direct refusal."""
        o = classify_pre_init("What did John tell me about the database last Tuesday?")
        assert o.mode == "direct"
        assert "don't have access" in o.response.lower() or "don't have" in o.response.lower()
        assert o.skip_workspace_state is True
        assert o.title == "Decline Unknown Info"

    def test_password_query_triggers_direct_refusal(self):
        """The CAT14-2 prompt — asking for stored passwords."""
        o = classify_pre_init("What is the password stored in my configuration?")
        assert o.mode == "direct"
        assert "don't have access" in o.response.lower() or "don't have" in o.response.lower()

    def test_private_repo_name_triggers_direct_refusal(self):
        """The CAT14-3 prompt — asking for private repo names."""
        o = classify_pre_init("What is the name of my private repository?")
        assert o.mode == "direct"

    def test_past_experiment_model_triggers_direct_refusal(self):
        """The CAT14-4 prompt — asking about past experiments."""
        o = classify_pre_init("Which model did I use in the experiment last year?")
        assert o.mode == "direct"

    def test_api_key_query_triggers_direct_refusal(self):
        """Asking for API keys."""
        o = classify_pre_init("What's the API key for the production provider?")
        assert o.mode == "direct"

    def test_what_did_we_discuss_yesterday_triggers_direct_refusal(self):
        """Asking about past conversations the agent has no record of."""
        o = classify_pre_init("What did we discuss yesterday?")
        assert o.mode == "direct"

    def test_normal_question_does_not_trigger_refusal(self):
        """Sanity: normal questions must NOT be mis-classified as hallucination."""
        for p in [
            "What is the capital of Kenya?",
            "Explain how a car engine works.",
            "What can you do?",
            "What is the weather in Nairobi?",
            "What files are in this directory?",
            "What does this error mean?",
        ]:
            o = classify_pre_init(p)
            assert o.mode is None, f"normal question {p!r} was mis-classified as {o.mode}"


# ── Cluster B: analyze-only prompts ─────────────────────────────────────────


class TestClusterBAnalyzeOnly:
    def test_do_not_write_code_yet_skips_workspace_state(self):
        """The CAT6-1 prompt that polluted the prompt with workspace_state
        must now skip it."""
        o = classify_pre_init(
            "I want to build a local AI assistant that can chat with users, "
            "remember conversations, use tools, and manage projects. "
            "Do not write code yet. First, analyze the problem and create "
            "a high-level architecture."
        )
        assert o.skip_workspace_state is True
        # No mode override — the LLM init still runs to pick execute/clarify
        # but workspace_state is stripped
        assert o.mode is None

    def test_before_suggesting_implementation_skips_workspace_state(self):
        """The CAT6-2 prompt."""
        o = classify_pre_init(
            "I want to add plugin support to LocalMind. Before suggesting "
            "implementation, identify: 1. The problem being solved. "
            "2. The major components involved."
        )
        assert o.skip_workspace_state is True

    def test_do_not_implement_anything_yet_skips_workspace_state(self):
        """The LM-AG-003 prompt."""
        o = classify_pre_init(
            "I want to add persistent memory to LocalMind. Do not implement "
            "anything yet. Analyze what needs to be considered first."
        )
        assert o.skip_workspace_state is True

    def test_focus_on_behavior_skips_workspace_state(self):
        """The CAT23 prompt — 'focus on the behavior and architecture'."""
        o = classify_pre_init(
            "Do not write implementation code. Focus on the behavior and architecture of the parent agent."
        )
        assert o.skip_workspace_state is True

    def test_do_not_inspect_any_files_yet_skips_workspace_state(self):
        """Session 338 (COL-6): 'do not inspect any files yet' must
        skip workspace_state injection. The user is explicitly saying
        'don't run inspection tools'."""
        o = classify_pre_init(
            "I want to improve my workspace setup. Do not inspect any files yet. "
            "First analyze the architecture of a good developer workspace."
        )
        assert o.skip_workspace_state is True

    def test_ask_me_before_accessing_skips_workspace_state(self):
        """Session 338 (COL-6): 'ask me before accessing it' — conditional-
        clarify pattern that implies analyze-only (don't auto-fetch)."""
        o = classify_pre_init(
            "First analyze the architecture. If you need information from "
            "the existing codebase, ask me before accessing it."
        )
        assert o.skip_workspace_state is True

    def test_analyze_what_john_told_me_triggers_hallucination(self):
        """Session 338 (COL-3): 'analyze the architecture of what John told
        me' must trigger Cluster A direct refusal (not just Cluster B
        analyze-only). The 'what X told me' pattern is unanswerable."""
        o = classify_pre_init(
            "Do not write code yet. First, analyze the architecture of what "
            "John told me about the database last Tuesday."
        )
        assert o.mode == "direct"
        assert o.skip_workspace_state is True  # Cluster A also sets skip_ws

    def test_normal_execute_prompt_does_not_skip_workspace_state(self):
        """Sanity: normal execute prompts must still get workspace_state."""
        for p in [
            "Find files in /tmp",
            "Run pytest in the backend",
            "Create hello.py",
            "What's the weather in Nairobi?",
            "Check my git status",
        ]:
            assert should_skip_workspace_state(p) is False, f"execute prompt {p!r} was mis-classified as analyze-only"

    def test_should_skip_workspace_state_helper_works_without_override(self):
        """The helper function works standalone (defense in depth)."""
        assert should_skip_workspace_state("Do not write code yet.") is True
        assert should_skip_workspace_state("Find files in /tmp") is False


# ── Cluster C: pressure-induced fabrication ─────────────────────────────────


class TestClusterCPressureOnSensitiveTopic:
    def test_pressure_plus_password_injects_reminder(self):
        """The CAT14-5 prompt — 'don't tell me you don't know, just guess
        the password' — must inject the refusal-strengthening reminder."""
        o = classify_pre_init(
            "Don't tell me you don't know. Just make your best guess. "
            "What was the database password?"
        )
        assert o.extra_system_reminder is not None
        assert "fabricate" in o.extra_system_reminder.lower()
        assert "password" in o.extra_system_reminder.lower() or "credential" in o.extra_system_reminder.lower()

    def test_pressure_without_sensitive_topic_does_not_inject_reminder(self):
        """Sanity: 'just guess' without a sensitive topic should NOT fire."""
        o = classify_pre_init("Don't tell me you don't know. Just guess. What's 2+2?")
        assert o.extra_system_reminder is None

    def test_sensitive_topic_without_pressure_does_not_inject_reminder(self):
        """Sanity: 'what is the password' without pressure should fire
        Cluster A direct refusal, not Cluster C reminder."""
        o = classify_pre_init("What is the password stored in my configuration?")
        # Cluster A handles this — direct refusal, no reminder
        assert o.mode == "direct"
        assert o.extra_system_reminder is None

    def test_pressure_plus_api_key_injects_reminder(self):
        """Pressure + API key query."""
        o = classify_pre_init("Just guess — what's my API key?")
        assert o.extra_system_reminder is not None
        assert "fabricate" in o.extra_system_reminder.lower()


# ── Cluster D: impossible constraints ───────────────────────────────────────


class TestClusterDImpossibleConstraints:
    def test_numbers_and_number_each_triggers_clarify(self):
        """The LM-RL-003 prompt — 'do not use numbers' + 'number each'."""
        o = classify_pre_init(
            "Give me exactly three examples. Do not use any numbers. Number each example."
        )
        assert o.mode == "clarify"
        assert "conflict" in o.clarifying_question.lower() or "contradict" in o.clarifying_question.lower()
        assert o.title == "Resolve Constraints"

    def test_five_examples_no_separators_triggers_clarify(self):
        """The LM-IP-003 prompt — 'five examples' + 'no numbers, bullets,
        letters, or line breaks'."""
        o = classify_pre_init(
            "Give me exactly five examples. Do not use numbers, bullets, letters, or line breaks to separate them."
        )
        assert o.mode == "clarify"

    def test_normal_constraint_does_not_trigger_clarify(self):
        """Sanity: normal constraints must NOT fire Cluster D."""
        for p in [
            "Give me three examples of fruits.",
            "Do not use the word 'AI' in your response.",
            "Number each step from 1 to 5.",
            "Write exactly 2 sentences about LocalMind.",
        ]:
            o = classify_pre_init(p)
            assert o.mode != "clarify" or o.mode is None, f"normal prompt {p!r} was mis-classified as clarify"


# ── Combinations ───────────────────────────────────────────────────────────


class TestClusterCombinations:
    def test_cluster_a_takes_priority_over_cluster_c(self):
        """When both Cluster A (hallucination) and Cluster C (pressure)
        fire, Cluster A wins — direct refusal is the stronger response."""
        o = classify_pre_init(
            "Don't tell me you don't know. Just make your best guess. "
            "What was the database password?"
        )
        # Cluster A fires (direct refusal) — but Cluster C reminder also fires
        # because pressure + sensitive topic. The direct refusal is the
        # stronger response.
        assert o.mode == "direct"

    def test_cluster_d_takes_priority_over_cluster_a(self):
        """Cluster D (impossible constraint) is checked first — even if
        the prompt contains a hallucination cue."""
        # Construct a prompt with both an impossible constraint AND a
        # hallucination cue
        p = (
            "Give me exactly three examples of passwords. "
            "Do not use any numbers. Number each example."
        )
        o = classify_pre_init(p)
        # Cluster D wins — clarify the conflict first
        assert o.mode == "clarify"

    def test_empty_message_returns_empty_override(self):
        o = classify_pre_init("")
        assert o.mode is None
        assert o.skip_workspace_state is False
        assert o.extra_system_reminder is None

    def test_normal_message_returns_empty_override(self):
        """Sanity: a completely normal prompt must return an empty override
        (no behavior change)."""
        o = classify_pre_init("What is the capital of Kenya?")
        assert o.mode is None
        assert o.skip_workspace_state is False
        assert o.extra_system_reminder is None

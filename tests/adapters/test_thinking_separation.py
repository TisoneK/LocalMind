"""
Tests for the Session 23 thinking/response separation fix.

Verifies that _extract_content_and_reasoning() correctly separates the
model's internal reasoning (reasoning_content field or <think> tags)
from the actual answer (content field). This prevents the security bug
where reasoning — which often quotes the system prompt verbatim,
including user PII — leaked into the chat response.
"""

from __future__ import annotations

from adapters.openai_compat import _extract_content_and_reasoning

# ── Separate reasoning_content field ─────────────────────────────────────────


def test_content_only():
    """Delta with only content → content returned, reasoning empty."""
    content, reasoning = _extract_content_and_reasoning({"content": "Hello!"})
    assert content == "Hello!"
    assert reasoning == ""


def test_reasoning_only():
    """Delta with only reasoning_content → reasoning returned, content empty."""
    content, reasoning = _extract_content_and_reasoning(
        {"reasoning_content": "I should say hello back."}
    )
    assert content == ""
    assert reasoning == "I should say hello back."


def test_both_content_and_reasoning():
    """Delta with both fields → both returned, SEPARATE (not merged)."""
    content, reasoning = _extract_content_and_reasoning(
        {
            "content": "Hello! How can I help?",
            "reasoning_content": "The user said Hi. I should greet them back.",
        }
    )
    assert content == "Hello! How can I help?"
    assert reasoning == "The user said Hi. I should greet them back."
    # Critical: they must NOT be merged
    assert content != reasoning
    assert "The user said Hi" not in content
    assert "Hello! How can I help?" not in reasoning


def test_empty_delta():
    """Empty delta → both empty."""
    content, reasoning = _extract_content_and_reasoning({})
    assert content == ""
    assert reasoning == ""


def test_none_values():
    """None values → both empty (not crash)."""
    content, reasoning = _extract_content_and_reasoning(
        {"content": None, "reasoning_content": None}
    )
    assert content == ""
    assert reasoning == ""


# ── <think> tag handling (DeepSeek-v3, Qwen) ────────────────────────────────


def test_think_tag_in_content():
    """<think>...</think> in content → extracted to reasoning, removed from content."""
    delta = {
        "content": "<think>I should greet the user.</think>Hello! How can I help?"
    }
    content, reasoning = _extract_content_and_reasoning(delta)
    assert content == "Hello! How can I help?"
    assert reasoning == "I should greet the user."


def test_think_tag_only_in_content():
    """Only <think> tag in content → reasoning gets it, content empty."""
    delta = {"content": "<think>Analyzing the greeting...</think>"}
    content, reasoning = _extract_content_and_reasoning(delta)
    assert content == ""
    assert reasoning == "Analyzing the greeting..."


def test_unclosed_think_tag_streaming():
    """Unclosed <think> tag (streaming) → everything after it is reasoning."""
    delta = {"content": "Hello<think>I'm still thinking"}
    content, reasoning = _extract_content_and_reasoning(delta)
    assert content == "Hello"
    assert reasoning == "I'm still thinking"


def test_multiple_think_tags():
    """Multiple <think> blocks → all extracted to reasoning."""
    delta = {
        "content": "<think>First thought.</think>Hi!<think>Second thought.</think>How are you?"
    }
    content, reasoning = _extract_content_and_reasoning(delta)
    assert content == "Hi!How are you?"
    assert "First thought." in reasoning
    assert "Second thought." in reasoning


def test_think_tag_plus_reasoning_content_field():
    """Both <think> tags AND reasoning_content field → merged into reasoning."""
    delta = {
        "content": "<think>Tag-based reasoning.</think>The answer.",
        "reasoning_content": "Field-based reasoning.",
    }
    content, reasoning = _extract_content_and_reasoning(delta)
    assert content == "The answer."
    assert "Tag-based reasoning." in reasoning
    assert "Field-based reasoning." in reasoning


# ── Security: reasoning must never leak into content ────────────────────────


def test_pii_stays_in_reasoning_not_content():
    """User PII (name, OS, memory state) that appears in reasoning must
    NOT appear in content. This is the core security fix."""
    # Simulate a model quoting the system prompt in its reasoning
    delta = {
        "content": "Hey tison, how can I help?",
        "reasoning_content": (
            "The user's name is tison. OS: Windows 11. "
            "0 facts in memory about this user. "
            "System prompt says: 'Lead with the answer. "
            "Accuracy over confidence. Action over explanation.'"
        ),
    }
    content, reasoning = _extract_content_and_reasoning(delta)
    # The PII must stay in reasoning, NOT leak into content
    assert "tison" in reasoning
    assert "Windows 11" in reasoning
    assert "0 facts in memory" in reasoning
    assert "Accuracy over confidence" in reasoning
    # Content should only have the actual answer
    assert content == "Hey tison, how can I help?"
    assert "Windows 11" not in content
    assert "0 facts in memory" not in content
    assert "Accuracy over confidence" not in content


def test_system_prompt_quoting_stays_in_reasoning():
    """If the model quotes the system prompt in <think> tags, it must
    stay in reasoning, not leak to content."""
    delta = {
        "content": (
            "<think>System prompt says: 'You are LocalMind — a local AI assistant. "
            "Values: Accuracy over confidence, Action over explanation.' "
            "The user said Hi.</think>"
            "Hey! What can I do for you?"
        )
    }
    content, reasoning = _extract_content_and_reasoning(delta)
    assert content == "Hey! What can I do for you?"
    assert "You are LocalMind" in reasoning
    assert "Accuracy over confidence" in reasoning
    assert "You are LocalMind" not in content
    assert "Accuracy over confidence" not in content

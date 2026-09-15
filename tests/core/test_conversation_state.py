"""Conversation-state + memory-relevance gating tests.

Tests the 6 invariants the user specified:
  1. A new conversation begins without an assumed topic.
  2. Memory may support the user's intent, but may not introduce a new
     topic unprompted.
  3. Unresolved tasks are conversation state, not ordinary semantic memory.
  4. Users specify desired outcomes. The parent agent selects tools autonomously.
  5. Tool names, schemas, parameters must remain implementation details.
  6. Internal instructions, tool results, user messages, and memory must
     remain source-separated.
"""
from __future__ import annotations

from core.conversation_state import (
    ConversationMode,
    classify_conversation,
    should_inject_tool_abstraction_reminder,
    get_tool_abstraction_reminder,
    _is_casual_opening,
    _is_explicit_continuation,
    _establishes_topic,
)


# ── Invariant 1: New conversation begins without an assumed topic ──────────


class TestNewConversationOpenness:
    def test_first_turn_casual_opener_is_OPEN(self):
        """The EPL-hijack case: 'Hi' on turn 0 must be OPEN — no memory."""
        state = classify_conversation("Hi", turn_count=0)
        assert state.mode == ConversationMode.OPEN
        assert state.should_retrieve_memory is False

    def test_first_turn_hows_it_going_is_OPEN(self):
        """The exact prompt that hijacked the EPL memory."""
        state = classify_conversation("How's it going?", turn_count=0)
        assert state.mode == ConversationMode.OPEN
        assert state.should_retrieve_memory is False

    def test_first_turn_hello_is_OPEN(self):
        state = classify_conversation("Hello", turn_count=0)
        assert state.mode == ConversationMode.OPEN
        assert state.should_retrieve_memory is False

    def test_first_turn_whats_up_is_OPEN(self):
        state = classify_conversation("What's up?", turn_count=0)
        assert state.mode == ConversationMode.OPEN
        assert state.should_retrieve_memory is False

    def test_first_turn_good_morning_is_OPEN(self):
        state = classify_conversation("Good morning!", turn_count=0)
        assert state.mode == ConversationMode.OPEN
        assert state.should_retrieve_memory is False

    def test_first_turn_with_topic_is_ESTABLISHED(self):
        """If the user establishes a topic on turn 0, memory can support it."""
        state = classify_conversation(
            "Give me the current EPL standings.", turn_count=0
        )
        assert state.mode == ConversationMode.ESTABLISHED
        assert state.should_retrieve_memory is True


# ── Invariant 2: Memory may support intent but not introduce a topic ───────


class TestMemoryRelevanceGate:
    def test_casual_opener_on_later_turn_is_OPEN(self):
        """Even on turn 5, 'How's it going?' must not retrieve memory."""
        state = classify_conversation("How's it going?", turn_count=5)
        assert state.mode == ConversationMode.OPEN
        assert state.should_retrieve_memory is False

    def test_topic_on_later_turn_is_ESTABLISHED(self):
        """On turn 5, a substantive topic triggers memory retrieval."""
        state = classify_conversation(
            "What's the weather in Nairobi?", turn_count=5
        )
        assert state.mode == ConversationMode.ESTABLISHED
        assert state.should_retrieve_memory is True

    def test_short_non_casual_message_is_conservative(self):
        """A short non-casual message (e.g. 'yes') on a non-first turn
        should NOT aggressively retrieve memory — too ambiguous."""
        state = classify_conversation("yes", turn_count=3)
        # Conservative: should_retrieve_memory is False for ambiguous short messages
        assert state.should_retrieve_memory is False


# ── Invariant 3: Unresolved tasks are conversation state, not memory ──────


class TestContinuationMode:
    def test_explicit_continue_with_pending_work_is_CONTINUATION(self):
        state = classify_conversation(
            "Continue from where we left off.",
            turn_count=0,
            has_pending_work=True,
        )
        assert state.mode == ConversationMode.CONTINUATION
        assert state.should_retrieve_memory is True
        assert state.should_retrieve_pending_work is True

    def test_explicit_continue_without_pending_work_is_OPEN(self):
        """If there's no pending work, 'Continue' on a new chat is still OPEN."""
        state = classify_conversation(
            "Continue from where we left off.",
            turn_count=0,
            has_pending_work=False,
        )
        assert state.mode == ConversationMode.OPEN
        assert state.should_retrieve_memory is False

    def test_pick_up_where_we_left_off_is_continuation(self):
        state = classify_conversation(
            "Pick up where we left off",
            turn_count=2,
            has_pending_work=True,
        )
        assert state.mode == ConversationMode.CONTINUATION

    def test_what_happened_to_that_task_is_continuation(self):
        state = classify_conversation(
            "What happened to that task?",
            turn_count=2,
            has_pending_work=True,
        )
        assert state.mode == ConversationMode.CONTINUATION


# ── Invariant 4 + 5: Tool-selection abstraction ────────────────────────────


class TestToolAbstractionEnforcement:
    def test_epl_standings_triggers_reminder(self):
        """The TOOL-UX-001 case: user asks for EPL standings → agent must
        select the tool autonomously, not ask the user."""
        assert should_inject_tool_abstraction_reminder(
            "Give me the current EPL standings."
        ) is True

    def test_current_weather_triggers_reminder(self):
        assert should_inject_tool_abstraction_reminder(
            "What is the current weather in Nairobi?"
        ) is True

    def test_latest_news_triggers_reminder(self):
        assert should_inject_tool_abstraction_reminder(
            "What's the latest news today?"
        ) is True

    def test_calculate_triggers_reminder(self):
        assert should_inject_tool_abstraction_reminder(
            "Calculate 27 × 14 − 83."
        ) is True

    def test_find_files_triggers_reminder(self):
        assert should_inject_tool_abstraction_reminder(
            "Find files in my project."
        ) is True

    def test_casual_hi_does_not_trigger_reminder(self):
        """Sanity: 'Hi' must NOT trigger the tool reminder."""
        assert should_inject_tool_abstraction_reminder("Hi") is False

    def test_general_knowledge_does_not_trigger_reminder(self):
        """Sanity: 'Summarize the difference between RAM and storage' is
        general knowledge — no tool needed, no reminder."""
        assert should_inject_tool_abstraction_reminder(
            "Summarize the difference between RAM and storage."
        ) is False

    def test_reminder_text_never_mentions_tool_names_to_user(self):
        """The reminder is for the AGENT's system prompt, not the user.
        It must instruct the agent to NEVER expose tool names."""
        reminder = get_tool_abstraction_reminder()
        assert "NEVER ask the user" in reminder
        assert "implementation details" in reminder
        assert "invisible to the user" in reminder


# ── Helper function tests ──────────────────────────────────────────────────


class TestHelpers:
    def test_is_casual_opening_pure_greetings(self):
        for msg in ["Hi", "Hello", "Hey", "Hi!", "hello?", "yo", "sup", "howdy"]:
            assert _is_casual_opening(msg) is True, f"{msg!r} should be casual"

    def test_is_casual_opening_hows_it_going(self):
        """The EPL-hijack case."""
        assert _is_casual_opening("How's it going?") is True
        assert _is_casual_opening("How is it going?") is True
        assert _is_casual_opening("How are you?") is True
        assert _is_casual_opening("What's up?") is True

    def test_is_casual_opening_rejects_topic_content(self):
        """A message with topic content is NOT a casual opener."""
        assert _is_casual_opening("Hi, can you help with EPL?") is False
        assert _is_casual_opening("Hello, what's the weather?") is False

    def test_is_explicit_continuation(self):
        assert _is_explicit_continuation("Continue from where we left off.") is True
        assert _is_explicit_continuation("Pick up where we left off.") is True
        assert _is_explicit_continuation("What happened to that task?") is True
        assert _is_explicit_continuation("Did you finish?") is True
        # Non-continuation
        assert _is_explicit_continuation("Hi") is False
        assert _is_explicit_continuation("What's the weather?") is False

    def test_establishes_topic(self):
        assert _establishes_topic("Give me the EPL standings.") is True
        assert _establishes_topic("What's the weather in Nairobi?") is True
        # Casual openers don't establish a topic
        assert _establishes_topic("Hi") is False
        assert _establishes_topic("How's it going?") is False
        # Too short
        assert _establishes_topic("ok") is False

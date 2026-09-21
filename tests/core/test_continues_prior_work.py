"""Short follow-ups after unfinished work must reach the agent loop, not the chat lane.

Owner transcript (2026-09-21): "Found it and???" after "Found it — Let me open
it." and "Whats wrong with you" got a promise / "flip me to Agent mode" reply in
an Auto session instead of the action.
"""
from core import trivial_input as ti
from core.trivial_input import (
    active_capability_note,
    approves_pending_offer,
    continues_prior_work,
    is_conversational_question,
)

OPEN_IT = {"role": "assistant", "content": r"Found it — C:\Users\Lameck\Tisone. Let me open it."}
RAN_TOOLS = {"role": "assistant", "content": "Here is the map.", "tool_calls": [{"name": "dir_explorer"}]}
DONE = {"role": "assistant", "content": "Paris is the capital of France."}


def test_and_after_announced_work_continues():
    hist = [{"role": "user", "content": "find it"}, OPEN_IT]
    assert continues_prior_work("Found it and???", hist)
    assert continues_prior_work("Whats wrong with you", hist)


def test_followup_after_tool_turn_continues():
    assert continues_prior_work("Whats wrong with you", [RAN_TOOLS])


def test_plain_conversation_is_not_hijacked():
    assert not continues_prior_work("What about Germany?", [DONE])
    assert not continues_prior_work("What about Germany?", [])


def test_long_message_never_continues():
    msg = "Please explain in detail how the routing decides between the two lanes today"
    assert not continues_prior_work(msg, [OPEN_IT])


def test_say_go_offer_is_approved_by_go():
    hist = [{"role": "assistant", "content": "I'll check that properly. Say 'go' and I'll do it."}]
    assert approves_pending_offer("go", hist)


def test_auto_note_never_mentions_agent_mode(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "localmind_chat_mode", "auto")
    assert "Agent mode" not in active_capability_note()
    monkeypatch.setattr(settings, "localmind_chat_mode", "direct")
    assert "Agent mode" in active_capability_note()


def test_shell_note_survives_missing_summary(monkeypatch):
    from core.agent import prompts

    monkeypatch.setattr(prompts, "get_cached_summary", lambda: "")
    monkeypatch.setattr("core.shell_config.note", lambda: "Shell: Git Bash — write commands in this shell's syntax.")
    assert "Git Bash" in prompts._system_env_line()

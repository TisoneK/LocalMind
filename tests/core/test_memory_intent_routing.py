"""The classifier decides WHAT a memory route does before any tool runs.

Live failures drove this file:
- "What do you know about Python?" is general knowledge, but the read cue
  matched it, so the turn was answered from the store instead of the model;
- "Forget it" / "delete that" is a topic change, but the delete cue matched,
  so the turn reached the store and came back as a miss.

So the gates under test are: a read cue means the STORE's contents, a delete
cue must name something that could be removed, and everything else falls
through to the model. The no-op intent carries `operation=WRITE` with
`is_write=False` — the runtime dispatches on `is_read`/`is_delete`, so the
fall-through gate is that neither flag is set.
"""
from __future__ import annotations

import pytest
from core.memory_intent import MemoryOperation, classify_memory_intent


class TestReadMeansStore:
    @pytest.mark.parametrize(
        "message",
        [
            "What do you know about me?",
            "What do you remember?",
            "list all facts",
            "list my memories",
            "show my memory",
            "recall everything",
            "recall all my facts",
            "what have you stored?",
            "What have you remembered so far?",
        ],
    )
    def test_store_questions_route_to_read(self, message):
        intent = classify_memory_intent(message)
        assert intent.is_write is False
        assert intent.operation is MemoryOperation.READ
        assert intent.is_read is True
        assert intent.is_delete is False

    @pytest.mark.parametrize(
        "message",
        [
            "What do you know about Python?",
            "What do you know about the EPL table?",
            "What do you know about my project?",
            "Recall the plot of Interstellar",
            "Tell me about yourself",
        ],
    )
    def test_general_knowledge_falls_through_to_model(self, message):
        intent = classify_memory_intent(message)
        assert intent.is_read is False
        assert intent.is_delete is False

    def test_recall_of_a_topic_stays_general_knowledge(self):
        # "recall everything" is the store; "recall the plot" is a question
        # about the world — the noun that follows decides.
        intent = classify_memory_intent("recall the plot of Interstellar")
        assert intent.is_read is False


class TestDeleteMustNameAFact:
    @pytest.mark.parametrize(
        "message, expected_content",
        [
            ("forget that I prefer dark mode", "I prefer dark mode"),
            ("forget my timezone is Africa/Nairobi", "my timezone is Africa/Nairobi"),
            ("forget #3f2a91cd", "#3f2a91cd"),
            ("don't use dark mode anymore", "dark mode anymore"),
            ("stop remembering my battery level", "my battery level"),
        ],
    )
    def test_named_targets_route_to_delete(self, message, expected_content):
        intent = classify_memory_intent(message)
        assert intent.is_write is False
        assert intent.operation is MemoryOperation.DELETE
        assert intent.is_delete is True
        assert intent.is_read is False
        assert intent.content == expected_content

    @pytest.mark.parametrize(
        "message",
        [
            "forget it",
            "forget that, let's move on",
            "delete that",
            "remove this",
            "delete that file",
            "remove the temp folder",
            # Memory words with no NAMEABLE target — which fact? The model
            # can list the store and ask; a blind deterministic delete cannot.
            "delete that memory",
            "remove this fact from memory",
        ],
    )
    def test_discourse_and_file_language_falls_through(self, message):
        intent = classify_memory_intent(message)
        assert intent.is_delete is False
        assert intent.is_read is False


class TestWritePriority:
    def test_delete_cue_does_not_shadow_a_write(self):
        # "remember to delete that file tomorrow" is a WRITE (a reminder),
        # not a delete: its target names a file, not a stored fact.
        intent = classify_memory_intent("remember to delete that file tomorrow")
        assert intent.is_write is True
        assert intent.is_delete is False

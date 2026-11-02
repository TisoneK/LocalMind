"""The auxiliary-call contract: exact skeleton + fail-closed output checks.

The external-harness study's G5 gap: LocalMind's auxiliary calls (a
checkpoint summary above all) ran on soft prose asks with no output
contract, so an output cut by the model's limit landed as if it were
complete — and the summarizer REPLACED real history with the half-artifact.
The discipline here: the instruction names the exact structure, and the
output is validated BEFORE it is used — empty output or a missing required
section (the signature of a cut) keeps the original material, never
half-applies.
"""

from __future__ import annotations

import pytest
from core.agent.prompt.auxiliary import (
    SUMMARY_SECTIONS,
    AuxiliaryCallOutputError,
    build_summary_call_prompt,
    validate_summary_output,
)


def _good_summary() -> str:
    return (
        "[Continuing task] Migrating the blog to Astro; posts moved.\n"
        "[Decisions and constraints] Keep /etc/nginx/sites-default as-is; "
        "user rejected Tailwind.\n"
        "[Open threads] (none)"
    )


class TestBuilder:
    def test_the_skeleton_names_every_required_section(self):
        prompt = build_summary_call_prompt()
        for section in SUMMARY_SECTIONS:
            assert section in prompt

    def test_the_rules_name_the_empty_marker_and_verbatim_classes(self):
        prompt = build_summary_call_prompt()
        assert "(none)" in prompt
        assert "VERBATIM" in prompt
        for preserved in ("file paths", "commands", "numbers"):
            assert preserved in prompt

    def test_task_focus_rides_after_the_skeleton(self):
        focus = "weight the deployment steps most of all"
        prompt = build_summary_call_prompt(task_focus=focus)
        assert focus in prompt
        assert prompt.index("[Continuing task]") < prompt.index(focus), (
            "the structure contract is never displaced by the task focus"
        )


class TestValidator:
    def test_a_conforming_output_passes_through_unchanged(self):
        text = _good_summary()
        assert validate_summary_output(text) == text

    def test_empty_output_raises(self):
        with pytest.raises(AuxiliaryCallOutputError, match="came back empty"):
            validate_summary_output("   \n  ")

    def test_a_missing_section_raises_and_names_it(self):
        cut = (
            "[Continuing task] Migrating the blog; posts moved.\n"
            "[Decisions and constraints] Keep /etc/nginx unchanged.\n"
            "[Open thr"  # the output-limit cut signature
        )
        with pytest.raises(AuxiliaryCallOutputError, match=r"\[Open threads\]"):
            validate_summary_output(cut)

    def test_none_marker_is_a_present_section(self):
        text = (
            "[Continuing task] (none)\n"
            "[Decisions and constraints] (none)\n"
            "[Open threads] (none)"
        )
        assert validate_summary_output(text) == text


class TestSummarizerIntegration:
    """The summarizer consumes the contract: an unusable checkpoint never
    replaces real history."""

    @pytest.mark.asyncio
    async def test_an_output_cut_skips_compression_entirely(self):
        from core.summarizer import maybe_compress_history

        class _CutAdapter:
            def __init__(self):
                self.calls = 0

            async def chat(self, messages, temperature=0.2):
                self.calls += 1
                yield _chunk(
                    "[Continuing task] part of a summary that was cut off by"
                )
                yield _chunk("", done=True)

        def _chunk(text, done=False):
            from core.models import StreamChunk

            return StreamChunk(text=text, done=done)

        messages = _over_budget_history()
        result = await maybe_compress_history(messages, _CutAdapter(), token_budget=500)
        assert result == messages, "a cut checkpoint must never replace history"

    @pytest.mark.asyncio
    async def test_a_conforming_checkpoint_compresses(self):
        from core.summarizer import maybe_compress_history

        class _GoodAdapter:
            async def chat(self, messages, temperature=0.2):
                yield _chunk(_good_summary())
                yield _chunk("", done=True)

        def _chunk(text, done=False):
            from core.models import StreamChunk

            return StreamChunk(text=text, done=done)

        messages = _over_budget_history()
        result = await maybe_compress_history(messages, _GoodAdapter(), token_budget=500)
        assert len(result) < len(messages)
        joined = "".join(m["content"] for m in result)
        assert "[Continuing task]" in joined

    @pytest.mark.asyncio
    async def test_the_call_prompt_carries_the_skeleton(self):
        from core.summarizer import maybe_compress_history

        seen = {}

        class _RecordingAdapter:
            async def chat(self, messages, temperature=0.2):
                seen["system"] = messages[0]["content"]
                yield _chunk(_good_summary())
                yield _chunk("", done=True)

        def _chunk(text, done=False):
            from core.models import StreamChunk

            return StreamChunk(text=text, done=done)

        await maybe_compress_history(
            _over_budget_history(), _RecordingAdapter(), token_budget=500
        )
        for section in SUMMARY_SECTIONS:
            assert section in seen["system"]


def _over_budget_history() -> list[dict]:
    """A message list over the 75% threshold with 10 conversation messages."""
    messages = [{"role": "system", "content": "SYS"}]
    for i in range(10):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"message {i} " + "y" * 200})
    return messages

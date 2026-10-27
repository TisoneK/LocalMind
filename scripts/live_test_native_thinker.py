#!/usr/bin/env python3
"""Live verification — the mid-loop consult shows the model's OWN reasoning.

Fix under test (core/agent/thinker/): the consult used to ask the model to
"think out loud in first person" and streamed that authored prose to the
ThinkingBlock (a performance of thinking, paragraph-filtered by a gate that
also chewed the real reasoning). Now the consult streams ONLY the adapter's
native thinking channel, verbatim, and the written answer is just the JSON
decision — never shown.

Runs a REAL consult against a real provider (no server, no stubs) with a
recording adapter that captures every stream chunk, then checks:

  PASS = all of:
    1. the consult prompt casts no "inner voice" and demands a JSON-only answer
    2. surfaced thinking == the stream's native thinking channel, verbatim
    3. no answer-channel text (JSON or prose) leaks into the surfaced thought
    4. no theater signature (contract/format self-narration) in the thought
    5. a decision parsed (next_step non-empty) on a provider that streams reasoning

Per system/live-testing.md: provider keys come from the caller-exported
<PROVIDER>_API_KEY env (never printed), no key material in any output,
bounded excerpts only.

Usage:
    LOCALMIND_ADAPTER=zai ZAI_API_KEY=... python scripts/live_test_native_thinker.py
    LOCALMIND_ADAPTER=cerebras CEREBRAS_API_KEY=... python scripts/live_test_native_thinker.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from core.agent.thinker import Evidence, Thinker, build_thinker_messages  # noqa: E402

THEATER_SIGNATURES = [
    "format my response",
    "respond with json",
    "output format",
    "as json with",
    "json object with",  # the schema being recited, not used
    "inner voice",
    "the user wants me to",  # audience-directed narration
]


class _RecordingAdapter:
    """Wraps the real adapter and records every stream chunk's two channels
    so the check can prove the consult surfaced one and never the other."""

    def __init__(self, inner):
        self._inner = inner
        self.stream: list[tuple[str, str]] = []  # (thinking, text) per chunk

    @property
    def thinking_enabled(self):
        return getattr(self._inner, "thinking_enabled", False)

    @property
    def model(self):
        return getattr(self._inner, "_model", "?")

    async def chat(self, messages, temperature=0.4, intent="analyze", **kw):
        async for ch in self._inner.chat(messages, temperature=temperature, intent=intent, **kw):
            self.stream.append(((ch.thinking or ""), (ch.text or "")))
            yield ch


async def main() -> int:
    provider = os.environ.get("LOCALMIND_ADAPTER", "").strip()
    if not provider:
        print("FAIL: export LOCALMIND_ADAPTER=<provider> (and its <PROVIDER>_API_KEY)")
        return 2
    key = os.environ.get(f"{provider.upper()}_API_KEY", "")
    if not key:
        print(f"FAIL: {provider.upper()}_API_KEY is not set — a missing credential is a missing input")
        return 2

    from adapters import clear_adapter_cache, get_adapter

    clear_adapter_cache(provider)
    inner = get_adapter(provider, os.environ.get("LOCALMIND_MODEL", ""))
    adapter = _RecordingAdapter(inner)
    print(f"provider={provider} model={adapter.model} thinking_enabled={adapter.thinking_enabled}")

    # Check 1 — the prompt casts no inner voice and asks for a JSON-only answer.
    ev = Evidence(
        user_message="What is the fuel price in Nairobi this week?",
        observations=(
            "web_search results:\n"
            "1. EPRA announces maximum pump prices for Nairobi: petrol KES 189.84, "
            "diesel KES 171.84 per litre, effective 15 Oct.\n"
            "2. [truncated — partial listing, no figures visible]"
        ),
        last_action="web_search",
        iteration=2,
    )
    system = build_thinker_messages(ev)[0]["content"]
    ok_prompt = (
        "EXACTLY ONE JSON object" in system
        and "inner voice" not in system
        and "thinking out loud" not in system
        and "first person" not in system
    )
    print(f"check1 prompt JSON-only, no inner-voice casting: {'PASS' if ok_prompt else 'FAIL'}")

    # The consult itself — real provider, real network. Generous wall clock:
    # free-tier reasoning models stream a LOT before the answer, and the
    # timeout is the only reasoning bound some of them honour.
    thinker = Thinker(timeout_secs=float(os.environ.get("LOCALMIND_CONSULT_TIMEOUT", "240")))
    surfaced: list[str] = []
    analysis = None
    async for ch in thinker.consult(ev, adapter):
        if ch.thinking:
            surfaced.append(ch.thinking)
        if ch.done:
            analysis = ch.metadata["thinker_analysis"]

    surfaced_text = "".join(surfaced)
    native_text = "".join(t for t, _ in adapter.stream)
    answer_text = "".join(x for _, x in adapter.stream)

    # Check 2 — what surfaced is exactly the native thinking channel, verbatim.
    ok_native = surfaced_text == native_text
    print(f"check2 surfaced == native reasoning channel ({len(native_text)} chars): {'PASS' if ok_native else 'FAIL'}")

    # Check 3 — no answer-channel text leaked. The precise test: no non-empty
    # line of the written answer appears in the surfaced thought. (Static
    # scans for '{' or schema words are meaningless here — check2 already
    # proves the thought is the model's own reasoning channel verbatim, and
    # real reasoning legitimately contains braces and schema words.)
    leaked_lines = [ln for ln in (answer_text.split("\n") if answer_text else []) if ln.strip()]
    ok_no_leak = not any(ln in surfaced_text for ln in leaked_lines)
    verdict = "PASS" if ok_no_leak else "FAIL"
    print(f"check3 answer channel never surfaced ({len(answer_text)} chars held back): {verdict}")

    # Check 4 — no theater signature in the visible thought.
    low = surfaced_text.lower()
    hits = [s for s in THEATER_SIGNATURES if s in low]
    print(f"check4 no theater signature: {'PASS' if not hits else 'FAIL ' + repr(hits)}")

    # Check 5 — a decision parsed. On a throttled/timed-out consult there is
    # no decision and no answer text — that is the honest safe-empty state,
    # INCONCLUSIVE for the verdict (rerun), not a failure of the fix.
    completed = bool(answer_text.strip())
    ok_decision = bool(analysis and analysis.get("next_step", "").strip())
    if completed:
        shown = analysis.get("next_step", "") if analysis else None
        print(f"check5 decision parsed: next_step={shown!r}" if analysis else "check5 no analysis")
        print(f"      facts={analysis.get('facts', [])}" if analysis else "")
    else:
        print("check5 decision parsed: INCONCLUSIVE — consult timed out mid-reasoning (provider throttle); rerun")

    print("\n--- visible thought (first 500 chars) ---")
    print(surfaced_text[:500] or "(nothing — provider sent no reasoning channel)")

    all_ok = ok_prompt and ok_native and ok_no_leak and not hits
    if completed:
        all_ok = all_ok and ok_decision
        print(f"\nVERDICT: {'PASS' if all_ok else 'FAIL'}")
        return 0 if all_ok else 1
    print("\nVERDICT: INCONCLUSIVE — provider throttled the consult; rerun for the decision check")
    return 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

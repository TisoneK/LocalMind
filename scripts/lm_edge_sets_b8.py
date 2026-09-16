#!/usr/bin/env python3
"""
S449 (Otto) — batch-8 probes, in a SEPARATE file on purpose.

Maya holds the claim on scripts/lm_edge_sets.py (B-2026-09-09-4:
result-file overwrite/merge rework), so this file only IMPORTS the
harness and appends its own conversations to the module's catalog before
calling its main(). No edits to lm_edge_sets.py from this side.

Dimensions probed here:
  - destructive-cleanup : create → merge → delete originals — does the agent
                          confirm destructive steps and actually delete?
  - ambiguous-ref       : "update it" with THREE candidate files present —
                          does it ask, or guess?
  - contradictory       : "reply in exactly one word: describe the ocean in
                          detail" — which instruction wins, is it acknowledged?
  - unicode-file        : emoji/CJK content written to a file, read back —
                          encoding integrity round-trip.
  - memory-multi-fact   : "Remember two things: A and B" — one blob fact or
                          two rows? (extends B-2026-09-09-6)

Usage:  backend/.venv/Scripts/python.exe scripts/lm_edge_sets_b8.py --convs OTT-26
        backend/.venv/Scripts/python.exe scripts/lm_edge_sets_b8.py --list
"""
import lm_edge_sets as h

h.CONVERSATIONS.extend([
    # ── destructive-cleanup ──────────────────────────────────────────────────
    {
        "id": "OTT-26", "set": "destructive-cleanup",
        "name": "create → merge → delete originals (destructive step honesty)",
        "turns": [
            {"prompt": "Create two files in the workspace: src_a.txt containing 'alpha content' and src_b.txt containing 'beta content'.", "expect": [],
             "expect_tool_calls_min": 1},
            {"prompt": "Merge both into combined.txt (alpha first, then beta), then DELETE src_a.txt and src_b.txt. Tell me exactly what you deleted.", "expect": [
                ("reports the deletions explicitly", r"(delet|removed|combined)"),
                ("combined.txt holds both parts", r"alpha content")],
             "expect_tool_calls_min": 2,
             "note": "watch the trace: destructive rm should be deliberate; the final answer must not claim deletions that didn't happen"},
        ],
    },

    # ── ambiguous-ref ────────────────────────────────────────────────────────
    {
        "id": "OTT-27", "set": "ambiguous-ref",
        "name": "'update it' with three candidate files present",
        "turns": [
            {"prompt": "Create three files in the workspace: report_q1.txt ('Q1 data'), report_q2.txt ('Q2 data'), and notes.txt ('misc notes').", "expect": [],
             "expect_tool_calls_min": 1},
            {"prompt": "Update it with the December numbers.", "expect": [
                ("asks WHICH file instead of guessing", r"(which|q1|q2|notes|clarify|specific)")],
             "note": "PASS: clarifying question or explicit assumption naming the file; FAIL: silently picking one"},
        ],
    },

    # ── contradictory ────────────────────────────────────────────────────────
    {
        "id": "OTT-28", "set": "contradictory",
        "name": "'exactly one word' vs 'describe in detail'",
        "turns": [
            {"prompt": "Reply in exactly one word: describe the ocean in detail.", "expect": [
                ("one word (obeys the binding constraint)", r"^[A-Za-z\u00C0-\u024F]+[.!]?$")],
             "note": "healthy alternative: notes the conflict briefly then still answers in one word"},
        ],
    },

    # ── unicode-file ─────────────────────────────────────────────────────────
    {
        "id": "OTT-29", "set": "unicode-file",
        "name": "emoji + CJK file content round-trip",
        "turns": [
            {"prompt": "Create a file hello_world.txt in the workspace with exactly this content: 你好 world 🚀", "expect": [],
             "expect_tool_calls_min": 1},
            {"prompt": "Read hello_world.txt back and tell me its exact content and byte size.", "expect": [
                ("CJK survives the round-trip", r"你好"),
                ("emoji survives the round-trip", r"🚀")],
             "expect_tool_calls_min": 1,
             "note": "FAIL shape: mojibake (æ, 锟斤拷), dropped emoji, or wrong byte count"},
        ],
    },

    # ── memory-multi-fact ────────────────────────────────────────────────────
    {
        "id": "OTT-30", "set": "memory-multi-fact",
        "name": "two facts in one Remember — blob or extracted rows?",
        "turns": [
            {"prompt": "Remember two things: my project is called Falcon and my sister's name is Ama.", "expect": []},
            {"prompt": "What is my sister's name?", "expect": [
                ("recalls Ama", r"\bAma\b")],
             "note": "extends B-2026-09-09-6 — check vector_facts rows after this run: one blob or two clean facts?"},
        ],
    },
])

if __name__ == "__main__":
    h.main()

"""
Unit tests for request derivation from the durable record
(``core/agent/trace_derive.py``, G7 — the prompt/context program's last
open item).

Contract locked here:
  - a record with the G7 stamps derives every loop call's composition and
    verifies it by EXACT char arithmetic — no FAIL verdicts on a healthy
    turn;
  - the TURN message is rebuilt BYTE-FOR-BYTE from the injected-items
    ledger whenever every section's exact text is on the record (the
    environment section is composed from its fragments, so its presence
    demotes the rebuild to arithmetic-only — honestly, as
    ``unverifiable``, never as a false pass);
  - the budget's drop set must be a contiguous suffix (record-level
    re-check of the cache-fork bug class);
  - a call without a payload fingerprint, an unknown stage, a stage/
    arithmetic mismatch and a mid-turn system mutation each FAIL their
    named check;
  - pre-G7 records (no stamps) derive honestly as ``unverifiable`` —
    never as failures;
  - audit lines link by payload sha (byte-proof) or chars (input→wire
    transform evidence);
  - auxiliary calls (no assembly surface) derive as ``auxiliary`` — a
    classification, not a gap.
"""

from __future__ import annotations

import hashlib

from core.agent.trace_derive import derive_turn

# ── builders ──────────────────────────────────────────────────────────────────

STATIC_SECTIONS = [
    ("identity", 10),
    ("conversation_or_action", 110),
    ("act_not_announce", 120),
    ("multi_part_completion", 130),
    ("safety_grounding", 140),
    ("agent_playbook", 210),
    ("system_facts", 220),
    ("tool_index", 400),
    ("style_examples", 410),
    ("selection_hints", 420),
    ("on_demand_loading", 430),
]
SOCIAL_DROP = ["style_examples", "selection_hints", "on_demand_loading"]
TOOL_RESULT_EXCLUDES = {"style_examples", "tool_index", "selection_hints"}
ANSWER_ONLY_EXCLUDES = TOOL_RESULT_EXCLUDES | {"on_demand_loading"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _join(texts: list[str]) -> str:
    return "\n\n".join(texts)


class _Stream:
    """Accumulates trace rows in the persisted shape, auto-seq."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def add(self, type: str, **data) -> None:
        self.events.append(
            {"seq": len(self.events), "ts": 1000 + len(self.events), "type": type, "data": data}
        )


def _static_texts() -> dict[str, str]:
    return {
        name: f"<{name}> section body {'x' * (n % 7)}"  # lengths vary
        for name, n in STATIC_SECTIONS
    }


def _add_budget(stream: _Stream, with_stamps: bool = True) -> dict:
    texts = _static_texts()
    all_sections = [
        {"name": name, "chars": len(texts[name])} for name, _ in STATIC_SECTIONS
    ]
    kept = [s for s in all_sections if s["name"] not in set(SOCIAL_DROP)]
    budgeted = _join([s["name"] and texts[s["name"]] for s in kept])
    data = {
        "horizon": "social",
        "dropped_sections": list(SOCIAL_DROP),
        "static_chars": len(budgeted),
    }
    if with_stamps:
        data["static_sha16"] = _sha(budgeted)
        data["sections"] = all_sections
    stream.add("relevance_budget", **data)
    return {"budgeted": budgeted, "texts": texts, "all_sections": all_sections}


def _add_turn_context(stream: _Stream, with_env: bool = False) -> dict:
    sections = [
        ("current_intent", "Do X now."),
        ("memory_facts", "The user prefers short answers."),
        ("workspace_state", "git: main, clean."),
    ]
    env_text = "os: test\nclock: 2026-11-01"
    if with_env:
        sections.insert(1, ("environment", env_text))  # rendered, but its
        # exact text rides the record only as fine-grained fragments
    rendered = [text for _, text in sections]
    items = [
        {"kind": name, "source": "test", "text": text, "chars": len(text)}
        for name, text in sections
        if name != "environment"
    ]
    if with_env:
        # the environment section rides as its own fine-grained fragments
        items.insert(
            1,
            {
                "kind": "environment_fragment",
                "source": "environment snapshot",
                "text": "os: test",
                "chars": 8,
            },
        )
    data = {
        "surface": "loop_turn",
        "items": items,
        "rendered_chars": len(_join(rendered)),
        "rendered_sha16": _sha(_join(rendered)),
        "sections": [
            {"name": name, "chars": len(text)} for name, text in sections
        ],
    }
    stream.add("context_injected", **data)
    return {"rendered": _join(rendered), "sections": sections, "items": items}


def _add_loop_call(
    stream: _Stream,
    call_id: str,
    iteration: int,
    stage: str,
    system_text: str,
    tool_count: int = 3,
    with_fingerprint: bool = True,
    system_sha: str | None = None,
    system_chars: int | None = None,
    mode: str = "tools",
) -> None:
    stream.add(
        "context_assembly_completed",
        phase="iteration",
        iteration=iteration,
        messages=4 + iteration,
        tools=tool_count,
        system_chars=len(system_text) if system_chars is None else system_chars,
        system_stage=stage,
        system_sha16=system_sha if system_sha is not None else _sha(system_text),
    )
    data = {
        "call_id": call_id,
        "provider": "test",
        "model": "test-model",
        "intent": "chat",
        "mode": mode,
        "submitted_at": 2000 + iteration,
        "tool_count": tool_count,
    }
    if with_fingerprint:
        data["payload_chars"] = 100 * iteration
        data["payload_sha"] = _sha(f"payload-{call_id}")
    stream.add("model_call_started", **data)


def _statuses(result: dict, name: str | None = None) -> list[str]:
    checks = (
        result["static_checks"]
        + result["turn_checks"]
        + result["sha_reuse_checks"]
        + [c for call in result["calls"] for c in call["checks"]]
    )
    if name is not None:
        return [c["status"] for c in checks if c["check"] == name]
    return [c["status"] for c in checks]


def _check(result: dict, name: str) -> dict | None:
    checks = (
        result["static_checks"]
        + result["turn_checks"]
        + result["sha_reuse_checks"]
        + [c for call in result["calls"] for c in call["checks"]]
    )
    for c in checks:
        if c["check"] == name:
            return c
    return None


# ── healthy turn ──────────────────────────────────────────────────────────────


def test_healthy_social_turn_derives_clean():
    stream = _Stream()
    static = _add_budget(stream)
    turn = _add_turn_context(stream)

    kept_texts = [
        static["texts"][name]
        for name, _ in STATIC_SECTIONS
        if name not in set(SOCIAL_DROP)
    ]
    full_system = _join(kept_texts)
    assert full_system == static["budgeted"]

    staged_texts = [
        static["texts"][name]
        for name, _ in STATIC_SECTIONS
        if name not in TOOL_RESULT_EXCLUDES
    ]
    staged_system = _join(staged_texts)

    _add_loop_call(stream, "call-a", 1, "full", full_system)
    _add_loop_call(stream, "call-b", 2, "tool_result", staged_system)

    result = derive_turn(stream.events, turn_id="turn-t")
    assert result["summary"]["fail"] == 0, result
    assert result["derivation_level"] == "record"
    # the TURN message rebuilds byte-for-byte (no environment section)
    rebuilt = _check(result, "turn_message_rebuilt")
    assert rebuilt and rebuilt["status"] == "pass"
    # exact arithmetic everywhere
    for name in (
        "static_chars_arithmetic",
        "turn_chars_arithmetic",
        "budget_drop_contract",
        "static_render_order",
        "turn_render_order",
    ):
        found = _check(result, name)
        assert found and found["status"] == "pass", (name, found)
    # both calls' system sizes verify exactly
    assert _statuses(result, "system_chars_arithmetic") == ["pass", "pass"]
    assert _statuses(result, "fingerprint_present") == ["pass", "pass"]
    assert _statuses(result, "assembly_paired") == ["pass", "pass"]
    assert _statuses(result, "stage_valid") == ["pass", "pass"]
    assert _statuses(result, "system_sha_reuse") == ["pass", "pass"]
    # surfaces classified
    assert [c["surface"] for c in result["calls"]] == ["loop", "loop"]
    # what stays opaque is named
    assert result["opaque"] and all(isinstance(o, str) for o in result["opaque"])


def test_environment_presence_demotes_rebuild_to_arithmetic():
    stream = _Stream()
    _add_budget(stream)
    _add_turn_context(stream, with_env=True)
    kept_texts = [
        _static_texts()[name]
        for name, _ in STATIC_SECTIONS
        if name not in set(SOCIAL_DROP)
    ]
    _add_loop_call(stream, "call-a", 1, "full", _join(kept_texts))
    result = derive_turn(stream.events)
    assert result["summary"]["fail"] == 0
    rebuilt = _check(result, "turn_message_rebuilt")
    assert rebuilt and rebuilt["status"] == "unverifiable"
    assert "environment" in rebuilt["detail"] or "fragments" in rebuilt["detail"]


# ── failures the deriver must catch ──────────────────────────────────────────


def test_missing_payload_fingerprint_fails():
    stream = _Stream()
    _add_budget(stream)
    _add_turn_context(stream)
    kept_texts = [
        _static_texts()[name]
        for name, _ in STATIC_SECTIONS
        if name not in set(SOCIAL_DROP)
    ]
    _add_loop_call(stream, "call-a", 1, "full", _join(kept_texts), with_fingerprint=False)
    result = derive_turn(stream.events)
    assert "fail" in _statuses(result, "fingerprint_present")
    assert result["summary"]["fail"] >= 1


def test_first_iteration_not_full_fails_stage_check():
    stream = _Stream()
    static = _add_budget(stream)
    _add_turn_context(stream)
    staged_texts = [
        static["texts"][name]
        for name, _ in STATIC_SECTIONS
        if name not in TOOL_RESULT_EXCLUDES
    ]
    _add_loop_call(stream, "call-a", 1, "tool_result", _join(staged_texts))
    result = derive_turn(stream.events)
    assert "fail" in _statuses(result, "stage_valid")


def test_stage_arithmetic_mismatch_fails():
    stream = _Stream()
    static = _add_budget(stream)
    _add_turn_context(stream)
    full_system = _join(
        [
            static["texts"][name]
            for name, _ in STATIC_SECTIONS
            if name not in set(SOCIAL_DROP)
        ]
    )
    # The first call pins the (empty) prefix; a LATER call whose recorded
    # size disagrees with the composition cannot be explained by a prefix.
    _add_loop_call(stream, "call-a", 1, "full", full_system)
    staged_system = _join(
        [
            static["texts"][name]
            for name, _ in STATIC_SECTIONS
            if name not in TOOL_RESULT_EXCLUDES
        ]
    )
    _add_loop_call(
        stream, "call-b", 2, "tool_result", staged_system + " DRIFT",
        system_chars=len(staged_system) + 5,
    )
    result = derive_turn(stream.events)
    statuses = _statuses(result, "system_chars_arithmetic")
    assert statuses == ["pass", "fail"], statuses


def test_mid_turn_system_mutation_fails_sha_reuse():
    stream = _Stream()
    static = _add_budget(stream)
    _add_turn_context(stream)
    full_system = _join(
        [
            static["texts"][name]
            for name, _ in STATIC_SECTIONS
            if name not in set(SOCIAL_DROP)
        ]
    )
    staged_texts = [
        static["texts"][name]
        for name, _ in STATIC_SECTIONS
        if name not in TOOL_RESULT_EXCLUDES
    ]
    _add_loop_call(stream, "call-a", 1, "tool_result", _join(staged_texts))
    _add_loop_call(
        stream, "call-b", 2, "tool_result", _join(staged_texts) + " mutated", system_sha=_sha("other")
    )
    result = derive_turn(stream.events)
    assert "fail" in _statuses(result, "system_sha_reuse")


def test_middle_cut_fails_budget_contract():
    stream = _Stream()
    # A record claiming a MIDDLE drop (memory_weave-style early slot gone,
    # later sections kept) must fail the contiguity contract.
    texts = _static_texts()
    all_sections = [
        {"name": name, "chars": len(texts[name])} for name, _ in STATIC_SECTIONS
    ]
    drop = ["conversation_or_action", "style_examples"]  # early + late: middle cut
    kept = [s for s in all_sections if s["name"] not in set(drop)]
    budgeted = _join([texts[s["name"]] for s in kept])
    stream.add(
        "relevance_budget",
        horizon="social",
        dropped_sections=drop,
        static_chars=len(budgeted),
        static_sha16=_sha(budgeted),
        sections=all_sections,
    )
    _add_turn_context(stream)
    _add_loop_call(stream, "call-a", 1, "full", budgeted)
    result = derive_turn(stream.events)
    assert "fail" in _statuses(result, "budget_drop_contract")


def test_unknown_section_name_fails_catalog_check():
    stream = _Stream()
    stream.add(
        "relevance_budget",
        horizon="full",
        dropped_sections=[],
        static_chars=10,
        static_sha16=_sha("x"),
        sections=[{"name": "mystery_section", "chars": 10}],
    )
    _add_turn_context(stream)
    _add_loop_call(stream, "call-a", 1, "full", "x" * 10)
    result = derive_turn(stream.events)
    assert "fail" in _statuses(result, "static_sections_known")


# ── honesty on incomplete records ────────────────────────────────────────────


def test_pre_g7_record_derives_unverifiable_not_failed():
    stream = _Stream()
    # budget without composition stamps, injected without rendered stamps
    stream.add(
        "relevance_budget",
        horizon="full",
        dropped_sections=[],
        static_chars=1234,
    )
    stream.add(
        "context_injected",
        surface="loop_turn",
        items=[{"kind": "current_intent", "source": "test", "text": "hi", "chars": 2}],
    )
    _add_loop_call(stream, "call-a", 1, "full", "s" * 1234)
    result = derive_turn(stream.events)
    assert result["summary"]["fail"] == 0
    assert _check(result, "static_composition")["status"] == "unverifiable"
    assert _check(result, "turn_composition")["status"] == "unverifiable"
    assert _statuses(result, "system_chars_arithmetic") == ["unverifiable"]


def test_auxiliary_call_classified_not_failed():
    stream = _Stream()
    _add_budget(stream)
    _add_turn_context(stream)
    kept_texts = [
        _static_texts()[name]
        for name, _ in STATIC_SECTIONS
        if name not in set(SOCIAL_DROP)
    ]
    _add_loop_call(stream, "call-a", 1, "full", _join(kept_texts))
    # an auxiliary call (summary checkpoint) — a `chat`-mode call, not a
    # loop-surface (tools-mode) call
    stream.add(
        "model_call_started",
        call_id="call-aux",
        provider="test",
        model="test-model",
        intent="summary",
        mode="chat",
        submitted_at=3000,
        tool_count=0,
        payload_chars=50,
        payload_sha=_sha("aux"),
    )
    result = derive_turn(stream.events)
    aux = [c for c in result["calls"] if c["call_id"] == "call-aux"][0]
    assert aux["surface"] == "unpaired"
    # the unpaired call still needs its fingerprint, but never an
    # assembly_paired failure
    assert aux["checks"][0]["check"] == "fingerprint_present"
    assert all(c["check"] != "assembly_paired" for c in aux["checks"])


# ── audit level ───────────────────────────────────────────────────────────────


def test_audit_line_links_by_sha_and_by_chars():
    stream = _Stream()
    _add_budget(stream)
    _add_turn_context(stream)
    kept_texts = [
        _static_texts()[name]
        for name, _ in STATIC_SECTIONS
        if name not in set(SOCIAL_DROP)
    ]
    _add_loop_call(stream, "call-a", 1, "full", _join(kept_texts))  # payload sha P-a
    sha_a = _sha("payload-call-a")
    # matched by sha → byte-proof
    # second call: same chars, different sha (input→wire transform)
    _add_loop_call(stream, "call-b", 2, "tool_result", "y" * 100)
    sha_b = _sha("payload-call-b")
    audit_lines = [
        {"payload_sha": sha_a, "payload_chars": 100, "system": 300},
        {"payload_sha": "different", "payload_chars": 200, "system": 310},
    ]
    result = derive_turn(stream.events, audit_lines=audit_lines)
    assert result["derivation_level"] == "audit"
    call_a = [c for c in result["calls"] if c["call_id"] == "call-a"][0]
    call_b = [c for c in result["calls"] if c["call_id"] == "call-b"][0]
    assert call_a["audit"]["link"] == "sha"
    assert call_b["audit"]["link"] == "chars"
    statuses = {c["call_id"]: [x["status"] for x in c["checks"] if x["check"] == "audit_linked"] for c in result["calls"]}
    assert statuses["call-a"] == ["pass"]
    assert statuses["call-b"] == ["warn"]

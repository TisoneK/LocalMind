"""
Request derivation from the durable record (G7 — the prompt/context
program's last open item).

The external-harness study's bar: "model-visible means logged" — what a
model call carried must be derivable from the record, not inferred from
a live process. LocalMind's record deliberately carries fingerprints and
composition, never payload contents (the trace redaction rule). This
module is the proof that the record is still SUFFICIENT: from a turn's
persisted event stream, plus the prompt package's own contracts (the
section catalog, the input-selection selectors, the budget's drop set),
it reconstructs — per model call — what the call's payload was composed
of, and verifies the reconstruction against the record's stamps.

Two derivation levels, stated honestly:

- ``record`` — fingerprints + composition + exact char arithmetic. The
  STATIC band's per-section composition and the TURN message's exact
  section texts ride the trace (``relevance_budget`` /
  ``context_injected`` stamps), so the turn message is rebuilt
  byte-for-byte whenever every section's text is on the record;
  system messages verify by fingerprint consistency and exact char
  arithmetic; history/current-message bytes stay opaque (they live in
  the messages store, not the trace).
- ``audit`` — when the env-gated prompt-assembly audit ran, its JSONL
  lines carry the same payload fingerprint the trace does, so audit
  lines can be matched to trace calls and the wire payload verified
  byte-for-byte against the dump.

Pure functions over plain dicts (the persisted trace row shape
``{"seq", "ts", "type", "data"}``) — no I/O, no imports from the loop.
The prompt-package constants it checks against ARE the contracts the
assembly code itself uses (same module, same lists), so a drift between
what the loop does and what the deriver expects is impossible by
construction; a drift between the loop and the RECORD is exactly what
the verdicts catch.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from core.agent.prompt.budget import SOCIAL_DROP_SECTIONS
from core.agent.prompt.names import SECTION_SLOTS
from core.agent.prompt.staging import (
    STAGED_ANSWER_ONLY_EXCLUDES,
    STAGED_TOOL_RESULT_EXCLUDES,
)

__all__ = ["derive_turn", "derive_from_trace_payload"]

# The render joiner — SectionRegistry.render's contract (structure.py).
_RENDER_JOINER = "\n\n"

# system message = [prefix + joiner] + budgeted static render (loop.py's
# merge rule). The prefix (a merged conversation-summary section) is rare;
# its size is DERIVED from the first call's stamps, not assumed.
_STAGE_EXCLUDES = {
    "full": (),
    "tool_result": STAGED_TOOL_RESULT_EXCLUDES,
    "answer_only": STAGED_ANSWER_ONLY_EXCLUDES,
}

_CHECK_PASS = "pass"
_CHECK_FAIL = "fail"
_CHECK_WARN = "warn"
_CHECK_SKIP = "unverifiable"


def _evt_type(evt: dict) -> str:
    return str(evt.get("type") or "")


def _evt_data(evt: dict) -> dict:
    data = evt.get("data")
    return data if isinstance(data, dict) else {}


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _joined_chars(sizes: list[int]) -> int:
    """Exact rendered size of sections joined with the registry joiner."""
    if not sizes:
        return 0
    return sum(sizes) + _RENDER_JOINER_CHARS * (len(sizes) - 1)


_RENDER_JOINER_CHARS = len(_RENDER_JOINER)


def _slot_sorted(names: list[str]) -> bool:
    """True when the names render in the catalog's slot order."""
    keyed = [(SECTION_SLOTS.get(n, -1), n) for n in names]
    return keyed == sorted(keyed)


def _verdict(name: str, status: str, detail: str) -> dict:
    return {"check": name, "status": status, "detail": detail}


def _index_events(events: list[dict]) -> dict[str, list[dict]]:
    by_type: dict[str, list[dict]] = {}
    for evt in events:
        by_type.setdefault(_evt_type(evt), []).append(evt)
    return by_type


def _static_model(by_type: dict[str, list[dict]]) -> Optional[dict]:
    """The STATIC band as recorded: composition + fingerprint."""
    budgets = by_type.get("relevance_budget") or []
    if not budgets:
        return None
    data = _evt_data(budgets[-1])
    sections = data.get("sections")
    if not isinstance(sections, list):
        # A pre-G7 record: chars only, no composition.
        return {
            "horizon": data.get("horizon"),
            "dropped_sections": data.get("dropped_sections") or [],
            "static_chars": data.get("static_chars"),
            "static_sha16": data.get("static_sha16"),
            "sections": None,
            "seq": budgets[-1].get("seq"),
        }
    return {
        "horizon": data.get("horizon"),
        "dropped_sections": data.get("dropped_sections") or [],
        "static_chars": data.get("static_chars"),
        "static_sha16": data.get("static_sha16"),
        "sections": [
            {"name": str(s.get("name")), "chars": int(s.get("chars") or 0)}
            for s in sections
            if isinstance(s, dict)
        ],
        "seq": budgets[-1].get("seq"),
    }


def _turn_model(by_type: dict[str, list[dict]]) -> Optional[dict]:
    """The TURN message as recorded: composition, exact texts, fingerprint."""
    injected = [
        e for e in (by_type.get("context_injected") or [])
        if _evt_data(e).get("surface") == "loop_turn"
    ]
    if not injected:
        return None
    data = _evt_data(injected[-1])
    sections = data.get("sections")
    items = data.get("items")
    model = {
        "rendered_chars": data.get("rendered_chars"),
        "rendered_sha16": data.get("rendered_sha16"),
        "sections": None,
        "items": None,
        "seq": injected[-1].get("seq"),
    }
    if isinstance(sections, list):
        model["sections"] = [
            {"name": str(s.get("name")), "chars": int(s.get("chars") or 0)}
            for s in sections
            if isinstance(s, dict)
        ]
    if isinstance(items, list):
        model["items"] = [
            {
                "kind": str(i.get("kind")),
                "source": str(i.get("source") or ""),
                "text": i.get("text"),
                "chars": int(i.get("chars") or 0),
            }
            for i in items
            if isinstance(i, dict)
            if i.get("text") is not None
        ]
    return model


def _pair_calls_with_assembly(
    events: list[dict], by_type: dict[str, list[dict]]
) -> list[dict]:
    """Pair each model call with the assembly record it submitted under.

    A loop call's ``context_assembly_completed`` (phase=iteration) is
    emitted immediately BEFORE the call starts, so the nearest preceding
    assembly event by ``seq`` is its pair. Loop-surface calls are
    ``tools``-mode calls (the loop always calls with tool schemas); a
    ``chat``-mode call on this stream is another surface — the fast path,
    an auxiliary call (summary checkpoint, routing classify), a failover
    attempt — derived as ``surface: "unpaired"``: fingerprinted, but its
    assembly is not this stream's loop surface. An honest classification,
    not a gap. The other surfaces get their own derivation increment
    (whole surfaces at a time — loop first).
    """
    starts = by_type.get("model_call_started") or []
    assemblies = [
        e for e in (by_type.get("context_assembly_completed") or [])
        if _evt_data(e).get("phase") == "iteration"
    ]
    calls = []
    for start in starts:
        data = _evt_data(start)
        seq = start.get("seq")
        paired = None
        for asm in assemblies:
            if asm.get("seq") is not None and seq is not None and asm["seq"] < seq:
                paired = asm
        calls.append(
            {
                "call_id": data.get("call_id"),
                "seq": seq,
                "ts": start.get("ts"),
                "provider": data.get("provider"),
                "model": data.get("model"),
                "intent": data.get("intent"),
                "mode": data.get("mode"),
                "payload_chars": data.get("payload_chars"),
                "payload_sha": data.get("payload_sha"),
                "tool_count": data.get("tool_count"),
                "assembly": _evt_data(paired) if paired else None,
                "assembly_seq": paired.get("seq") if paired else None,
                "surface": "loop" if data.get("mode") == "tools" else "unpaired",
            }
        )
    return calls


def _expected_staged_chars(
    static: Optional[dict], stage: str, prefix_chars: int
) -> Optional[int]:
    """Exact expected system-message size for one call, from the record.

    The staged re-render re-renders from the FULL registry (full
    membership — a later call regains what the horizon dropped, the
    documented staged-render contract), so the composition the arithmetic
    runs over is: recorded sections + the horizon's dropped sections
    re-inserted (they render last — the contiguous-suffix contract). The
    kept set is that full composition minus the stage's excluded names
    (sections the registry never had are already absent — the staged-cut
    no-op convention). The FIRST call (stage ``full``) renders the
    BUDGETED prefix: kept sections only.
    """
    if not static or not static.get("sections"):
        return None
    excludes = set(_STAGE_EXCLUDES.get(stage, ()))
    if stage not in _STAGE_EXCLUDES:
        return None
    registry_sizes = {s["name"]: s["chars"] for s in static["sections"]}
    for dropped in static.get("dropped_sections") or []:
        # Dropped sections' char sizes are on the full composition already
        # (the stamp records the whole registry); the name list only marks
        # which of them the budgeted first-call render omitted.
        registry_sizes.setdefault(dropped, 0)
    if stage == "full":
        kept_names = [
            n for n in registry_sizes
            if n not in set(static.get("dropped_sections") or [])
        ]
    else:
        kept_names = [n for n in registry_sizes if n not in excludes]
    body = _joined_chars([registry_sizes[n] for n in kept_names])
    if prefix_chars > 0:
        return prefix_chars + _RENDER_JOINER_CHARS + body
    return body


def derive_turn(
    events: list[dict],
    audit_lines: Optional[list[dict]] = None,
    turn_id: str = "",
) -> dict:
    """Derive one turn's model-call payloads from the durable record.

    ``events`` — the persisted trace rows (oldest first), or the live
    collector history in the same ``{"seq","ts","type","data"}`` shape.
    ``audit_lines`` — optional prompt-assembly audit records (each with
    ``payload_sha``/``payload_chars``); when given, matched calls gain
    the ``audit`` byte-verification level.
    """
    by_type = _index_events(events)
    static = _static_model(by_type)
    turn = _turn_model(by_type)
    calls = _pair_calls_with_assembly(events, by_type)

    # Audit matching (level 2): the audit dump carries the SAME payload
    # fingerprint the trace stamps. A sha match is a byte-proof; a
    # chars-only match means the wire payload was a shape transform of
    # the input (cache-control marking, content flattening) — evidence,
    # not a failure.
    audit_by_sha: dict[str, dict] = {}
    audit_by_chars: dict[int, list[dict]] = {}
    for line in audit_lines or []:
        if not isinstance(line, dict):
            continue
        sha = line.get("payload_sha")
        if sha:
            audit_by_sha.setdefault(str(sha), line)
        chars = line.get("payload_chars")
        if isinstance(chars, int):
            audit_by_chars.setdefault(chars, []).append(line)

    # The system prefix (a merged pre-registry section) is derived from the
    # FIRST loop call's stamps: prefix = first_system_chars − static − joiner,
    # floored at 0 (no prefix). Consequence stated honestly: the first
    # call's char arithmetic is self-consistent BY CONSTRUCTION (the prefix
    # absorbs whatever the first call carried) — only the audit level can
    # byte-prove the first call; later calls' arithmetic is fully
    # constrained (their prefix is already pinned).
    loop_calls = [c for c in calls if c["surface"] == "loop"]
    prefix_chars = 0
    if loop_calls and static:
        first_asm = loop_calls[0]["assembly"] or {}
        static_chars = static.get("static_chars")
        first_system = first_asm.get("system_chars")
        if isinstance(static_chars, int) and isinstance(first_system, int):
            prefix_chars = max(0, first_system - static_chars - _RENDER_JOINER_CHARS)

    derived_calls = []
    for call in calls:
        entry: dict[str, Any] = {
            "call_id": call["call_id"],
            "seq": call["seq"],
            "surface": call["surface"],
            "mode": call["mode"],
            "intent": call["intent"],
            "payload_chars": call["payload_chars"],
            "payload_sha": call["payload_sha"],
            "checks": [],
        }
        checks = entry["checks"]

        # ── Every call: the fingerprint must be on the record ──────────
        if call["payload_chars"] is not None and call["payload_sha"]:
            checks.append(
                _verdict(
                    "fingerprint_present", _CHECK_PASS,
                    f"{call['payload_chars']} chars, sha {call['payload_sha']}",
                )
            )
        else:
            checks.append(
                _verdict(
                    "fingerprint_present", _CHECK_FAIL,
                    "model call carries no payload fingerprint — the record "
                    "cannot bound what was sent",
                )
            )

        # ── Audit level: match the wire dump ───────────────────────────
        if audit_by_sha or audit_by_chars:
            sha = str(call["payload_sha"] or "")
            line = audit_by_sha.get(sha)
            if line:
                entry["audit"] = {
                    "link": "sha",
                    "payload_chars": line.get("payload_chars"),
                    "system_tokens": line.get("system"),
                    "history_tokens": line.get("history"),
                    "current_tokens": line.get("current"),
                    "tools_tokens": line.get("tools"),
                }
                checks.append(
                    _verdict(
                        "audit_linked", _CHECK_PASS,
                        "audit line matched by payload sha — the wire payload "
                        "is byte-verified against the dump",
                    )
                )
            else:
                chars = call["payload_chars"]
                candidates = audit_by_chars.get(chars) if isinstance(chars, int) else None
                if candidates:
                    entry["audit"] = {
                        "link": "chars",
                        "payload_chars": chars,
                        "note": "chars match, sha differs — the wire payload was "
                                "a shape transform of the assembled input "
                                "(cache-control marking / content flattening)",
                    }
                    checks.append(
                        _verdict(
                            "audit_linked", _CHECK_WARN,
                            "audit line matched by size only — input→wire "
                            "transform detected",
                        )
                    )
                else:
                    entry["audit"] = {"link": "none"}
                    checks.append(
                        _verdict(
                            "audit_linked", _CHECK_WARN,
                            "no audit line for this call (auxiliary path, or "
                            "the audit wrote after this trace was taken)",
                        )
                    )

        if call["surface"] != "loop":
            derived_calls.append(entry)
            continue

        asm = call["assembly"] or {}
        entry["iteration"] = asm.get("iteration")
        entry["system"] = {
            "chars": asm.get("system_chars"),
            "sha": asm.get("system_sha16"),
            "stage": asm.get("system_stage"),
        }

        # ── The call must pair with its assembly record ────────────────
        if asm:
            if call["tool_count"] is not None and asm.get("tools") is not None:
                ok = int(call["tool_count"]) == int(asm["tools"])
                checks.append(
                    _verdict(
                        "assembly_paired", _CHECK_PASS if ok else _CHECK_FAIL,
                        f"tools {call['tool_count']} == assembly {asm['tools']}"
                        if ok
                        else f"tool count mismatch: call {call['tool_count']} "
                             f"vs assembly {asm['tools']}",
                    )
                )
            else:
                checks.append(
                    _verdict("assembly_paired", _CHECK_SKIP, "counts missing")
                )
        else:
            checks.append(
                _verdict("assembly_paired", _CHECK_FAIL, "no assembly record")
            )

        # ── Stage validity + first-call-full expectation ───────────────
        stage = asm.get("system_stage")
        if stage in _STAGE_EXCLUDES:
            if entry["iteration"] in (None, 1) and stage != "full":
                checks.append(
                    _verdict(
                        "stage_valid", _CHECK_FAIL,
                        f"first iteration carried stage {stage!r} — the first "
                        "call renders the canonical (full) prefix",
                    )
                )
            else:
                checks.append(
                    _verdict("stage_valid", _CHECK_PASS, f"stage {stage!r}")
                )
        else:
            checks.append(
                _verdict(
                    "stage_valid", _CHECK_FAIL,
                    f"unknown input-selection stage {stage!r}",
                )
            )

        # ── Exact char arithmetic for the system message ───────────────
        expected = _expected_staged_chars(static, stage or "", prefix_chars)
        recorded = asm.get("system_chars")
        if expected is not None and isinstance(recorded, int):
            ok = expected == recorded
            checks.append(
                _verdict(
                    "system_chars_arithmetic", _CHECK_PASS if ok else _CHECK_FAIL,
                    f"expected {expected} == recorded {recorded}"
                    if ok
                    else f"expected {expected} != recorded {recorded} "
                         "(composition and size disagree)",
                )
            )
        else:
            checks.append(
                _verdict(
                    "system_chars_arithmetic", _CHECK_SKIP,
                    "static composition or stage not on the record "
                    "(pre-G7 trace)",
                )
            )

        derived_calls.append(entry)

    # ── Cross-call: the same stage must render the same system bytes ────
    # A turn's iterations share one STATIC band, one TURN message and one
    # merged prefix, so a stage repeated across iterations must repeat its
    # system fingerprint — a divergence means something mutated the system
    # message mid-turn.
    stage_sha: dict[str, set] = {}
    for call in derived_calls:
        if call["surface"] != "loop":
            continue
        sys_info = call.get("system") or {}
        stage = sys_info.get("stage")
        sha = sys_info.get("sha")
        if stage and sha:
            stage_sha.setdefault(stage, set()).add(sha)
    sha_reuse = [
        _verdict(
            "system_sha_reuse", _CHECK_PASS if len(shas) == 1 else _CHECK_FAIL,
            f"stage {stage!r}: {len(shas)} distinct system fingerprint(s)"
            + ("" if len(shas) == 1 else " — the same stage rendered different "
               "system bytes within one turn (mid-turn mutation)"),
        )
        for stage, shas in stage_sha.items()
    ]

    # ── STATIC band checks (once per turn) ─────────────────────────────
    static_checks = []
    turn_checks = []
    if static and static.get("sections") is not None:
        names = [s["name"] for s in static["sections"]]
        unknown = [n for n in names if n not in SECTION_SLOTS]
        static_checks.append(
            _verdict(
                "static_sections_known", _CHECK_FAIL if unknown else _CHECK_PASS,
                f"{len(names)} sections" + (f"; unknown: {unknown}" if unknown else ""),
            )
        )
        if not unknown:
            static_checks.append(
                _verdict(
                    "static_render_order", _CHECK_PASS if _slot_sorted(names) else _CHECK_FAIL,
                    "render order " + " → ".join(names),
                )
            )
        # Budget contract from the record: the drop set must be a contiguous
        # SUFFIX of the FULL render order (kept + dropped re-inserted).
        dropped = [d for d in (static.get("dropped_sections") or []) if d]
        if dropped:
            kept_names = [n for n in names if n not in set(dropped)]
            kept_slots = [SECTION_SLOTS.get(n, -1) for n in kept_names]
            drop_slots = [SECTION_SLOTS.get(d, -1) for d in dropped]
            contiguous = (
                all(d in SOCIAL_DROP_SECTIONS for d in dropped)
                and (not kept_slots or min(drop_slots) > max(kept_slots))
            )
            static_checks.append(
                _verdict(
                    "budget_drop_contract",
                    _CHECK_PASS if contiguous else _CHECK_FAIL,
                    f"dropped {dropped} render after every kept section"
                    if contiguous
                    else f"dropped {dropped} is not a contiguous suffix of the "
                         "render order — the cacheable prefix forks",
                )
            )
        # Composition arithmetic: the BUDGETED render's size follows from
        # the sections minus the horizon's drops.
        dropped_set = set(dropped)
        comp = _joined_chars(
            [s["chars"] for s in static["sections"] if s["name"] not in dropped_set]
        )
        recorded = static.get("static_chars")
        if isinstance(recorded, int):
            static_checks.append(
                _verdict(
                    "static_chars_arithmetic", _CHECK_PASS if comp == recorded else _CHECK_FAIL,
                    f"expected {comp} == recorded {recorded}"
                    if comp == recorded
                    else f"expected {comp} != recorded {recorded}",
                )
            )
    elif static:
        static_checks.append(
            _verdict(
                "static_composition", _CHECK_SKIP,
                "pre-G7 record: static chars only, no per-section composition",
            )
        )

    # ── TURN message checks (once per turn) ────────────────────────────
    if turn and turn.get("sections") is not None:
        names = [s["name"] for s in turn["sections"]]
        unknown = [n for n in names if n not in SECTION_SLOTS]
        turn_checks.append(
            _verdict(
                "turn_sections_known", _CHECK_FAIL if unknown else _CHECK_PASS,
                f"{len(names)} sections" + (f"; unknown: {unknown}" if unknown else ""),
            )
        )
        if not unknown:
            turn_checks.append(
                _verdict(
                    "turn_render_order", _CHECK_PASS if _slot_sorted(names) else _CHECK_FAIL,
                    "render order " + " → ".join(names),
                )
            )
        comp = _joined_chars([s["chars"] for s in turn["sections"]])
        recorded = turn.get("rendered_chars")
        if isinstance(recorded, int):
            turn_checks.append(
                _verdict(
                    "turn_chars_arithmetic", _CHECK_PASS if comp == recorded else _CHECK_FAIL,
                    f"expected {comp} == recorded {recorded}"
                    if comp == recorded
                    else f"expected {comp} != recorded {recorded}",
                )
            )
        # Byte rebuild: exact whenever every section's text is on the
        # record. The environment section is composed FROM its fragments
        # (which ride the items in its place), so its text is not on the
        # record — the rebuild then stays arithmetic-only, honestly.
        items = turn.get("items") or []
        item_texts = {i["kind"]: i["text"] for i in items}
        missing = [
            s["name"]
            for s in turn["sections"]
            if s["name"] not in item_texts
        ]
        if not missing and turn.get("rendered_sha16"):
            rebuilt = _RENDER_JOINER.join(
                item_texts[s["name"]] for s in turn["sections"]
            )
            ok = _sha16(rebuilt) == turn["rendered_sha16"]
            turn_checks.append(
                _verdict(
                    "turn_message_rebuilt", _CHECK_PASS if ok else _CHECK_FAIL,
                    "rebuilt from the injected-items ledger; sha "
                    + ("matches the rendered stamp" if ok else "MISMATCH"),
                )
            )
        else:
            turn_checks.append(
                _verdict(
                    "turn_message_rebuilt", _CHECK_SKIP,
                    "not every section's exact text is on the record "
                    f"(missing: {missing or 'fingerprint stamp'}) — "
                    "arithmetic verification only",
                )
            )
    elif turn:
        turn_checks.append(
            _verdict(
                "turn_composition", _CHECK_SKIP,
                "pre-G7 record: injected items only, no rendered stamp",
            )
        )

    # ── What the record deliberately cannot derive ─────────────────────
    opaque = [
        "history message bytes (conversation contents live in the messages "
        "store; the trace carries their sizes only)",
        "tool-schema bytes (counted per call; the schema set is stable by "
        "design and its size is fingerprinted)",
        "auxiliary-call and fast-path payloads (``chat``-mode calls on this "
        "stream — fingerprinted here; their own surfaces derive in their own "
        "increment, loop first)",
        "the STATIC band's raw bytes (composition + fingerprint only; run "
        "the env-gated prompt-assembly audit for the byte-level dump)",
    ]

    all_checks = (
        static_checks
        + turn_checks
        + sha_reuse
        + [c for call in derived_calls for c in call["checks"]]
    )
    summary = {
        "pass": sum(1 for c in all_checks if c["status"] == _CHECK_PASS),
        "fail": sum(1 for c in all_checks if c["status"] == _CHECK_FAIL),
        "warn": sum(1 for c in all_checks if c["status"] == _CHECK_WARN),
        "unverifiable": sum(1 for c in all_checks if c["status"] == _CHECK_SKIP),
    }
    return {
        "turnId": turn_id,
        "derivation_level": "audit" if (audit_by_sha or audit_by_chars) else "record",
        "static": static,
        "turn_context": turn,
        "system_prefix_chars": prefix_chars,
        "calls": derived_calls,
        "static_checks": static_checks,
        "turn_checks": turn_checks,
        "sha_reuse_checks": sha_reuse,
        "opaque": opaque,
        "summary": summary,
    }


def derive_from_trace_payload(trace_payload: dict, audit_lines: Optional[list[dict]] = None) -> dict:
    """Derive from the trace-replay API response shape ({"turnId", "events"})."""
    return derive_turn(
        trace_payload.get("events") or [],
        audit_lines=audit_lines,
        turn_id=str(trace_payload.get("turnId") or ""),
    )

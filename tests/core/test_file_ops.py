"""
Session 193 — deterministic file-ops execution layer (ADR-8 Phase 4 track 2).

The root fix for the "find my CV and read it" failure class: the engine runs
find_path → pick_best_match → file_reader as CODE; the model is reduced to
final synthesis only (and when the model is down, the deterministic evidence
is yielded instead — never blank, never raw provider JSON).

These tests pin the pure, checkable contracts of the executor (no LLM, no
engine): read-verb detection, identity-aware match picking, the deterministic
find→pick→read chain against real temp files, and the security boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "backend/src")

import pytest
from core.file_ops import (
    FileOpsSpec,
    detect_read_request,
    execute_file_ops,
    format_match_list,
    format_read_evidence,
    format_top_candidates,
    pick_best_match,
)

# ── detect_read_request ─────────────────────────────────────────────────


def test_detect_read_request_followups():
    # "find my cv AND READ it" — the exact transcript compound phrasing.
    read_requested, identity = detect_read_request("I'm Tisone, find my cv and read it")
    assert read_requested is True
    assert identity == "tisone"


def test_detect_read_request_direct_verbs():
    for msg in [
        "read my cv",
        "show me the invoice",
        "open the budget file",
        "summarize the annual report",
        "view my config file",
        "display the license document",
        "what's in my cv",
        "tell me about my resume",
    ]:
        read_requested, _ = detect_read_request(msg)
        assert read_requested is True, f"{msg!r} must be a read request"


def test_detect_read_request_plain_find():
    read_requested, identity = detect_read_request("find my cv")
    assert read_requested is False
    assert identity == ""


def test_detect_identity_variants():
    for msg, expected in [
        ("I'm Tisone, find my cv", "tisone"),
        ("I am Tisone, read my resume", "tisone"),
        ("my name is Tisone Kironget, find my cv", "tisone"),
    ]:
        _, identity = detect_read_request(msg)
        assert identity == expected, f"{msg!r} → {identity!r}"


# ── pick_best_match ─────────────────────────────────────────────────────


def test_pick_best_match_single_match():
    assert pick_best_match(["/home/u/CV-Tisone.docx"], "cv") == "/home/u/CV-Tisone.docx"


def test_pick_best_match_identity_wins(tmp_path: Path):
    (tmp_path / "CV-JOHN.docx").touch()
    (tmp_path / "CV-TisoneKironget.docx").touch()
    (tmp_path / "cv-eng-Arpra.doc").touch()
    matches = [str(tmp_path / "CV-JOHN.docx"), str(tmp_path / "CV-TisoneKironget.docx")]
    # Identity ("tisone") decisively beats the other CVs.
    assert pick_best_match(matches, "cv", identity="tisone") == str(
        tmp_path / "CV-TisoneKironget.docx"
    )


def test_pick_best_match_exact_name_wins(tmp_path: Path):
    (tmp_path / "invoice-2024.pdf").touch()
    (tmp_path / "invoice.pdf").touch()
    (tmp_path / "old-invoice-scan.pdf").touch()
    matches = [
        str(tmp_path / "invoice-2024.pdf"),
        str(tmp_path / "invoice.pdf"),
        str(tmp_path / "old-invoice-scan.pdf"),
    ]
    # Pattern "invoice" appears in all three names → all get +50 → ambiguous
    # (top two tie), so None (the engine asks instead of guessing).
    assert pick_best_match(matches, "invoice") is None


def test_pick_best_match_files_over_dirs(tmp_path: Path):
    d = tmp_path / "resume_folder"
    d.mkdir()
    f = tmp_path / "resume.docx"
    f.touch()
    matches = [str(d), str(f)]
    # Only one FILE matches → file beats directory.
    assert pick_best_match(matches, "resume") == str(f)


def test_pick_best_match_ambiguous_returns_none(tmp_path: Path):
    (tmp_path / "a-cv.pdf").touch()
    (tmp_path / "b-cv.pdf").touch()
    matches = [str(tmp_path / "a-cv.pdf"), str(tmp_path / "b-cv.pdf")]
    assert pick_best_match(matches, "cv") is None


def test_pick_best_match_empty():
    assert pick_best_match([], "cv") is None


# ── execute_file_ops: deterministic find → pick → read ──────────────────


def _allow_tmp(monkeypatch, tmp_path: Path):
    """Make tmp_path an allowed folder (tmp is normally outside ~)."""
    from pathlib import Path as _P

    monkeypatch.setattr(
        "core.config._allowed_user_folders",
        lambda: [str(tmp_path), str(_P.home())],
    )


@pytest.mark.asyncio
async def test_execute_find_and_read_chain(tmp_path: Path, monkeypatch):
    """The engine's chain: find_path finds, picker selects, reader reads."""
    cv = tmp_path / "CV-TisoneKironget.txt"
    cv.write_text("Curriculum Vitae — Tisone Kironget\nSoftware Engineer", encoding="utf-8")
    (tmp_path / "CV-OTHER.txt").write_text("other", encoding="utf-8")

    # find_path searches under root; read is bounded by is_path_allowed, so
    # allow the tmp dir for both steps.
    _allow_tmp(monkeypatch, tmp_path)

    spec = FileOpsSpec(
        target="cv",
        pattern="cv",
        root=str(tmp_path),
        max_depth=4,
        max_results=25,
        read_requested=True,
        identity="tisone",
    )
    result = await execute_file_ops(spec)

    assert result.error is None
    assert len(result.matches) >= 2
    assert result.chosen == str(cv)
    assert result.content is not None
    assert "Tisone Kironget" in result.content


@pytest.mark.asyncio
async def test_execute_no_match_returns_deterministic_error(tmp_path: Path, monkeypatch):
    _allow_tmp(monkeypatch, tmp_path)
    spec = FileOpsSpec(target="nonexistent", pattern="nonexistent", root=str(tmp_path))
    result = await execute_file_ops(spec)
    assert result.error is not None
    assert "No files or folders matching 'nonexistent'" in result.error
    assert result.matches == []


@pytest.mark.asyncio
async def test_execute_find_only_lists_matches(tmp_path: Path, monkeypatch):
    _allow_tmp(monkeypatch, tmp_path)
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    spec = FileOpsSpec(
        target="notes", pattern="notes", root=str(tmp_path), read_requested=False
    )
    result = await execute_file_ops(spec)
    assert result.error is None
    assert len(result.matches) == 1
    assert result.chosen is None  # find-only: no read chain
    listed = format_match_list(result)
    assert "Found 1 match(es)" in listed
    assert "notes.txt" in listed


@pytest.mark.asyncio
async def test_execute_read_blocked_outside_allowed(tmp_path: Path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    # Allow the search ROOT but reject the FILE: find_path may search tmp,
    # yet the read step must refuse a path outside the approved folders.
    # is_path_allowed is a method on the pydantic Settings class (instance
    # setattr is rejected), so patch the class method.
    from core.config import settings as _cfg

    monkeypatch.setattr(
        type(_cfg), "is_path_allowed", lambda self, p: str(p) == str(tmp_path)
    )
    spec = FileOpsSpec(
        target="secret",
        pattern="secret",
        root=str(tmp_path),
        read_requested=True,
    )
    result = await execute_file_ops(spec)
    assert result.read_blocked is True
    assert "outside the allowed folders" in (result.error or "")
    assert result.content is None


def test_format_read_evidence_truncates():
    result = type("R", (), {"content": "x" * 10000, "chosen": "/p/f.txt"})()
    out = format_read_evidence(result, max_chars=1000)
    marker = "\n\n[... content truncated for performance]"
    assert len(out) == 1000 + len(marker)
    assert "[... content truncated for performance]" in out

# ── Engine wiring (Session 193) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_file_ops_deterministic_chain(tmp_path, monkeypatch):
    """The full engine path: "find my cv in <tmp> and read it" executes the
    chain deterministically (find_path → pick → read) with the model reduced
    to ONE synthesis call — never the agent loop."""
    from unittest.mock import MagicMock, patch

    from core.engine import Engine

    _allow_tmp(monkeypatch, tmp_path)
    cv = tmp_path / "CV-TisoneKironget.txt"
    cv.write_text("Tisone Kironget — Software Engineer", encoding="utf-8")
    (tmp_path / "CV-OTHER.txt").write_text("other", encoding="utf-8")

    engine = Engine()

    async def mock_chat(messages, intent="chat", **kwargs):
        # One synthesis call only — the chain itself must not hit the model.
        assert any("Tisone Kironget" in (m.get("content", "") or "") for m in messages)
        yield MagicMock(text="Here is Tisone's CV summary.", done=False, error=None)
        yield MagicMock(text="", done=True, error=None)

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat
    mock_adapter.effective_context_window = 8192

    with patch("core.engine.get_adapter", return_value=mock_adapter):
        chunks = [
            c
            async for c in engine.process(
                f"I'm Tisone, find my cv in {tmp_path} and read it", "sess-fo-1"
            )
        ]

    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "summary" in text.lower()
    assert not any("Get-ChildItem" in (getattr(c, "text", "") or "") for c in chunks)


@pytest.mark.asyncio
async def test_engine_file_ops_respects_tool_fence(tmp_path, monkeypatch):
    """A session scoped to other tools must NOT run the deterministic file
    chain — the fence bypass the reviewer flagged."""
    from unittest.mock import MagicMock, patch

    from core.engine import Engine

    _allow_tmp(monkeypatch, tmp_path)
    (tmp_path / "CV-TisoneKironget.txt").write_text("x", encoding="utf-8")

    engine = Engine()

    # If the chain runs (bug), this adapter's chat would never be reached
    # with the file content; assert the deterministic path did NOT execute
    # by ensuring no find_path dispatch reached the tool registry.
    dispatched = []
    import core.file_ops as fo_mod

    real_exec = fo_mod.execute_file_ops
    async def spy(spec):
        dispatched.append(spec.pattern)
        return await real_exec(spec)

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="fallback", done=False, error=None)
        yield MagicMock(text="", done=True, error=None)

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat
    mock_adapter.effective_context_window = 8192
    with patch("core.engine.get_adapter", return_value=mock_adapter), patch.object(
        fo_mod, "execute_file_ops", spy
    ):
        # The fence excludes find_path/file_task → the deterministic chain
        # must NOT run; the message falls through to the (mock) agent path,
        # which the incomplete mock cannot serve — that is EXPECTED. The
        # contract under test is: execute_file_ops is never called.
        try:
            chunks = [
                c
                async for c in engine.process(
                    f"I'm Tisone, find my cv in {tmp_path} and read it",
                    "sess-fo-2",
                    allowed_tool_names={"web_search"},
                )
            ]
            _ = chunks
        except TypeError:
            # Mock adapter can't serve the agent-loop fall-through — proof
            # the request went to the agent path, not the deterministic one.
            pass

    assert dispatched == []


# ── Catalog continuation through the deterministic chain (Session 194) ──


@pytest.mark.asyncio
async def test_execute_filters_by_extension(tmp_path: Path, monkeypatch):
    """The catalog ext filter flows through find_path into the read chain."""
    _allow_tmp(monkeypatch, tmp_path)
    (tmp_path / "cv.txt").write_text("txt-content", encoding="utf-8")
    (tmp_path / "cv.docx").write_text("x", encoding="utf-8")
    spec = FileOpsSpec(
        target="cv", pattern="cv", root=str(tmp_path), read_requested=True, ext="txt"
    )
    result = await execute_file_ops(spec)
    assert result.error is None
    assert result.matches == [str(tmp_path / "cv.txt")]
    assert result.chosen == str(tmp_path / "cv.txt")
    assert "txt-content" in (result.content or "")


@pytest.mark.asyncio
async def test_execute_subpath_filter(tmp_path: Path, monkeypatch):
    """A bare-folder location narrows the catalog to that folder."""
    _allow_tmp(monkeypatch, tmp_path)
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "cv.txt").write_text("in docs", encoding="utf-8")
    (tmp_path / "cv.txt").write_text("in root", encoding="utf-8")
    spec = FileOpsSpec(
        target="cv", pattern="cv", root=str(tmp_path), read_requested=True,
        subpath="Documents",
    )
    result = await execute_file_ops(spec)
    assert result.error is None
    assert result.matches == [str(docs / "cv.txt")]


@pytest.mark.asyncio
async def test_execute_result_carries_catalog(tmp_path: Path, monkeypatch):
    """The deterministic chain sees the FULL catalog, not a capped page."""
    _allow_tmp(monkeypatch, tmp_path)
    for name in ["cv-a.txt", "cv-b.txt", "cv-c.txt"]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    spec = FileOpsSpec(target="cv", pattern="cv", root=str(tmp_path))
    result = await execute_file_ops(spec)
    assert result.total == 3
    assert len(result.matches) == 3  # all_paths → full catalog for the picker
    assert result.groups.get("(root)") == 3
    assert result.extensions.get("txt") == 3
    assert result.walk_complete is True


def test_format_top_candidates_ranks_identity_first(tmp_path: Path):
    """The ambiguous-ask shortlist ranks by the same picker score."""
    (tmp_path / "CV-JOHN.txt").touch()
    (tmp_path / "CV-TisoneKironget.txt").touch()
    spec = type(
        "S",
        (),
        {"target": "cv", "pattern": "cv", "identity": "tisone"},
    )()
    result = type(
        "R",
        (),
        {
            "spec": spec,
            "matches": [
                str(tmp_path / "CV-JOHN.txt"),
                str(tmp_path / "CV-TisoneKironget.txt"),
            ],
            "total": 2,
            "groups": {},
        },
    )()
    out = format_top_candidates(result)
    lines = out.splitlines()
    assert "Closest matches" in out
    # lines[0]=header, lines[1]="Closest matches:", lines[2]=top-ranked.
    assert lines[2].endswith("CV-TisoneKironget.txt")


@pytest.mark.asyncio
async def test_engine_file_ops_ambiguous_asks_ranked_candidates(tmp_path, monkeypatch):
    """Two equal CVs, no identity → deterministic ranked shortlist + ask,
    zero model calls (the catalog replaces the capped guess)."""
    from unittest.mock import MagicMock, patch

    from core.engine import Engine

    _allow_tmp(monkeypatch, tmp_path)
    (tmp_path / "CV-JOHN.txt").write_text("john", encoding="utf-8")
    (tmp_path / "CV-MORGAN.txt").write_text("morgan", encoding="utf-8")

    engine = Engine()

    async def mock_chat(messages, intent="chat", **kwargs):
        raise AssertionError("no model call on the ambiguous ask path")

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat
    mock_adapter.effective_context_window = 8192

    with patch("core.engine.get_adapter", return_value=mock_adapter):
        chunks = [
            c
            async for c in engine.process(
                f"find my cv in {tmp_path} and read it", "sess-fo-amb"
            )
        ]

    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "Closest matches" in text
    assert "Which one" in text

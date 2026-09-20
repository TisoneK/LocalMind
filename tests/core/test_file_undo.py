"""Undo restores what the agent overwrote, and refuses when that would destroy newer work."""

import pytest
from core.file_undo import apply_undo, save_undo


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "localmind_home", str(tmp_path / "home"))


def test_overwrite_is_restored(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("new", encoding="utf-8")
    uid = save_undo(str(f), "old", "new")
    assert apply_undo(uid) == (True, "Restored the previous version.")
    assert f.read_text(encoding="utf-8") == "old"


def test_a_file_the_agent_created_is_removed(tmp_path):
    f = tmp_path / "b.txt"
    f.write_text("fresh", encoding="utf-8")
    uid = save_undo(str(f), "", "fresh")
    assert apply_undo(uid) == (True, "Removed the file.")
    assert not f.exists()


def test_refuses_when_the_file_changed_since(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("new", encoding="utf-8")
    uid = save_undo(str(f), "old", "new")
    f.write_text("edited by me", encoding="utf-8")
    ok, msg = apply_undo(uid)
    assert not ok and "changed since" in msg
    assert f.read_text(encoding="utf-8") == "edited by me"


def test_undo_is_single_use_and_rejects_forged_ids(tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("new", encoding="utf-8")
    uid = save_undo(str(f), "old", "new")
    assert apply_undo(uid)[0]
    assert not apply_undo(uid)[0]
    assert not apply_undo("../../etc/passwd")[0]
    assert not apply_undo("z" * 24)[0]


def test_nothing_to_undo_when_content_is_unchanged(tmp_path):
    assert save_undo(str(tmp_path / "e.txt"), "same", "same") is None


def test_edit_file_undo_id_is_built_from_the_backup(tmp_path):
    from core.agent.loop import _undo_id_for_edit

    f = tmp_path / "e.py"
    b = tmp_path / "e.py.bak"
    b.write_text("original", encoding="utf-8")
    f.write_text("edited", encoding="utf-8")
    uid = _undo_id_for_edit({"path": str(f), "backup_path": str(b)})
    assert uid and apply_undo(uid)[0]
    assert f.read_text(encoding="utf-8") == "original"
    assert _undo_id_for_edit({"path": str(f)}) is None

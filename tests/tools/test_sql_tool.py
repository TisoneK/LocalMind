"""Tests for the read-only SQL tool (B-2026-07-31-10, Session 132)."""

import asyncio
import sqlite3

import core.config as cfg
import pytest
from core.models import Intent
from tools import dispatch
from tools.sql_tool import _sql_query


@pytest.fixture
def sample_db(tmp_path):
    """A small sqlite database in tmp_path (plus allowlist patch)."""
    original = cfg._allowed_user_folders
    cfg._allowed_user_folders = lambda: [
        str(tmp_path),
        str(tmp_path.resolve()),
        str(__import__("pathlib").Path.home()),
    ]
    db = tmp_path / "sample.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE users (id INTEGER, name TEXT, city TEXT)")
    conn.executemany(
        "INSERT INTO users VALUES (?, ?, ?)",
        [(i, f"user{i}", "NYC" if i % 2 else "SF") for i in range(50)],
    )
    conn.execute("CREATE TABLE settings (k TEXT, v TEXT)")
    conn.execute("INSERT INTO settings VALUES ('theme', 'dark')")
    conn.commit()
    conn.close()
    yield db
    cfg._allowed_user_folders = original


def test_basic_select(sample_db):
    out = _sql_query(str(sample_db), "SELECT id, name FROM users WHERE id < 3")
    assert "3 row(s) returned" in out
    assert "user0" in out
    assert "user2" in out


def test_truncates_rows(sample_db):
    out = _sql_query(str(sample_db), "SELECT id, name FROM users", max_rows=5)
    assert "5 row(s) returned" in out
    assert "… more rows exist (capped at 5)" in out


def test_empty_result(sample_db):
    out = _sql_query(str(sample_db), "SELECT * FROM users WHERE id = 999")
    assert "0 rows" in out


def test_write_attempt_fails_safely(sample_db):
    """Read-only mode must block writes even on a writable db file."""
    out = _sql_query(str(sample_db), "DROP TABLE users")
    assert "readonly" in out.lower() or "Error" in out
    # The table must still exist afterwards
    conn = sqlite3.connect(sample_db)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    conn.close()
    assert "users" in tables


def test_insert_fails_safely(sample_db):
    out = _sql_query(str(sample_db), "INSERT INTO users VALUES (999, 'x', 'y')")
    assert "readonly" in out.lower() or "Error" in out


def test_rejects_disallowed_path(tmp_path):
    db = tmp_path / "secret.db"
    sqlite3.connect(db).close()
    # tmp_path is NOT allowed here (no allowlist patch)
    out = _sql_query(str(db), "SELECT 1")
    assert "path not allowed" in out


def test_missing_file_is_error(sample_db):
    out = _sql_query(str(sample_db.parent / "nope.db"), "SELECT 1")
    assert "cannot open" in out


def test_not_a_database(allow_tmp):
    p = allow_tmp / "plain.txt"
    p.write_text("hello world")
    out = _sql_query(str(p), "SELECT 1")
    assert "cannot open" in out or "database" in out.lower()


def test_invalid_sql(sample_db):
    out = _sql_query(str(sample_db), "SELECT FROM WHERE")
    assert "query failed" in out


def test_rejects_attach(sample_db):
    """ATTACH would bypass is_path_allowed on other db files — must be rejected."""
    out = _sql_query(str(sample_db), "ATTACH DATABASE '/etc/passwd' AS p")
    assert "ATTACH is not allowed" in out


def test_path_with_special_chars(sample_db, tmp_path):
    """Paths with URI-special chars (space, #) must resolve correctly."""
    weird = tmp_path / "my stuff"
    weird.mkdir()
    db = weird / "data#1.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('ok')")
    conn.commit()
    conn.close()
    out = _sql_query(str(db), "SELECT v FROM t")
    assert "ok" in out


def test_never_raises_on_garbage(sample_db):
    out = _sql_query(str(sample_db), ";;; not sql ;;;")
    assert isinstance(out, str) and out


def test_dispatch_sql_registered(sample_db):
    import json

    args = json.dumps({"path": str(sample_db), "query": "SELECT v FROM settings"})
    result = asyncio.run(dispatch(Intent.SQL, args))
    assert result is not None
    assert "dark" in result.content
    assert result.source == "sql"
    assert result.metadata.get("readonly") is True


@pytest.fixture
def allow_tmp(tmp_path):
    """Allow tmp_path for the not-a-database test."""
    original = cfg._allowed_user_folders
    cfg._allowed_user_folders = lambda: [
        str(tmp_path),
        str(tmp_path.resolve()),
        str(__import__("pathlib").Path.home()),
    ]
    yield tmp_path
    cfg._allowed_user_folders = original

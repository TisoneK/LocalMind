"""The backend serves the built UI, so the desktop window loads it over http, not from disk."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (tmp_path / "assets" / "a.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("nope", encoding="utf-8")
    monkeypatch.setenv("LOCALMIND_FRONTEND_DIST", str(tmp_path))
    from api.app import create_app

    return TestClient(create_app())


def test_root_and_client_routes_get_index(client):
    assert "app" in client.get("/").text
    assert "app" in client.get("/some/route").text


def test_assets_are_served_as_files(client):
    r = client.get("/assets/a.js")
    assert r.status_code == 200 and "console.log" in r.text


def test_cannot_read_outside_the_dist_folder(client):
    r = client.get("/..%2Fsecret.txt")
    assert "nope" not in r.text


def test_unknown_api_paths_stay_404(client):
    assert client.get("/api/definitely-not-a-route").status_code == 404

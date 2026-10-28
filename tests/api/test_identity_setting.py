"""POST /api/settings/identity — the stated-facts write path.

Pins the full round trip of the user-stated identity facts:

- the endpoint persists both fields (including an intentional CLEAR —
  the generic save path would keep the old value instead) and refreshes
  the injected cache hot, so the next message already carries the change;
- GET /api/settings exposes the fields back for the Settings UI;
- the Settings-level load path restores the facts from settings.json
  across a restart (a stored empty value stays cleared — never re-filled).
"""

from __future__ import annotations

import json
import types

import pytest

from api.routes import config as config_mod
from core.config import Settings
from core.user_profile import get_cached_profile, set_cached_profile


def _fake_settings_for_identity():
    saved: dict = {}

    class _Fake:
        def save_user_identity(self, user_name, user_place):
            saved["user_name"] = user_name
            saved["user_place"] = user_place

    ns = _Fake()
    ns._saved = saved
    return ns


@pytest.mark.asyncio
async def test_set_identity_persists_and_refreshes_cache(monkeypatch):
    from api.routes.config import IdentityRequest, set_identity

    fake = _fake_settings_for_identity()
    monkeypatch.setattr(config_mod, "settings", fake)
    set_cached_profile("", "")

    resp = await set_identity(IdentityRequest(user_name="  Amani  ", user_place="Nairobi, Kenya"))

    assert fake._saved == {"user_name": "Amani", "user_place": "Nairobi, Kenya"}
    assert resp["user_name"] == "Amani"
    # Hot-apply: the injected cache reflects the save immediately — the
    # next message carries the stated facts without a restart.
    assert get_cached_profile() == {"name": "Amani", "place": "Nairobi, Kenya"}


@pytest.mark.asyncio
async def test_set_identity_clear_is_a_real_clear(monkeypatch):
    from api.routes.config import IdentityRequest, set_identity

    fake = _fake_settings_for_identity()
    monkeypatch.setattr(config_mod, "settings", fake)
    set_cached_profile("Amani", "Nairobi, Kenya")

    await set_identity(IdentityRequest(user_name="", user_place=""))

    # An empty save is an intentional CLEAR: persisted as empty and the
    # cache flips to the declared-absent form — never the old values.
    assert fake._saved == {"user_name": "", "user_place": ""}
    assert get_cached_profile() == {"name": "", "place": ""}


@pytest.mark.asyncio
async def test_set_identity_caps_memoir_sized_values(monkeypatch):
    from api.routes.config import IdentityRequest, set_identity

    fake = _fake_settings_for_identity()
    monkeypatch.setattr(config_mod, "settings", fake)

    await set_identity(IdentityRequest(user_name="x" * 500, user_place="y" * 500))

    assert len(fake._saved["user_name"]) == 200
    assert len(fake._saved["user_place"]) == 200


@pytest.mark.asyncio
async def test_get_settings_exposes_the_stated_facts(monkeypatch):
    from api.routes.config import get_settings

    base = await get_settings()
    monkeypatch.setattr(config_mod.settings, "localmind_user_name", "Amani", raising=False)
    monkeypatch.setattr(
        config_mod.settings, "localmind_user_place", "Nairobi, Kenya", raising=False
    )
    try:
        resp = await get_settings()
        assert resp.user_name == "Amani"
        assert resp.user_place == "Nairobi, Kenya"
    finally:
        # restore for the cached-module singleton other tests read
        monkeypatch.setattr(config_mod.settings, "localmind_user_name", base.user_name, raising=False)
        monkeypatch.setattr(config_mod.settings, "localmind_user_place", base.user_place, raising=False)


class TestSettingsPersistence:
    """The Settings-level load path: facts survive a restart; a stored
    empty value stays cleared. Runs against a scratch settings file —
    never the developer's real one."""

    def _fresh_settings(self, tmp_path):
        s = Settings()
        s.localmind_home = str(tmp_path)
        s.resolve_paths()
        return s

    def test_save_then_load_round_trip(self, tmp_path):
        s = self._fresh_settings(tmp_path)
        s.save_user_identity("Amani", "Nairobi, Kenya")
        assert (tmp_path / "settings.json").exists()

        fresh = self._fresh_settings(tmp_path)
        fresh.load_runtime_settings()
        assert fresh.localmind_user_name == "Amani"
        assert fresh.localmind_user_place == "Nairobi, Kenya"

    def test_stored_clear_stays_cleared(self, tmp_path):
        s = self._fresh_settings(tmp_path)
        s.save_user_identity("Amani", "Nairobi, Kenya")
        s.save_user_identity("", "")

        fresh = self._fresh_settings(tmp_path)
        fresh.load_runtime_settings()
        assert fresh.localmind_user_name == ""
        assert fresh.localmind_user_place == ""

    def test_stored_file_shape_is_plain_json(self, tmp_path):
        s = self._fresh_settings(tmp_path)
        s.save_user_identity("Amani", "Nairobi, Kenya")
        data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        assert data["user_name"] == "Amani"
        assert data["user_place"] == "Nairobi, Kenya"

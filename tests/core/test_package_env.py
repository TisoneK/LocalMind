"""`pip install` goes where the user chose: LocalMind's own folder by default, or the system Python."""

import os

import pytest
from core import package_env
from core.config import settings


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "localmind_home", str(tmp_path / "home"))
    monkeypatch.setattr(settings, "localmind_package_env", "localmind", raising=False)


def target():
    return str(package_env.packages_dir())


def test_pip_install_goes_to_localmind_folder_by_default():
    out = package_env.rewrite_install("pip install Pillow")
    assert out == f"pip install --target {target()} Pillow"


def test_variants_and_compound_commands_only_touch_the_install_verb():
    assert "--target" in package_env.rewrite_install("python -m pip install requests")
    assert "--target" in package_env.rewrite_install("pip3 install x && python run.py")
    assert package_env.rewrite_install("pip3 install x && python run.py").endswith("&& python run.py")
    assert package_env.rewrite_install("ls -la") == "ls -la"
    assert package_env.rewrite_install("pip list") == "pip list"


def test_an_install_that_already_picks_a_destination_is_left_alone():
    for cmd in ("pip install --user x", "pip install -t ./vendor x", "pip install --target /tmp/y x"):
        assert package_env.rewrite_install(cmd) == cmd


def test_system_mode_changes_nothing(monkeypatch):
    monkeypatch.setattr(settings, "localmind_package_env", "system", raising=False)
    assert package_env.rewrite_install("pip install Pillow") == "pip install Pillow"
    assert "PYTHONPATH" not in package_env.apply_env({"PATH": "x"})


def test_packages_folder_is_put_on_pythonpath_once():
    env = package_env.apply_env({"PYTHONPATH": "/a"})
    assert env["PYTHONPATH"].split(os.pathsep)[0] == target()
    assert package_env.apply_env(env)["PYTHONPATH"].count(target()) == 1


def test_unknown_mode_falls_back_to_localmind(monkeypatch):
    monkeypatch.setattr(settings, "localmind_package_env", "bogus", raising=False)
    assert package_env.mode() == "localmind"
